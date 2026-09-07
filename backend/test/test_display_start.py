import time

import pytest
from flask_socketio.test_client import SocketIOTestClient

from app import create_app
from app.extensions import db, socketio
from app.models import Game, Round
from app.services import realtime
from app.utils.time import utcnow
from test_turns import (
    HOST_TOKEN_HEADER,
    MANGHUHULA,
    SESSION_TOKEN_HEADER,
    TAGASAGOT,
    _add_member,
    _assign_roles,
    _connect,
    _create_category,
    _create_game,
    _create_matches,
    _create_team,
    _submit_words,
)

COUNTDOWN_SECONDS = 3
TARGET_WORDS = 5


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


def _big_setup(client, manghuhula_is_member=False):
    """30 enabled words (3 categories x 2 teams x 5), timer set on every round."""
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
        _create_category(client, game_id, host, "Cat{}".format(i))
        for i in range(3)
    ]
    words_a = []
    words_b = []
    for cat_id in cats:
        words_a += _submit_words(
            client, game_id, team_a["team_id"], cat_id,
            ["a{}{}".format(cats.index(cat_id), n) for n in range(1, 6)],
            sess_a,
        )
        words_b += _submit_words(
            client, game_id, team_b["team_id"], cat_id,
            ["b{}{}".format(cats.index(cat_id), n) for n in range(1, 6)],
            sess_b,
        )

    if manghuhula_is_member:
        _assign_roles(
            client, team_a,
            [(leader_a["member_id"], TAGASAGOT),
             (member_a["member_id"], MANGHUHULA)], host,
        )
        _assign_roles(
            client, team_b,
            [(leader_b["member_id"], TAGASAGOT),
             (member_b["member_id"], MANGHUHULA)], host,
        )
    else:
        _assign_roles(
            client, team_a,
            [(leader_a["member_id"], MANGHUHULA),
             (member_a["member_id"], TAGASAGOT)], host,
        )
        _assign_roles(
            client, team_b,
            [(leader_b["member_id"], MANGHUHULA),
             (member_b["member_id"], TAGASAGOT)], host,
        )

    for round_number in (1, 2):
        assert client.post(
            "/api/games/{}/rounds".format(game_id),
            json={"round_number": round_number, "timer_seconds": 60},
            headers={HOST_TOKEN_HEADER: host},
        ).status_code == 201
    assert client.post(
        "/api/games/{}/rounds/1/categories".format(game_id),
        json={"category_ids": cats},
        headers={HOST_TOKEN_HEADER: host},
    ).status_code == 200
    matches_resp = _create_matches(
        client, game_id, host, 1,
        [{"team_id": team_a["team_id"],
          "opponent_team_id": team_b["team_id"]}],
    )
    assert matches_resp.status_code == 201
    match_a = next(
        m for m in matches_resp.get_json()["data"]["matches"]
        if m["round_number"] == 1
    )

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
        words_a=words_a,
        words_b=words_b,
        match_a=match_a,
    )


def _ready(client, s, match=None):
    body = {}
    if match is not None:
        body["match_id"] = match["match_id"]
    return client.post(
        "/api/games/{}/display/ready".format(s.game_id),
        json=body,
        headers={HOST_TOKEN_HEADER: s.host},
    )


def _go(client, s, match):
    return client.post(
        "/api/games/{}/display/go".format(s.game_id),
        json={"match_id": match["match_id"]},
        headers={HOST_TOKEN_HEADER: s.host},
    )


def _state(client, s, session_token=None, use_host=True):
    headers = {}
    if use_host:
        headers[HOST_TOKEN_HEADER] = s.host
    if session_token is not None:
        headers[SESSION_TOKEN_HEADER] = session_token
    return client.get(
        "/api/games/{}/display/state".format(s.game_id), headers=headers
    )


def _connect_member(client, member, device_id):
    response = client.post(
        "/api/devices/connect",
        json={
            "connection_token": member["connection_token"],
            "device_id": device_id,
        },
    )
    assert response.status_code == 201
    return response.get_json()["data"]["session_token"]


