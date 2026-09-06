import pytest
from flask_socketio.test_client import SocketIOTestClient

from app import create_app
from app.extensions import db, socketio
from app.models import DeviceSession, TeamMember
from app.services import realtime
from test_turns import (
    HOST_TOKEN_HEADER,
    MANGHUHULA,
    TAGASAGOT,
    _add_member,
    _assign_roles,
    _assign_turn_words,
    _connect,
    _create_category,
    _create_game,
    _create_matches,
    _create_team,
    _submit_words,
)


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


class Setup:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _setup(client):
    game_id, host = _create_game(client)
    team_a = _create_team(client, game_id, "Team A")
    team_b = _create_team(client, game_id, "Team B")
    leader_a = team_a["leader"]
    leader_b = team_b["leader"]
    sess_a = _connect(client, leader_a)["session_token"]
    sess_b = _connect(client, leader_b)["session_token"]
    member_a = _add_member(client, team_a["team_id"], "Maria")
    member_b = _add_member(client, team_b["team_id"], "Kris")

    cats = [
        _create_category(client, game_id, host, "Food"),
        _create_category(client, game_id, host, "Animals"),
    ]
    words_a0 = _submit_words(
        client, game_id, team_a["team_id"], cats[0], ["a01", "a02", "a03", "a04", "a05"], sess_a
    )
    words_b0 = _submit_words(
        client, game_id, team_b["team_id"], cats[0], ["b01", "b02", "b03", "b04", "b05"], sess_b
    )

    _assign_roles(
        client,
        team_a,
        [(leader_a["member_id"], MANGHUHULA), (member_a["member_id"], TAGASAGOT)],
        host,
    )
    _assign_roles(
        client,
        team_b,
        [(leader_b["member_id"], MANGHUHULA), (member_b["member_id"], TAGASAGOT)],
        host,
    )

    assert (
        client.post(
            "/api/games/{}/rounds".format(game_id),
            json={"round_number": 1},
            headers={HOST_TOKEN_HEADER: host},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/games/{}/rounds/1/categories".format(game_id),
            json={"category_ids": cats},
            headers={HOST_TOKEN_HEADER: host},
        ).status_code
        == 200
    )
    resp = _create_matches(
        client,
        game_id,
        host,
        1,
        [
            {"team_id": team_a["team_id"], "opponent_team_id": team_b["team_id"]},
            {"team_id": team_b["team_id"], "opponent_team_id": team_a["team_id"]},
        ],
    )
    assert resp.status_code == 201
    matches = resp.get_json()["data"]["matches"]
    match_a = next(m for m in matches if m["team_id"] == team_a["team_id"])
    match_b = next(m for m in matches if m["team_id"] == team_b["team_id"])

    return Setup(
        game_id=game_id,
        host=host,
        team_a=team_a,
        team_b=team_b,
        leader_a=leader_a,
        leader_b=leader_b,
        sess_a=sess_a,
        sess_b=sess_b,
        member_a=member_a,
        member_b=member_b,
        cats=cats,
        words_a0=words_a0,
        words_b0=words_b0,
        match_a=match_a,
        match_b=match_b,
    )


def _socket(app, token, device_id=None):
    query_string = "device_id={}".format(device_id) if device_id else None
    return SocketIOTestClient(
        app, socketio, auth={"token": token}, query_string=query_string
    )


def _named(events, name):
    return [e for e in events if e["name"] == name]


def _peer_sid(member_id):
    for sid, peer in realtime.SOCKET_PEERS.items():
        if peer.get("member_id") == member_id:
            return sid
    return None


def _turn_by_assign(client, host, match, words):
    resp = _assign_turn_words(
        client, host, match["match_id"], word_ids=words
    )
    assert resp.status_code == 201
    return resp.get_json()["data"]["turn_id"]


def _start_turn(client, host, match):
    resp = client.post(
        "/api/matches/{}/turn/start".format(match["match_id"]),
        headers={HOST_TOKEN_HEADER: host},
    )
    assert resp.status_code == 200
    return resp.get_json()["data"]


