"""Tests for game-state save/load & resume (Part 4).

The database is the source of truth. These tests verify:
  * manual save persists/confirms state without creating a duplicate game
  * resume/load restores round, teams, scoreboard, timer and penalties from the
    database (server-computed timer, never a browser value)
  * host authorization is enforced on both operations
  * invalid state transitions are rejected by the backend
"""

import pytest

from app import create_app
from app.extensions import db
from app.models import Game, GameEvent, TeamMember, Turn
from app.services import game_service

HOST_TOKEN_HEADER = "X-Host-Token"
SESSION_TOKEN_HEADER = "X-Session-Token"
MANGHUHULA = TeamMember.GAMEPLAY_ROLE_MANGHUHULA
TAGASAGOT = TeamMember.GAMEPLAY_ROLE_TAGASAGOT


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
    response = client.post("/api/games")
    assert response.status_code == 201
    data = response.get_json()["data"]
    return data["game_id"], data["host_session_token"]


def _create_team(client, game_id, name):
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"team_name": name, "username": name.split()[-1]},
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _add_member(client, team_id, username):
    response = client.post(
        "/api/teams/{}/members".format(team_id), json={"username": username}
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _connect(client, member, device_id="dev"):
    response = client.post(
        "/api/devices/connect",
        json={"connection_token": member["connection_token"], "device_id": device_id},
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _create_category(client, game_id, host, name):
    response = client.post(
        "/api/games/{}/categories".format(game_id),
        json={"name": name},
        headers={HOST_TOKEN_HEADER: host},
    )
    assert response.status_code == 201
    return response.get_json()["data"]["category_id"]


def _submit_words(client, game_id, team_id, category_id, words, session_token):
    ids = []
    for word in words:
        response = client.post(
            "/api/games/{}/words".format(game_id),
            json={"team_id": team_id, "category_id": category_id, "word_text": word},
            headers={SESSION_TOKEN_HEADER: session_token},
        )
        assert response.status_code == 201
        ids.append(response.get_json()["data"]["word_id"])
    return ids


def _assign_roles(client, team, roles, host):
    response = client.post(
        "/api/teams/{}/roles".format(team["team_id"]),
        json={"roles": [{"member_id": m, "gameplay_role": r} for m, r in roles]},
        headers={HOST_TOKEN_HEADER: host},
    )
    assert response.status_code == 200


def _setup(client, assign_roles=True):
    """Build a game that is ready to start matches/turns."""
    game_id, host = _create_game(client)
    team_a = _create_team(client, game_id, "Team A")
    team_b = _create_team(client, game_id, "Team B")
    leader_a = team_a["leader"]
    leader_b = team_b["leader"]
    sess_a = _connect(client, leader_a)["session_token"]
    sess_b = _connect(client, leader_b)["session_token"]
    member_a = _add_member(client, team_a["team_id"], "Maria")
    member_b = _add_member(client, team_b["team_id"], "Kris")

    cat_a = _create_category(client, game_id, host, "Food")
    cat_b = _create_category(client, game_id, host, "Animals")
    words_a0 = _submit_words(
        client, game_id, team_a["team_id"], cat_a,
        ["a01", "a02", "a03", "a04", "a05"], sess_a,
    )
    words_b0 = _submit_words(
        client, game_id, team_b["team_id"], cat_a,
        ["b01", "b02", "b03", "b04", "b05"], sess_b,
    )
    if assign_roles:
        _assign_roles(
            client, team_a,
            [(leader_a["member_id"], MANGHUHULA), (member_a["member_id"], TAGASAGOT)],
            host,
        )
        _assign_roles(
            client, team_b,
            [(leader_b["member_id"], MANGHUHULA), (member_b["member_id"], TAGASAGOT)],
            host,
        )
    assert client.post(
        "/api/games/{}/rounds".format(game_id),
        json={"round_number": 1},
        headers={HOST_TOKEN_HEADER: host},
    ).status_code == 201
    assert client.post(
        "/api/games/{}/rounds/1/categories".format(game_id),
        json={"category_ids": [cat_a, cat_b]},
        headers={HOST_TOKEN_HEADER: host},
    ).status_code == 200
    resp = client.post(
        "/api/games/{}/matches".format(game_id),
        json={
            "round_number": 1,
            "matches": [
                {"team_id": team_a["team_id"], "opponent_team_id": team_b["team_id"]},
                {"team_id": team_b["team_id"], "opponent_team_id": team_a["team_id"]},
            ],
        },
        headers={HOST_TOKEN_HEADER: host},
    )
    assert resp.status_code == 201
    matches = resp.get_json()["data"]["matches"]
    match_a = next(m for m in matches if m["team_id"] == team_a["team_id"])

    return {
        "game_id": game_id,
        "host": host,
        "team_a": team_a,
        "match_a": match_a,
        "words_b0": words_b0,
    }


def _start_active_turn(client, s):
    """Assign words (submitted by the opponent) to the first turn and start it."""
    assign = client.post(
        "/api/matches/{}/turns".format(s["match_a"]["match_id"]),
        json={"word_ids": s["words_b0"][:3]},
        headers={HOST_TOKEN_HEADER: s["host"]},
    )
    assert assign.status_code == 201
    start = client.post(
        "/api/matches/{}/turn/start".format(s["match_a"]["match_id"]),
        headers={HOST_TOKEN_HEADER: s["host"]},
    )
    assert start.status_code == 200
    return start


# ---------------------------------------------------------------------------
# Manual save
# ---------------------------------------------------------------------------


def test_manual_save_persists_and_no_duplicate(client, app):
    game_id, host = _create_game(client)

    with app.app_context():
        before = db.session.query(Game).count()
    response = client.post(
        "/api/games/{}/save".format(game_id),
        headers={HOST_TOKEN_HEADER: host},
    )
    assert response.status_code == 200
    with app.app_context():
        after = db.session.query(Game).count()
        assert after == before  # no duplicate game created
        assert (
            GameEvent.query.filter_by(
                game_id=game_id, event_type="GAME_SAVED"
            ).count()
            == 1
        )

    body = response.get_json()["data"]
    assert body["game_id"] == game_id


def test_manual_save_requires_host(client):
    game_id, _ = _create_game(client)
    response = client.post("/api/games/{}/save".format(game_id))
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Resume / load state
# ---------------------------------------------------------------------------


def test_resume_state_requires_host(client):
    game_id, _ = _create_game(client)
    response = client.get("/api/games/{}/state".format(game_id))
    assert response.status_code == 401


def test_resume_state_returns_game_teams_and_scoreboard(client):
    game_id, host = _create_game(client)
    team_a = _create_team(client, game_id, "Team A")
    team_b = _create_team(client, game_id, "Team B")

    response = client.get(
        "/api/games/{}/state".format(game_id),
        headers={HOST_TOKEN_HEADER: host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["game_id"] == game_id
    assert data["current_round"] is None
    names = {t["team_name"] for t in data["teams"]}
    assert names == {"Team A", "Team B"}
    team_ids = {row["team_id"] for row in data["scoreboard"]}
    assert team_ids == {team_a["team_id"], team_b["team_id"]}
    assert data["resume_turn"] is None


def test_resume_state_restores_round_team_timer_and_penalties(client, app):
    s = _setup(client)
    game_id, host = s["game_id"], s["host"]

    # Start the first turn of match A so there is live in-progress state.
    start = _start_active_turn(client, s)
    turn_id = start.get_json()["data"]["turn_id"]

    # Sanity: a penalty/revert round-trip so penalties restore too. Add +3s.
    time_add = client.post(
        "/api/turns/{}/time/add".format(turn_id),
        json={"seconds": 3},
        headers={HOST_TOKEN_HEADER: host},
    )
    assert time_add.status_code == 200

    response = client.get(
        "/api/games/{}/state".format(game_id),
        headers={HOST_TOKEN_HEADER: host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert data["status"] != Game.STATUS_GAME_COMPLETE
    assert data["current_round"] == 1
    assert data["round"]["round_number"] == 1
    assert len(data["teams"]) == 2
    assert data["resume_turn"] is not None
    rt = data["resume_turn"]
    assert rt["turn_id"] == turn_id
    assert rt["status"] == Turn.STATUS_ACTIVE
    # Timer is server-computed from the DB, and reflects the +3s penalty.
    assert rt["adjustment_seconds"] == 3
    assert rt["starting_seconds"] == 60
    assert 0 <= rt["remaining_seconds"] <= 63
    assert rt["current_word_text"] is not None
    assert rt["total_words"] == 3


def test_resume_state_restores_scoreboard_after_correct(client, app):
    s = _setup(client)
    game_id, host = s["game_id"], s["host"]
    start = _start_active_turn(client, s)
    turn_id = start.get_json()["data"]["turn_id"]

    correct = client.post(
        "/api/turns/{}/correct".format(turn_id), headers={HOST_TOKEN_HEADER: host}
    )
    assert correct.status_code == 200

    response = client.get(
        "/api/games/{}/state".format(game_id),
        headers={HOST_TOKEN_HEADER: host},
    )
    data = response.get_json()["data"]
    assert data["resume_turn"]["correct_words"] == 1
    scores = {row["team_id"]: row for row in data["scoreboard"]}
    assert s["team_a"]["team_id"] in scores


# ---------------------------------------------------------------------------
# Invalid transition validation (backend is the source of truth)
# ---------------------------------------------------------------------------


def test_invalid_transition_rejected(client, app):
    game_id, host = _create_game(client)
    with app.app_context():
        game = db.session.get(Game, game_id)
        game.status = Game.STATUS_GAME_COMPLETE
        db.session.commit()

    # A completed game must not transition back into an active round.
    with app.app_context():
        game = db.session.get(Game, game_id)
        with pytest.raises(game_service.GameStateError):
            game_service.resume_game(game)
