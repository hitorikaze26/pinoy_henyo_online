"""Tests for the Part-2 backend contract:

- deep-link resolution (``/join/game`` and ``/join/team``),
- GAME_ENDED responses when a player joins/requests connection to an ended
  game (instead of the host-facing "read-only" mechanics message), and
- the full host-switch flow (join a second game -> device connect rebinds
  the session -> old session superseded -> connection request to the new
  game).
"""

import pytest

from app import create_app
from app.extensions import db
from app.models import DeviceSession


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
    return {
        "game_id": data["game_id"],
        "game_code": data["game_code"],
        "host_token": data["host_session_token"],
    }


def _create_team(client, game_id, username="Juan", team_name="Team Henyo"):
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"username": username, "team_name": team_name},
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _connect(client, **payload):
    response = client.post("/api/devices/connect", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]


def _end_game(client, game_id, host_token):
    start = client.post(
        "/api/games/{}/start".format(game_id),
        headers={"X-Host-Token": host_token},
    )
    assert start.status_code == 200, start.get_json()
    response = client.post(
        "/api/games/{}/end".format(game_id),
        headers={"X-Host-Token": host_token},
    )
    assert response.status_code == 200, response.get_json()


# ---------------------------------------------------------------------------
# Deep-link resolvers
# ---------------------------------------------------------------------------


def test_join_game_deep_link_redirects_to_landing(client):
    game = _create_game(client)
    response = client.get("/join/game/{}".format(game["game_code"]))
    assert response.status_code == 302
    assert response.headers["Location"] == "/?game={}".format(game["game_code"])


def test_join_team_deep_link_redirects_with_both_codes(client):
    game = _create_game(client)
    team = _create_team(client, game["game_id"])
    response = client.get(
        "/join/team/{}?game={}".format(team["team_code"], game["game_code"])
    )
    assert response.status_code == 302
    assert response.headers["Location"] == (
        "/?game={}&team={}".format(game["game_code"], team["team_code"])
    )


def test_deep_link_lowercase_codes_are_normalized(client):
    game = _create_game(client)
    team = _create_team(client, game["game_id"])
    response = client.get(
        "/join/team/{}?game={}".format(
            team["team_code"].lower(), game["game_code"].lower()
        )
    )
    assert response.status_code == 302
    assert response.headers["Location"] == (
        "/?game={}&team={}".format(game["game_code"], team["team_code"])
    )


def test_deep_link_unknown_game_redirects_with_error(client):
    response = client.get("/join/game/PHZZZZ")
    assert response.status_code == 302
    assert "error=not_found" in response.headers["Location"]


def test_deep_link_team_missing_game_param(client):
    response = client.get("/join/team/ABCD")
    assert response.status_code == 302
    assert "error=missing_game" in response.headers["Location"]


def test_deep_link_unknown_team_redirects_with_error(client):
    game = _create_game(client)
    response = client.get("/join/team/ZZZZ?game={}".format(game["game_code"]))
    assert response.status_code == 302
    assert "error=team_not_found" in response.headers["Location"]


def test_deep_link_ended_game_redirects_with_error(client):
    game = _create_game(client)
    _end_game(client, game["game_id"], game["host_token"])
    response = client.get("/join/game/{}".format(game["game_code"]))
    assert response.status_code == 302
    assert "error=not_found" in response.headers["Location"]


# ---------------------------------------------------------------------------
# GAME_ENDED: player-facing rejection on ended games
# ---------------------------------------------------------------------------


def test_join_ended_game_returns_game_ended(client):
    game = _create_game(client)
    _end_game(client, game["game_id"], game["host_token"])
    response = client.post(
        "/api/games/{}/join".format(game["game_id"]),
        json={"username": "Juan", "team_name": "Team Henyo"},
    )
    assert response.status_code == 410
    assert response.get_json()["error"]["code"] == "GAME_ENDED"
    assert "no longer accepting" in response.get_json()["error"]["message"]


def test_connection_request_to_ended_game_returns_game_ended(client):
    game = _create_game(client)
    team = _create_team(client, game["game_id"])
    conn = _connect(
        client, connection_token=team["leader"]["connection_token"], device_id="dev-1"
    )
    _end_game(client, game["game_id"], game["host_token"])
    response = client.post(
        "/api/games/{}/connection-request".format(game["game_id"]),
        headers={"X-Session-Token": conn["session_token"]},
    )
    assert response.status_code == 410
    assert response.get_json()["error"]["code"] == "GAME_ENDED"


# ---------------------------------------------------------------------------
# Host-switch composite contract (Part 2)
# ---------------------------------------------------------------------------


def test_switch_rebinds_session_and_requests_connection(client, app):
    # 1) Game A + team + connected device session.
    game_a = _create_game(client)
    team_a = _create_team(client, game_a["game_id"], username="Leo")
    conn_a = _connect(
        client,
        connection_token=team_a["leader"]["connection_token"],
        device_id="dev-switch-1",
    )

    # 2) Game B: join by team name (fresh team), reconnect the SAME device.
    game_b = _create_game(client)
    join_resp = client.post(
        "/api/games/{}/join".format(game_b["game_id"]),
        json={"username": "Leo", "team_name": "Team B"},
    )
    assert join_resp.status_code == 201, join_resp.get_json()
    joined_b = join_resp.get_json()["data"]
    tok_b = joined_b["leader"]["connection_token"]

    conn_resp = client.post(
        "/api/devices/connect",
        json={
            "connection_token": tok_b,
            "device_id": "dev-switch-1",
            "session_token": conn_a["session_token"],
        },
    )
    assert conn_resp.status_code == 201, conn_resp.get_json()
    conn_b = conn_resp.get_json()["data"]
    assert conn_b["session_token"] != conn_a["session_token"]
    assert conn_b["game_id"] == game_b["game_id"]
    assert conn_b["team_id"] == joined_b["team_id"]
    assert conn_b["member_id"] == joined_b["leader"]["member_id"]

    # Old session in game A is superseded (not left dangling/hidden).
    with app.app_context():
        stale = DeviceSession.query.filter_by(
            session_token=conn_a["session_token"]
        ).first()
        assert stale is not None
        assert stale.disconnected_at is not None
        assert stale.game_id == game_a["game_id"]

    # 3) Request connection in the NEW game with the NEW session.
    req_resp = client.post(
        "/api/games/{}/connection-request".format(game_b["game_id"]),
        headers={"X-Session-Token": conn_b["session_token"]},
    )
    assert req_resp.status_code == 200, req_resp.get_json()
    assert req_resp.get_json()["data"]["connection_status"] == "CONNECTION_REQUESTED"
    assert req_resp.get_json()["data"]["team_id"] == joined_b["team_id"]


def test_by_code_resolution_exists_for_switch(client):
    game = _create_game(client)
    response = client.get("/api/games/by-code/{}".format(game["game_code"]))
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["game_id"] == game["game_id"]
    assert data["game_code"] == game["game_code"]