def _host_post(client, host, path, **kwargs):
    return client.post(path, headers={HOST_TOKEN_HEADER: host}, **kwargs)


# ---------------------------------------------------------------------------
# 1. Host socket connection
# ---------------------------------------------------------------------------


def test_host_socket_connection(app, client):
    game_id, host = _create_game(client)
    sio = _socket(app, host)
    assert sio.is_connected()

    sid = _peer_sid(None) or [
        s for s, p in realtime.SOCKET_PEERS.items() if p.get("role") == "HOST"
    ][0]
    peer = realtime.SOCKET_PEERS[sid]
    assert peer["role"] == "HOST"
    assert peer["game_id"] == game_id
    assert realtime.game_room(game_id) in socketio.server.rooms(sid)

    sio.disconnect()
    assert sid not in realtime.SOCKET_PEERS


# ---------------------------------------------------------------------------
# 2. Team member socket connections
# ---------------------------------------------------------------------------


def test_team_and_member_socket_connections(app, client):
    game_id, host = _create_game(client)
    host_sio = _socket(app, host)
    team = _create_team(client, game_id, "Team A")
    leader = team["leader"]
    member = _add_member(client, team["team_id"], "Maria")

    leader_sio = _socket(
        app, _connect(client, leader)["session_token"]
    )
    member_sio = _socket(
        app, _connect(client, member, device_id="dev-2")["session_token"]
    )
    assert leader_sio.is_connected()
    assert member_sio.is_connected()

    leader_sid = _peer_sid(leader["member_id"])
    assert leader_sid is not None
    peer = realtime.SOCKET_PEERS[leader_sid]
    assert peer["role"] == "TEAM_LEADER"
    assert peer["team_id"] == team["team_id"]
    rooms = socketio.server.rooms(leader_sid)
    assert realtime.game_room(game_id) in rooms
    assert realtime.team_room(team["team_id"]) in rooms

    with app.app_context():
        member_row = db.session.get(TeamMember, member["member_id"])
        assert member_row.is_connected is True

    host_events = host_sio.get_received()
    assert len(_named(host_events, "team_connected")) == 2

    host_sio.disconnect()
    leader_sio.disconnect()
    member_sio.disconnect()


# ---------------------------------------------------------------------------
# 3. Game room isolation
# ---------------------------------------------------------------------------


def test_game_rooms_isolate_games(app, client):
    game_a_id, host_a = _create_game(client)
    game_b_id, host_b = _create_game(client)
    socket_a = _socket(app, host_a)
    socket_b = _socket(app, host_b)
    socket_a.get_received()
    socket_b.get_received()

    socketio.emit("ping", {"from_game": game_a_id}, room=realtime.game_room(game_a_id))

    assert len(_named(socket_a.get_received(), "ping")) == 1
    assert len(_named(socket_b.get_received(), "ping")) == 0

    socket_a.disconnect()
    socket_b.disconnect()


# ---------------------------------------------------------------------------
# 4. Team room isolation
# ---------------------------------------------------------------------------


def test_team_rooms_isolate_teams(app, client):
    game_id, host = _create_game(client)
    host_sio = _socket(app, host)
    team_a = _create_team(client, game_id, "Team A")
    team_b = _create_team(client, game_id, "Team B")
    team_a_sio = _socket(app, _connect(client, team_a["leader"])["session_token"])
    team_b_sio = _socket(
        app, _connect(client, team_b["leader"], device_id="dev-2")["session_token"]
    )
    for sio in (host_sio, team_a_sio, team_b_sio):
        sio.get_received()

    socketio.emit("ping", {"x": 1}, room=realtime.team_room(team_a["team_id"]))

    assert len(_named(team_a_sio.get_received(), "ping")) == 1
    assert len(_named(team_b_sio.get_received(), "ping")) == 0
    assert len(_named(host_sio.get_received(), "ping")) == 0

    host_sio.disconnect()
    team_a_sio.disconnect()
    team_b_sio.disconnect()


# ---------------------------------------------------------------------------
# 5. Secret words reach only the Manghuhula
# ---------------------------------------------------------------------------


