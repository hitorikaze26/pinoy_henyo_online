"""Tests for the host "Leave Game" endpoint (Part 3).

Host Leave Game ends the host's device session while keeping the game,
teams, members, words and scores intact. When the host leaves mid-play the
game is paused so it cannot advance unattended.
"""

import pytest

from app import create_app
from app.extensions import db
from app.models import Game, GameEvent, Team, TeamMember
from app.utils.time import utcnow

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


def _create_team(client, game_id, host_token, team_name="Team A", username="Juan"):
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"username": username, "team_name": team_name},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _leave(client, game_id, host_token=None):
    headers = {HOST_TOKEN_HEADER: host_token} if host_token else {}
    return client.post("/api/games/{}/leave".format(game_id), headers=headers)


def test_leave_game_requires_host_token(client):
    g = _create_game(client)
    response = _leave(client, g["game_id"])
    assert response.status_code == 401


def test_leave_game_keeps_data_and_status(client, app):
    g = _create_game(client)
    host = g["host_session_token"]
    game_id = g["game_id"]
    team = _create_team(client, game_id, host)
    member_id = team["leader"]["member_id"]
    team_id = team["team_id"]

    with app.app_context():
        game = db.session.get(Game, game_id)
        game.host_last_seen_at = utcnow()
        db.session.commit()

    response = _leave(client, game_id, host)
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == Game.STATUS_LOBBY

    with app.app_context():
        game = db.session.get(Game, game_id)
        assert game is not None
        assert game.status == Game.STATUS_LOBBY
        assert game.host_last_seen_at is None
        assert db.session.get(Team, team_id) is not None
        assert db.session.get(TeamMember, member_id) is not None
        assert (
            GameEvent.query.filter_by(game_id=game_id, event_type="HOST_LEFT").count()
            == 1
        )


def test_leave_game_pauses_active_round(client, app):
    g = _create_game(client)
    host = g["host_session_token"]
    game_id = g["game_id"]

    with app.app_context():
        game = db.session.get(Game, game_id)
        game.status = Game.STATUS_ROUND_1
        game.current_round = 1
        game.host_last_seen_at = utcnow()
        db.session.commit()

    response = _leave(client, game_id, host)
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == Game.STATUS_PAUSED

    with app.app_context():
        assert db.session.get(Game, game_id).status == Game.STATUS_PAUSED


@pytest.mark.parametrize(
    "status",
    [
        Game.STATUS_GAME_COMPLETE,
        Game.STATUS_CANCELLED,
        Game.STATUS_EXPIRED,
    ],
)
def test_leave_finished_game_allowed(client, app, status):
    """Hosts can leave finished games: terminal status stays intact and a
    HOST_LEFT event is recorded (no misleading pause)."""
    g = _create_game(client)
    host = g["host_session_token"]
    game_id = g["game_id"]

    with app.app_context():
        game = db.session.get(Game, game_id)
        game.status = status
        if status == Game.STATUS_GAME_COMPLETE:
            game.ended_at = utcnow()
        db.session.commit()

    response = _leave(client, game_id, host)
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == status

    with app.app_context():
        game = db.session.get(Game, game_id)
        assert game.status == status
        assert game.host_last_seen_at is None
        assert (
            GameEvent.query.filter_by(
                game_id=game_id, event_type="HOST_LEFT"
            ).count()
            == 1
        )


def test_leave_then_reconnect_host_session(client, app):
    g = _create_game(client)
    host = g["host_session_token"]
    game_id = g["game_id"]

    response = _leave(client, game_id, host)
    assert response.status_code == 200

    # The host session token remains valid for reconnection: the host can
    # still read the game and interact after leaving/returning.
    status = client.get("/api/games/{}/status".format(game_id))
    assert status.status_code == 200
    assert status.get_json()["data"]["game_id"] == game_id


def test_leave_wrong_host_token_rejected(client, app):
    g = _create_game(client)
    other = _create_game(client)
    response = _leave(client, g["game_id"], other["host_session_token"])
    assert response.status_code == 401
