import pytest

from app import create_app
from app.extensions import db
from app.models import Game, GameEvent
from app.utils.time import utcnow

HOST_TOKEN_HEADER = "X-Host-Token"
SESSION_TOKEN_HEADER = "X-Session-Token"
MANGHUHULA = "MANGHUHULA"
TAGASAGOT = "TAGASAGOT"


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def _create_game(client):
    r = client.post("/api/games")
    assert r.status_code == 201
    data = r.get_json()["data"]
    return data["game_id"], data["host_session_token"]


def _create_team(client, game_id, name, username):
    r = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"team_name": name, "username": username},
    )
    assert r.status_code == 201
    return r.get_json()["data"]


def _add_member(client, team_id, username):
    r = client.post(
        "/api/teams/{}/members".format(team_id), json={"username": username}
    )
    assert r.status_code == 201
    return r.get_json()["data"]


def _connect(client, connection_token):
    r = client.post(
        "/api/devices/connect",
        json={"connection_token": connection_token, "device_id": "dev"},
    )
    assert r.status_code == 201
    return r.get_json()["data"]["session_token"]


def _create_category(client, game_id, host, name):
    r = client.post(
        "/api/games/{}/categories".format(game_id),
        json={"name": name},
        headers={HOST_TOKEN_HEADER: host},
    )
    assert r.status_code == 201
    return r.get_json()["data"]["category_id"]


def _submit(client, game_id, team_id, cat, words, sess):
    ids = []
    for w in words:
        r = client.post(
            "/api/games/{}/words".format(game_id),
            json={"team_id": team_id, "category_id": cat, "word_text": w},
            headers={SESSION_TOKEN_HEADER: sess},
        )
        assert r.status_code == 201
        ids.append(r.get_json()["data"]["word_id"])
    return ids


def _roles(client, team, roles, host):
    body = {
        "roles": [
            {"member_id": m, "gameplay_role": role} for m, role in roles
        ]
    }
    return client.post(
        "/api/teams/{}/roles".format(team["team_id"]),
        json=body,
        headers={HOST_TOKEN_HEADER: host},
    )


class S:
    pass