def test_secret_words_only_reach_manghuhula(app, client):
    s = _setup(client)
    host_sio = _socket(app, s.host)
    manghuhula_sio = _socket(app, _connect(client, s.leader_a)["session_token"])
    tagasagot_sio = _socket(
        app, _connect(client, s.member_a, device_id="dev-2")["session_token"]
    )
    opponent_sio = _socket(
        app, _connect(client, s.leader_b, device_id="dev-3")["session_token"]
    )
    for sio in (host_sio, manghuhula_sio, tagasagot_sio, opponent_sio):
        sio.get_received()

    _turn_by_assign(client, s.host, s.match_a, s.words_b0[:3])
    assert _start_turn(client, s.host, s.match_a).get("turn_id") is not None

    def assert_public(events):
        for event in _named(events, "turn_started"):
            payload = event["args"][0]
            assert "words" not in payload
            assert "current_word_text" not in payload

    assert_public(host_sio.get_received())
    assert_public(tagasagot_sio.get_received())
    assert_public(opponent_sio.get_received())

    secret = None
    for event in _named(manghuhula_sio.get_received(), "turn_started"):
        payload = event["args"][0]
        if "words" in payload:
            secret = payload
    assert secret is not None
    texts = [w["word_text"] for w in secret["words"]]
    assert sorted(texts) == sorted(["b01", "b02", "b03"])

    host_sio.disconnect()
    manghuhula_sio.disconnect()
    tagasagot_sio.disconnect()
    opponent_sio.disconnect()


# ---------------------------------------------------------------------------
# 6. Reconnection
# ---------------------------------------------------------------------------


def test_reconnection_updates_session_state(app, client):
    game_id, host = _create_game(client)
    host_sio = _socket(app, host)
    team = _create_team(client, game_id, "Team A")
    leader = team["leader"]
    member_id = leader["member_id"]
    session = _connect(client, leader)
    session_token = session["session_token"]

    member_sio = _socket(app, session_token)
    with app.app_context():
        assert db.session.get(TeamMember, member_id).is_connected is True

    member_sio.disconnect()
    with app.app_context():
        assert db.session.get(TeamMember, member_id).is_connected is False
        stored = DeviceSession.query.filter_by(session_token=session_token).first()
        assert stored.disconnected_at is not None

    host_sio.get_received()
    reconnected = _socket(app, session_token)
    assert reconnected.is_connected()
    with app.app_context():
        assert db.session.get(TeamMember, member_id).is_connected is True
        stored = DeviceSession.query.filter_by(session_token=session_token).first()
        assert stored.disconnected_at is None
    assert len(_named(host_sio.get_received(), "team_connected")) == 1

    host_sio.disconnect()
    host_sio2 = _socket(app, host)
    assert host_sio2.is_connected()

    reconnected.disconnect()
    host_sio2.disconnect()


# ---------------------------------------------------------------------------
# 7. Unauthorized socket connections
# ---------------------------------------------------------------------------


def test_unauthorized_socket_connect(app, client):
    bad = SocketIOTestClient(app, socketio, auth={"token": "bogus-token"})
    assert not bad.is_connected()

    missing = SocketIOTestClient(app, socketio)
    assert not missing.is_connected()


# ---------------------------------------------------------------------------
# 7a. Unexpected errors inside the connect handler must surface as a clean,
#     controllable refusal (CONNECT_INTERNAL_ERROR), never as an opaque HTTP
#     500 to the socket client. The full cause is logged server-side.
# ---------------------------------------------------------------------------


def test_connect_internal_error_refused_not_500(app, client, monkeypatch, caplog):
    import logging

    from app.sockets import events as socket_events

    # A valid host token so the guard passes; the injected fault then fires
    # inside the authorize step, exactly like a DB/emit crash mid-handshake.
    game_id, host_token = _create_game(client)
    assert host_token

    def boom(token):
        raise RuntimeError("simulated connect-handshake failure")

    monkeypatch.setattr(socket_events, "_authorize_and_join", boom)

    with caplog.at_level(logging.ERROR, logger="app"):
        sio = SocketIOTestClient(app, socketio, auth={"token": host_token})

    # The socket was refused (clean), NOT an HTTP 500; and the connect
    # failure was logged server-side with an exception, not swallowed.
    assert not sio.is_connected()
    assert any(
        "Socket connect handler failed" in getattr(r, "message", "")
        and r.exc_info is not None
        for r in caplog.records
    )


