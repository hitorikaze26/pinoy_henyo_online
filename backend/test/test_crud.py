"""Tests for CRUD & database service layer (Part 2)."""

import pytest

from app import create_app
from app.extensions import db
from app.models import DeviceSession, Game, Match, Penalty, Round, Score, Team, TeamMember, Turn

HOST_TOKEN_HEADER = "X-Host-Token"


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
    return response.get_json()["data"]


def _create_team(client, game_id, team_name="Team A", username="Juan",
                 host_token=None):
    headers = {HOST_TOKEN_HEADER: host_token} if host_token else {}
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"username": username, "team_name": team_name},
        headers=headers,
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _add_member(client, team_id, username="Pedro"):
    response = client.post(
        "/api/teams/{}/members".format(team_id),
        json={"username": username},
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _connect(client, **payload):
    return client.post("/api/devices/connect", json=payload)


def _leader_session(client, team):
    response = _connect(
        client,
        connection_token=team["leader"]["connection_token"],
        device_id="dev-session",
    )
    assert response.status_code == 201
    return response.get_json()["data"]["session_token"]


# ---------------------------------------------------------------------------
# Game deletion (host history cleanup)
# ---------------------------------------------------------------------------


def test_delete_game_requires_host(client):
    g = _create_game(client)
    # No host token -> 401
    response = client.delete("/api/games/{}".format(g["game_id"]))
    assert response.status_code in (401, 404)
    # Wrong host token -> 401
    response = client.delete(
        "/api/games/{}".format(g["game_id"]),
        headers={HOST_TOKEN_HEADER: "wrong-token"},
    )
    assert response.status_code in (401, 404)


def test_delete_requires_confirmation(client, app):
    g = _create_game(client)
    from app.services import game_service
    with app.app_context():
        game = db.session.get(Game, g["game_id"])
        game.status = Game.STATUS_CANCELLED
        db.session.commit()
    # No confirm flag -> 400.
    response = client.delete(
        "/api/games/{}".format(g["game_id"]),
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "WITH_CONFIRMATION_REQUIRED"
    with app.app_context():
        assert db.session.get(Game, g["game_id"]) is not None


def test_delete_wrong_host_rejected(client, app):
    g = _create_game(client)
    other = _create_game(client)
    from app.services import game_service
    with app.app_context():
        game = db.session.get(Game, g["game_id"])
        game.status = Game.STATUS_CANCELLED
        db.session.commit()
    response = client.delete(
        "/api/games/{}".format(g["game_id"]),
        json={"confirm": True},
        headers={HOST_TOKEN_HEADER: other["host_session_token"]},
    )
    assert response.status_code in (401, 404)


def test_delete_looby_game_rejected(client):
    g = _create_game(client)
    response = client.delete(
        "/api/games/{}".format(g["game_id"]),
        json={"confirm": True},
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    # Only terminal games may be deleted; LOBBY is not terminal.
    assert response.status_code == 409


def test_delete_completed_game_removes_all_cascades(client, app):
    g = _create_game(client)
    team = _create_team(
        client, g["game_id"], host_token=g["host_session_token"]
    )
    team_id = team["team_id"]

    # Force the game to a terminal (cancelled) state via direct service call.
    from app.services import game_service
    with app.app_context():
        game = db.session.get(Game, g["game_id"])
        game.status = Game.STATUS_CANCELLED
        db.session.commit()

    response = client.delete(
        "/api/games/{}".format(g["game_id"]),
        json={"confirm": True},
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 200

    with app.app_context():
        assert db.session.get(Game, g["game_id"]) is None
        assert db.session.get(Team, team_id) is None


# ---------------------------------------------------------------------------
# Team deletion
# ---------------------------------------------------------------------------


def test_delete_team_requires_host(client):
    g = _create_game(client)
    team = _create_team(client, g["game_id"])
    response = client.delete("/api/teams/{}".format(team["team_id"]))
    assert response.status_code in (401, 404)


def test_delete_team_removes_team_and_members(client, app):
    g = _create_game(client)
    team = _create_team(client, g["game_id"])
    team_id = team["team_id"]
    member = _add_member(client, team_id)
    member_id = member["member_id"]

    response = client.delete(
        "/api/teams/{}".format(team_id),
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 200

    with app.app_context():
        assert db.session.get(Team, team_id) is None
        assert db.session.get(TeamMember, member_id) is None


def test_delete_connected_team_rejected(client, app):
    g = _create_game(client)
    team = _create_team(client, g["game_id"])
    team_id = team["team_id"]
    with app.app_context():
        t = db.session.get(Team, team_id)
        t.connection_status = Team.CONNECTION_CONNECTED
        db.session.commit()

    response = client.delete(
        "/api/teams/{}".format(team_id),
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Member removal
# ---------------------------------------------------------------------------


def test_remove_member(client, app):
    g = _create_game(client)
    team = _create_team(client, g["game_id"])
    team_id = team["team_id"]
    member = _add_member(client, team_id)
    member_id = member["member_id"]

    leader_session = _leader_session(client, team)

    response = client.delete(
        "/api/members/{}".format(member_id),
        headers={"X-Session-Token": leader_session},
    )
    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(TeamMember, member_id) is None


def test_remove_team_leader_rejected(client):
    g = _create_game(client)
    team = _create_team(client, g["game_id"])
    leader_id = team["leader"]["member_id"]

    response = client.delete(
        "/api/members/{}".format(leader_id),
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Penalty revert
# ---------------------------------------------------------------------------


def _build_full_game(client, app):
    """Set up two teams with an active round/match/turn."""
    from app.services import gameplay_service, turn_service

    g = _create_game(client)
    host = g["host_session_token"]
    game_id = g["game_id"]

    # Create categories
    for name in ("Food", "Places"):
        client.post("/api/games/{}/categories".format(game_id),
                    json={"name": name},
                    headers={HOST_TOKEN_HEADER: host})

    # Create teams
    team_a = _create_team(client, game_id, team_name="Team A", username="A",
                           host_token=host)
    team_b = _create_team(client, game_id, team_name="Team B", username="B",
                           host_token=host)

    return {
        "client": client, "app": app, "host": host, "game_id": game_id,
        "team_a": team_a, "team_b": team_b,
    }