def _full(client):
    s = S()
    s.game_id, s.host = _create_game(client)
    s.team_a = _create_team(client, s.game_id, "Team A", "Alan")
    s.team_b = _create_team(client, s.game_id, "Team B", "Bella")
    s.sess_a = _connect(client, s.team_a["leader"]["connection_token"])
    s.sess_b = _connect(client, s.team_b["leader"]["connection_token"])
    s.member_a = _add_member(client, s.team_a["team_id"], "Maria")
    s.member_b = _add_member(client, s.team_b["team_id"], "Kris")
    s.cat = _create_category(client, s.game_id, s.host, "Food")
    s.words_a = _submit(
        client, s.game_id, s.team_a["team_id"], s.cat,
        ["apple", "banana", "candy", "date"], s.sess_a,
    )
    s.words_b = _submit(
        client, s.game_id, s.team_b["team_id"], s.cat,
        ["egg", "fig", "grape", "ham"], s.sess_b,
    )
    assert _roles(
        client, s.team_a,
        [(s.team_a["leader"]["member_id"], MANGHUHULA),
         (s.member_a["member_id"], TAGASAGOT)],
        s.host,
    ).status_code == 200
    assert _roles(
        client, s.team_b,
        [(s.team_b["leader"]["member_id"], MANGHUHULA),
         (s.member_b["member_id"], TAGASAGOT)],
        s.host,
    ).status_code == 200
    assert client.post(
        "/api/games/{}/rounds".format(s.game_id),
        json={"round_number": 1},
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 201
    assert client.post(
        "/api/games/{}/rounds".format(s.game_id),
        json={"round_number": 2},
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 201
    assert client.post(
        "/api/games/{}/rounds/1/categories".format(s.game_id),
        json={"category_ids": [s.cat]},
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 200
    assert client.post(
        "/api/games/{}/matches".format(s.game_id),
        json={
            "round_number": 1,
            "matches": [
                {"team_id": s.team_a["team_id"],
                 "opponent_team_id": s.team_b["team_id"]}
            ],
        },
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 201
    matches = client.get(
        "/api/games/{}/matches".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]["matches"]
    s.match_a = next(m for m in matches if m["round_number"] == 1)
    return s


def _play_turn(client, s, match, word_ids, correct=3):
    turn = client.post(
        "/api/matches/{}/turns".format(match["match_id"]),
        json={"word_ids": word_ids},
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(match["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    for _ in range(correct):
        client.post(
            "/api/turns/{}/correct".format(turn["turn_id"]),
            headers={HOST_TOKEN_HEADER: s.host},
        )
    return turn


def _end_game(client, s):
    return client.post(
        "/api/games/{}/end".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def test_game_history_endpoint(client):
    s = _full(client)
    _play_turn(client, s, s.match_a, word_ids=s.words_b[:3])
    assert client.post(
        "/api/games/{}/start".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 200
    _end_game(client, s)

    response = client.get(
        "/api/games/{}/history".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["game_id"] == s.game_id
    assert len(data["teams"]) == 2
    assert data["winner"]["team_id"] == s.team_a["team_id"]
    assert any(t["event_type"] == "TURN_STARTED" for t in data["events"])
    assert any(t["event_type"] == "WORD_CORRECT" for t in data["events"])
    assert any(t["event_type"] == "TURN_COMPLETED" for t in data["events"])
    assert any(t["event_type"] == "ROLE_CHANGED" for t in data["events"])
    assert data["words_used"]


def test_game_history_requires_host(client):
    s = _full(client)
    assert client.get(
        "/api/games/{}/history".format(s.game_id)
    ).status_code == 401


def test_history_list_by_host_token(client):
    s = _full(client)
    _play_turn(client, s, s.match_a, word_ids=s.words_b[:3])
    assert client.post(
        "/api/games/{}/start".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 200
    _end_game(client, s)

    response = client.get(
        "/api/games/history", headers={HOST_TOKEN_HEADER: s.host}
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert len(data["games"]) == 1
    assert data["games"][0]["game_id"] == s.game_id


def test_history_list_requires_token(client):
    assert client.get("/api/games/history").status_code == 401


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


def test_leaderboard_orders_by_points(client):
    s = _full(client)
    _play_turn(client, s, s.match_a, word_ids=s.words_b[:3])
    _end_game(client, s)

    response = client.get(
        "/api/games/{}/leaderboard".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    board = response.get_json()["data"]["leaderboard"]
    assert board[0]["team_id"] == s.team_a["team_id"]
    assert board[0]["points"] == 3
    assert board[0]["correct_words"] == 3
    assert board[0]["rank"] == 1


def test_leaderboard_tie_breaks_by_first_correct(app, client):
    from datetime import timedelta

    from app.models import (
        Match,
        Round,
        Score,
        Turn,
        TurnWord,
    )

    s = _full(client)
    with app.app_context():
        round_obj = Round.query.filter_by(
            game_id=s.game_id, round_number=1
        ).first()
        match_a = Match.query.filter_by(game_id=s.game_id).first()
        now = utcnow()
        match_b = Match(
            game_id=s.game_id,
            round_id=round_obj.id,
            team_id=s.team_b["team_id"],
            opponent_team_id=s.team_a["team_id"],
            match_order=2,
            status=Match.STATUS_COMPLETED,
            winner_team_id=s.team_b["team_id"],
        )
        db.session.add(match_b)
        db.session.flush()
        db.session.add_all(
            [
                Score(
                    game_id=s.game_id,
                    team_id=s.team_a["team_id"],
                    round_id=round_obj.id,
                    match_id=match_a.id,
                    points=3,
                    correct_words=3,
                ),
                Score(
                    game_id=s.game_id,
                    team_id=s.team_b["team_id"],
                    round_id=round_obj.id,
                    match_id=match_b.id,
                    points=3,
                    correct_words=3,
                ),
            ]
        )
        turn_a = Turn(
            match_id=match_a.id,
            team_id=s.team_a["team_id"],
            round_id=round_obj.id,
            turn_order=1,
            status=Turn.STATUS_COMPLETED,
        )
        turn_b = Turn(
            match_id=match_b.id,
            team_id=s.team_b["team_id"],
            round_id=round_obj.id,
            turn_order=1,
            status=Turn.STATUS_COMPLETED,
        )
        db.session.add_all([turn_a, turn_b])
        db.session.flush()
        db.session.add_all(
            [
                TurnWord(
                    turn_id=turn_a.id,
                    word_id=s.words_b[0],
                    sequence=1,
                    result=TurnWord.RESULT_CORRECT,
                    used_at=now,
                ),
                TurnWord(
                    turn_id=turn_b.id,
                    word_id=s.words_b[0],
                    sequence=1,
                    result=TurnWord.RESULT_CORRECT,
                    used_at=now + timedelta(seconds=5),
                ),
            ]
        )
        db.session.commit()

    response = client.get(
        "/api/games/{}/leaderboard".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    board = response.get_json()["data"]["leaderboard"]
    # Equal points and correct words -> the earlier first correct word wins.
    assert board[0]["team_id"] == s.team_a["team_id"]
    assert board[1]["team_id"] == s.team_b["team_id"]
    assert board[0]["first_correct_at"] is not None


def test_leaderboard_requires_auth(client):
    s = _full(client)
    assert client.get(
        "/api/games/{}/leaderboard".format(s.game_id)
    ).status_code == 401
    assert client.get(
        "/api/games/{}/leaderboard".format(s.game_id),
        headers={HOST_TOKEN_HEADER: "bogus-token"},
    ).status_code == 401


def test_leaderboard_allows_any_player_session(client):
    s = _full(client)
    _play_turn(client, s, s.match_a, word_ids=s.words_b[:3])

    response = client.get(
        "/api/games/{}/leaderboard".format(s.game_id),
        headers={SESSION_TOKEN_HEADER: s.sess_b},
    )
    assert response.status_code == 200
    board = response.get_json()["data"]["leaderboard"]
    assert board[0]["team_id"] == s.team_a["team_id"]
    assert board[0]["points"] == 3
    assert board[0]["rank"] == 1
    assert all("team_code" in row for row in board)


def test_leaderboard_rejects_session_from_other_game(client):
    s = _full(client)
    other_game_id, _ = _create_game(client)
    other_team = _create_team(client, other_game_id, "Team X", "Xyla")
    other_sess = _connect(client, other_team["leader"]["connection_token"])

    assert client.get(
        "/api/games/{}/leaderboard".format(s.game_id),
        headers={SESSION_TOKEN_HEADER: other_sess},
    ).status_code == 401


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def test_statistics_summary(client):
    s = _full(client)
    _play_turn(client, s, s.match_a, word_ids=s.words_b[:3])
    assert client.post(
        "/api/games/{}/start".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 200
    _end_game(client, s)

    response = client.get(
        "/api/games/{}/statistics".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["game_id"] == s.game_id
    assert data["total_teams"] == 2
    assert data["total_words"] == 8
    assert data["total_correct_answers"] == 3
    assert data["winning_team"]["team_id"] == s.team_a["team_id"]
    assert data["fastest_team"]["team_id"] == s.team_a["team_id"]
    assert len(data["team_scores"]) == 2


def test_statistics_requires_host(client):
    s = _full(client)
    assert client.get(
        "/api/games/{}/statistics".format(s.game_id)
    ).status_code == 401


# ---------------------------------------------------------------------------
# Read-only completed games
# ---------------------------------------------------------------------------


def test_completed_game_is_read_only(app, client):
    s = _full(client)
    _play_turn(client, s, s.match_a, word_ids=s.words_b[:3])
    assert client.post(
        "/api/games/{}/start".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 200
    _end_game(client, s)

    with app.app_context():
        game = db.session.get(Game, s.game_id)
        assert game.status == Game.STATUS_GAME_COMPLETE

    response = client.post(
        "/api/games/{}/start".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------


def test_audit_events_recorded(app, client):
    s = _full(client)
    _play_turn(client, s, s.match_a, word_ids=s.words_b[:3])

    with app.app_context():
        types = [
            e.event_type
            for e in db.session.query(GameEvent)
            .filter_by(game_id=s.game_id)
            .order_by(GameEvent.id)
        ]
        assert "ROLE_CHANGED" in types
        assert "ROUND_STARTED" in types
        assert "MATCH_STARTED" in types
        assert "TURN_STARTED" in types
        assert "WORD_CORRECT" in types
        assert "TURN_COMPLETED" in types