# ---------------------------------------------------------------------------
# 8. Realtime host event flow (game, round, match, turn, timer)
# ---------------------------------------------------------------------------


def test_realtime_host_event_flow(app, client):
    s = _setup(client)
    host_sio = _socket(app, s.host)
    host_sio.get_received()

    assert _host_post(client, s.host, "/api/games/{}/start".format(s.game_id)).status_code == 200
    assert len(_named(host_sio.get_received(), "game_started")) == 1

    turn_a = _turn_by_assign(client, s.host, s.match_a, s.words_b0[:4])
    _start_turn(client, s.host, s.match_a)
    events = host_sio.get_received()
    assert len(_named(events, "round_started")) == 1
    assert len(_named(events, "match_started")) == 1
    assert len(_named(events, "turn_started")) == 1
    assert len(_named(events, "timer_updated")) == 1

    host = s.host
    assert _host_post(client, host, "/api/turns/{}/correct".format(turn_a)).status_code == 200
    assert len(_named(host_sio.get_received(), "word_correct")) == 1

    assert _host_post(client, host, "/api/turns/{}/pass".format(turn_a)).status_code == 200
    assert len(_named(host_sio.get_received(), "word_passed")) == 1

    assert _host_post(
        client, host, "/api/turns/{}/time/add".format(turn_a), json={"seconds": 15}
    ).status_code == 200
    time_events = host_sio.get_received()
    assert len(_named(time_events, "time_added")) == 1
    assert len(_named(time_events, "penalty_applied")) == 1

    assert _host_post(client, host, "/api/turns/{}/pause".format(turn_a)).status_code == 200
    assert len(_named(host_sio.get_received(), "timer_paused")) == 1

    assert _host_post(client, host, "/api/turns/{}/resume".format(turn_a)).status_code == 200
    assert len(_named(host_sio.get_received(), "timer_resumed")) == 1

    assert _host_post(
        client, host, "/api/turns/{}/time/remove".format(turn_a), json={"seconds": 5}
    ).status_code == 200
    time_events = host_sio.get_received()
    assert len(_named(time_events, "time_removed")) == 1
    assert len(_named(time_events, "penalty_applied")) == 1

    assert _host_post(client, host, "/api/turns/{}/correct".format(turn_a)).status_code == 200
    assert _host_post(client, host, "/api/turns/{}/correct".format(turn_a)).status_code == 200
    completed_events = host_sio.get_received()
    assert len(_named(completed_events, "turn_completed")) == 1

    turn_b = _turn_by_assign(client, host, s.match_b, s.words_a0[:3])
    _start_turn(client, host, s.match_b)
    host_sio.get_received()
    assert _host_post(client, host, "/api/turns/{}/end".format(turn_b)).status_code == 200
    end_events = host_sio.get_received()
    assert len(_named(end_events, "turn_completed")) == 1
    assert len(_named(end_events, "round_completed")) == 1

    host_sio.disconnect()


# ---------------------------------------------------------------------------
# Join turn room authorization + turn state
# ---------------------------------------------------------------------------