def _to_sockets(app, client, s):
    """Connect live phone sockets like production (returns socket, token)."""
    result = {}
    for name, member, device_id in (
        ("leader_a", s.leader_a, "dev-lead-a"),
        ("member_a", s.member_a, "dev-2"),
        ("leader_b", s.leader_b, "dev-3"),
        ("member_b", s.member_b, "dev-4"),
    ):
        token = _connect_member(client, member, device_id)
        sio = _socket(app, token)
        assert sio.is_connected(), "socket {} did not connect".format(name)
        sio.get_received()
        result[name] = (sio, token)
    return result


def _display_status(app, game_id):
    with app.app_context():
        return db.session.get(Game, game_id).display_status


def _turn_id_for(app, game_id):
    from app.models import Turn

    with app.app_context():
        game = db.session.get(Game, game_id)
        if game.display_go_match_id is None:
            return None
        return (
            Turn.query.filter_by(
                match_id=game.display_go_match_id, status=Turn.STATUS_ACTIVE
            ).first().id
        )


def _to_sockets_single(app, client, member, device_id):
    token = _connect_member(client, member, device_id)
    sio = _socket(app, token)
    assert sio.is_connected()
    sio.get_received()
    return sio, token


def _socket(app, token, device_id=None):
    query_string = "device_id={}".format(device_id) if device_id else None
    return SocketIOTestClient(
        app, socketio, auth={"token": token}, query_string=query_string
    )


def _named(events, name):
    return [e for e in events if e["name"] == name]


# ---------------------------------------------------------------------------
# Auth + gates
# ---------------------------------------------------------------------------


def test_display_ready_requires_host(client):
    s = _big_setup(client)
    response = client.post(
        "/api/games/{}/display/ready".format(s.game_id),
        json={"match_id": s.match_a["match_id"]},
    )
    assert response.status_code == 401


def test_display_go_requires_host(client):
    s = _big_setup(client)
    response = client.post(
        "/api/games/{}/display/go".format(s.game_id),
        json={"match_id": s.match_a["match_id"]},
    )
    assert response.status_code == 401


def test_display_state_requires_known_device(client):
    s = _big_setup(client)
    assert _state(client, s, use_host=False).status_code == 401
    assert (
        _state(client, s, session_token="not-a-token", use_host=False)
        .status_code
        == 401
    )


def test_ready_blocks_missing_match_and_words(client):
    s = _big_setup(client)
    # 30 words IS enough here; shrink by disabling to test the pool gate.
    response = _ready(client, s)  # no match_id
    assert response.status_code == 400
    issues = response.get_json()["error"]["issues"]
    assert any("Select a match" in issue for issue in issues)


def test_ready_blocks_small_word_pool(client):
    s = _big_setup(client)
    with client.application.app_context():
        from app.models import Word

        Word.query.update({Word.status: Word.STATUS_DISABLED})
        db.session.commit()
    response = _ready(client, s, s.match_a)
    assert response.status_code == 400
    issues = response.get_json()["error"]["issues"]
    assert any("15 enabled words" in issue for issue in issues)