def test_join_turn_room_and_state(app, client):
    s = _setup(client)
    host_sio = _socket(app, s.host)
    tagasagot_sio = _socket(
        app, _connect(client, s.member_a, device_id="dev-2")["session_token"]
    )
    outsider_sio = _socket(
        app, _connect(client, s.member_b, device_id="dev-3")["session_token"]
    )
    for sio in (host_sio, tagasagot_sio, outsider_sio):
        sio.get_received()

    turn_id = _turn_by_assign(client, s.host, s.match_a, s.words_b0[:3])
    _start_turn(client, s.host, s.match_a)
    for sio in (host_sio, tagasagot_sio, outsider_sio):
        sio.get_received()

    tagasagot_sio.emit("join_turn", turn_id)
    assert len(_named(tagasagot_sio.get_received(), "turn_state")) == 1

    host_sio.emit("join_turn", turn_id)
    assert len(_named(host_sio.get_received(), "turn_state")) == 1

    outsider_sio.emit("join_turn", turn_id)
    outsider_events = outsider_sio.get_received()
    assert any(e["name"] == "error" for e in outsider_events)
    assert not _named(outsider_events, "turn_state")

    assert _host_post(client, s.host, "/api/turns/{}/correct".format(turn_id)).status_code == 200
    host_events = host_sio.get_received()
    assert len(_named(host_events, "word_correct")) >= 1

    host_sio.disconnect()
    tagasagot_sio.disconnect()
    outsider_sio.disconnect()


# ---------------------------------------------------------------------------
# 9. Team connection lifecycle events
# ---------------------------------------------------------------------------


def test_connection_requested_reaches_host_and_team(app, client):
    game_id, host = _create_game(client)
    host_sio = _socket(app, host)
    team = _create_team(client, game_id, "Team A")
    team_sio = _socket(
        app, _connect(client, team["leader"])["session_token"]
    )
    host_sio.get_received()
    team_sio.get_received()

    response = client.post(
        "/api/games/{}/connection-request".format(game_id),
        json={"connection_token": team["leader"]["connection_token"]},
    )
    assert response.status_code == 200

    host_events = _named(host_sio.get_received(), "connection_requested")
    assert len(host_events) == 1
    payload = host_events[0]["args"][0]
    assert payload["team_id"] == team["team_id"]
    assert payload["game_id"] == game_id
    assert payload["connection_status"] == "CONNECTION_REQUESTED"

    team_events = _named(team_sio.get_received(), "connection_requested")
    assert len(team_events) >= 1
    assert team_events[0]["args"][0]["team_id"] == team["team_id"]

    host_sio.disconnect()
    team_sio.disconnect()


def test_connection_approved_reaches_team_and_host(app, client):
    game_id, host = _create_game(client)
    host_sio = _socket(app, host)
    team_a = _create_team(client, game_id, "Team A")
    team_b = _create_team(client, game_id, "Team B")
    team_a_sio = _socket(
        app, _connect(client, team_a["leader"], device_id="dev-a")["session_token"]
    )
    team_b_sio = _socket(
        app, _connect(client, team_b["leader"], device_id="dev-b")["session_token"]
    )
    for sio in (host_sio, team_a_sio, team_b_sio):
        sio.get_received()

    client.post(
        "/api/games/{}/connection-request".format(game_id),
        json={"connection_token": team_a["leader"]["connection_token"]},
    )
    for sio in (host_sio, team_a_sio, team_b_sio):
        sio.get_received()

    approved = client.post(
        "/api/games/{}/connection-requests/{}/approve".format(
            game_id, team_a["team_id"]
        ),
        headers={HOST_TOKEN_HEADER: host},
    )
    assert approved.status_code == 200
    assert approved.get_json()["data"]["connection_status"] == "CONNECTED"

    # The approving team and the host both receive the event.
    assert len(_named(team_a_sio.get_received(), "connection_approved")) >= 1
    assert len(_named(host_sio.get_received(), "connection_approved")) == 1

    # game_room is an intentional shared broadcast channel, so other teams may
    # also receive the event; it must never carry secret gameplay data.
    for payload in _named(team_b_sio.get_received(), "connection_approved"):
        assert "words" not in payload["args"][0]
        assert "current_word_text" not in payload["args"][0]

    host_sio.disconnect()
    team_a_sio.disconnect()
    team_b_sio.disconnect()


def test_connection_declined_reaches_team(app, client):
    game_id, host = _create_game(client)
    team = _create_team(client, game_id, "Team A")
    team_sio = _socket(
        app, _connect(client, team["leader"])["session_token"]
    )
    team_sio.get_received()

    client.post(
        "/api/games/{}/connection-request".format(game_id),
        json={"connection_token": team["leader"]["connection_token"]},
    )
    team_sio.get_received()
    response = client.post(
        "/api/games/{}/connection-requests/{}/decline".format(
            game_id, team["team_id"]
        ),
        headers={HOST_TOKEN_HEADER: host},
    )
    assert response.status_code == 200
    declined = _named(team_sio.get_received(), "connection_declined")
    assert len(declined) >= 1
    assert declined[0]["args"][0]["connection_status"] == "DECLINED"
    team_sio.disconnect()


def test_member_joined_and_left_reach_host_and_team(app, client):
    game_id, host = _create_game(client)
    host_sio = _socket(app, host)
    team = _create_team(client, game_id, "Team A")
    team_sio = _socket(
        app, _connect(client, team["leader"])["session_token"]
    )
    host_sio.get_received()
    team_sio.get_received()

    member = _add_member(client, team["team_id"], "Maria")
    for sio in (host_sio, team_sio):
        joined = _named(sio.get_received(), "member_joined")
        assert len(joined) >= 1
        assert joined[0]["args"][0]["member"]["member_id"] == member["member_id"]

    removed = client.delete(
        "/api/members/{}".format(member["member_id"]),
        headers={HOST_TOKEN_HEADER: host},
    )
    assert removed.status_code == 200
    for sio in (host_sio, team_sio):
        left = _named(sio.get_received(), "member_left")
        assert len(left) >= 1
        assert left[0]["args"][0]["member_id"] == member["member_id"]

    host_sio.disconnect()
    team_sio.disconnect()


# ---------------------------------------------------------------------------
# 10. Score + penalty events reach the team socket
# ---------------------------------------------------------------------------


def test_score_and_penalty_reach_team_socket(app, client):
    s = _setup(client)
    host_sio = _socket(app, s.host)
    tagasagot_sio = _socket(
        app, _connect(client, s.member_a, device_id="dev-2")["session_token"]
    )
    for sio in (host_sio, tagasagot_sio):
        sio.get_received()

    turn_a = _turn_by_assign(client, s.host, s.match_a, s.words_b0[:4])
    _start_turn(client, s.host, s.match_a)
    for sio in (host_sio, tagasagot_sio):
        sio.get_received()

    assert _host_post(
        client, s.host, "/api/turns/{}/correct".format(turn_a)
    ).status_code == 200
    correct = _named(tagasagot_sio.get_received(), "word_correct")
    assert len(correct) >= 1
    assert correct[0]["args"][0]["correct_words"] == 1
    assert correct[0]["args"][0]["turn_id"] == turn_a

    assert _host_post(
        client,
        s.host,
        "/api/turns/{}/time/add".format(turn_a),
        json={"seconds": 10},
    ).status_code == 200
    team_events = tagasagot_sio.get_received()
    assert len(_named(team_events, "time_added")) >= 1
    assert len(_named(team_events, "penalty_applied")) >= 1

    host_sio.disconnect()
    tagasagot_sio.disconnect()


# ---------------------------------------------------------------------------
# 11. settings_updated broadcasts to host and teams (game_room)
# ---------------------------------------------------------------------------


def test_settings_updated_reaches_host_and_teams(app, client):
    game_id, host = _create_game(client)
    host_sio = _socket(app, host)
    team = _create_team(client, game_id, "Team A")
    team_sio = _socket(
        app, _connect(client, team["leader"], device_id="dev-team")["session_token"]
    )
    for sio in (host_sio, team_sio):
        sio.get_received()

    response = client.put(
        "/api/games/{}/settings".format(game_id),
        json={"penalty_seconds": 10},
        headers={HOST_TOKEN_HEADER: host},
    )
    assert response.status_code == 200

    host_events = _named(host_sio.get_received(), "settings_updated")
    assert len(host_events) == 1
    payload = host_events[0]["args"][0]
    assert payload["penalty_seconds"] == 10
    assert payload["game_id"] == game_id
    assert "host_session_token" not in payload

    team_events = _named(team_sio.get_received(), "settings_updated")
    assert len(team_events) >= 1
    assert team_events[0]["args"][0]["penalty_seconds"] == 10

    host_sio.disconnect()
    team_sio.disconnect()