def test_ready_uses_configured_minimum_word_pool(client):
    s = _big_setup(client)
    # Lower the start gate to 5 words, then leave only 4 enabled.
    response = client.put(
        "/api/games/{}/settings".format(s.game_id),
        json={"min_words_to_start": 5},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    assert (
        response.get_json()["data"]["min_words_to_start"] == 5
    )
    with client.application.app_context():
        from app.models import Word

        pool = Word.query.filter_by(game_id=s.game_id).all()
        for index, word in enumerate(pool):
            if index >= 4:
                word.status = Word.STATUS_DISABLED
        db.session.commit()
    response = _ready(client, s, s.match_a)
    assert response.status_code == 400
    issues = response.get_json()["error"]["issues"]
    assert any("5 enabled words" in issue for issue in issues)

    # Enable 5 words spread across all 3 categories (2/2/1): the 5-word floor is
    # met, so the pool gate clears. _big_setup's words are ordered 10 per
    # category, so index // 10 picks the category.
    with client.application.app_context():
        from app.models import Word

        enabled = {0, 1, 10, 11, 20}
        for index, word in enumerate(Word.query.filter_by(game_id=s.game_id).all()):
            word.status = (
                Word.STATUS_AVAILABLE if index in enabled else Word.STATUS_DISABLED
            )
        db.session.commit()
    response = _ready(client, s, s.match_a)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["status"] == Game.DISPLAY_ARMED


def test_ready_blocks_zero_timer(client):
    s = _big_setup(client)
    with client.application.app_context():
        round_obj = Round.query.filter_by(
            game_id=s.game_id, round_number=1
        ).first()
        round_obj.timer_seconds = 0
        db.session.commit()
    response = _ready(client, s, s.match_a)
    assert response.status_code == 400
    issues = response.get_json()["error"]["issues"]
    assert any("invalid timer" in issue for issue in issues)


# ---------------------------------------------------------------------------
# Two-stage lifecycle
# ---------------------------------------------------------------------------


def test_ready_arms_then_go_counts_down_then_turn_runs(client, app):
    s = _big_setup(client)
    _to_sockets(app, client, s)  # live phones: leader_a is the Manghuhula
    response = _ready(client, s, s.match_a)
    assert response.status_code == 200
    armed = response.get_json()["data"]
    assert armed["status"] == Game.DISPLAY_ARMED
    assert armed["match_id"] == s.match_a["match_id"]
    assert armed["display_target"] == "manghuhula"
    assert _display_status(app, s.game_id) == Game.DISPLAY_ARMED

    go = _go(client, s, s.match_a)
    assert go.status_code == 200
    countdown = go.get_json()["data"]
    assert countdown["status"] == Game.DISPLAY_COUNTDOWN
    assert countdown["countdown_seconds"] == COUNTDOWN_SECONDS
    assert countdown["go_at"] is not None
    assert _display_status(app, s.game_id) == Game.DISPLAY_COUNTDOWN

    # Before the deadline the state read reports COUNTDOWN with remaining.
    state = _state(client, s).get_json()["data"]
    assert state["status"] == Game.DISPLAY_COUNTDOWN
    assert state["match_id"] == s.match_a["match_id"]
    assert state["remaining"] > 0

    time.sleep(COUNTDOWN_SECONDS + 1.2)
    state = _state(client, s).get_json()["data"]
    assert state["status"] == Game.DISPLAY_RUNNING
    assert state["turn_id"] is not None

    # The display flow assigned exactly MAX_WORDS_PER_TURN words.
    turn = client.get(
        "/api/turns/{}".format(state["turn_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]
    assert len(turn["words"]) == TARGET_WORDS


def test_go_revalidates_and_reverts_to_idle(client, app):
    s = _big_setup(client)
    assert _ready(client, s, s.match_a).status_code == 200
    with app.app_context():
        round_obj = Round.query.filter_by(
            game_id=s.game_id, round_number=1
        ).first()
        round_obj.status = Round.STATUS_COMPLETED
        db.session.commit()

    response = _go(client, s, s.match_a)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "DISPLAY_NOT_READY"
    assert any(
        "already complete" in issue
        for issue in response.get_json()["error"]["issues"]
    )
    assert _display_status(app, s.game_id) == Game.DISPLAY_IDLE


def test_go_without_arm_rejected(client):
    s = _big_setup(client)
    response = _go(client, s, s.match_a)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "DISPLAY_NOT_ARMED"


def test_finish_turn_returns_display_to_idle(client, app):
    s = _big_setup(client)
    assert _ready(client, s, s.match_a).status_code == 200
    assert _go(client, s, s.match_a).status_code == 200
    time.sleep(COUNTDOWN_SECONDS + 1.2)
    state = _state(client, s).get_json()["data"]
    assert state["status"] == Game.DISPLAY_RUNNING
    turn_id = state["turn_id"]

    for _ in range(3):
        assert client.post(
            "/api/turns/{}/correct".format(turn_id),
            headers={HOST_TOKEN_HEADER: s.host},
        ).status_code == 200
    state = _state(client, s).get_json()["data"]
    assert state["status"] == Game.DISPLAY_IDLE


def test_state_member_auth_and_target_flags(app, client):
    s = _big_setup(client)
    sockets = _to_sockets(app, client, s)
    _, token_manghuhula = sockets["leader_a"]
    _, token_opponent = sockets["leader_b"]
    assert _ready(client, s, s.match_a).status_code == 200
    assert _go(client, s, s.match_a).status_code == 200
    time.sleep(COUNTDOWN_SECONDS + 1.2)
    assert _state(client, s).get_json()["data"]["status"] == (
        Game.DISPLAY_RUNNING
    )

    manghuhula = _state(
        client, s, session_token=token_manghuhula, use_host=False
    ).get_json()["data"]
    assert manghuhula["status"] == Game.DISPLAY_RUNNING
    assert manghuhula["is_target"] is True
    assert manghuhula["target_kind"] == "manghuhula"
    assert manghuhula["team_id"] == s.team_a["team_id"]

    # Team B's connected leader is not on the playing team.
    opponent = _state(
        client, s, session_token=token_opponent, use_host=False
    ).get_json()["data"]
    assert opponent["is_target"] is False


# ---------------------------------------------------------------------------
# Secret targeting + recovery
# ---------------------------------------------------------------------------


def test_secret_result_reaches_resolved_target_only(app, client):
    s = _big_setup(client)
    sockets = _to_sockets(app, client, s)
    target_sio, _ = sockets["leader_a"]
    tagasagot_sio, _ = sockets["member_a"]
    opponent_sio, _ = sockets["leader_b"]
    host_sio = _socket(app, s.host)
    host_sio.get_received()

    assert _ready(client, s, s.match_a).status_code == 200
    assert _go(client, s, s.match_a).status_code == 200
    time.sleep(COUNTDOWN_SECONDS + 1.2)
    assert _state(client, s).get_json()["data"]["status"] == (
        Game.DISPLAY_RUNNING
    )

    def secret_events(sio):
        return [
            e["args"][0]
            for e in _named(sio.get_received(), "turn_started")
            if "words" in e["args"][0]
        ]

    secrets = []
    deadline = time.time() + 5.0
    while time.time() < deadline:
        secrets = secret_events(target_sio)
        if secrets:
            break
        time.sleep(0.2)
    assert secrets, "target must receive the secret words"

    for sio in (host_sio, tagasagot_sio, opponent_sio):
        assert not secret_events(sio), "secret must not be broadcast"

    # The secret is scoped to the turn actually started via display.
    texts = secrets[0]["words"]
    assert len(texts) == TARGET_WORDS
    assert all(w["word_text"] for w in texts)

    host_sio.disconnect()
    target_sio.disconnect()
    tagasagot_sio.disconnect()
    opponent_sio.disconnect()


def test_target_falls_back_to_connected_leader(app, client):
    s = _big_setup(client, manghuhula_is_member=True)
    # Only the leader phone connects — the disconnected Manghuhula (member)
    # must not resolve; the connected leader is the fallback target.
    _to_sockets_single(app, client, s.leader_a, "dev-lead-a")
    response = _ready(client, s, s.match_a)
    assert response.status_code == 200
    assert response.get_json()["data"]["display_target"] == "leader"


def test_leader_fallback_can_recover_secret_turn(app, client):
    s = _big_setup(client, manghuhula_is_member=True)
    leader_sio, leader_token = _to_sockets_single(
        app, client, s.leader_a, "dev-lead-a"
    )
    assert _ready(client, s, s.match_a).status_code == 200
    assert _go(client, s, s.match_a).status_code == 200
    time.sleep(COUNTDOWN_SECONDS + 1.2)
    state = _state(client, s).get_json()["data"]
    assert state["status"] == Game.DISPLAY_RUNNING
    turn_id = state["turn_id"]

    # The target flag is per-device: query as the fallback leader phone.
    fallback_state = _state(
        client, s, session_token=leader_token, use_host=False
    ).get_json()["data"]
    assert fallback_state["target_kind"] == "leader"
    assert fallback_state["is_target"] is True

    fallback = client.get(
        "/api/turns/{}".format(turn_id),
        headers={SESSION_TOKEN_HEADER: leader_token},
    ).get_json()["data"]
    assert len(fallback["words"]) == TARGET_WORDS

    # The opponent team's phone cannot access this turn at all (401), so
    # cross-team secret leakage is impossible.
    opponent = client.get(
        "/api/turns/{}".format(turn_id),
        headers={SESSION_TOKEN_HEADER: s.sess_b},
    )
    assert opponent.status_code == 401