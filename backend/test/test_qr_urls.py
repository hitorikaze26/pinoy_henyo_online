"""Regression tests for QR deep-link origin resolution.

Covers the localhost / LAN IP / Cloudflare-Tunnel-online split:

- explicit QR_BASE_URL override wins,
- request origin (host/scheme) is the fallback,
- X-Forwarded-Proto / X-Forwarded-Host from Cloudflare/rev-proxies win,
- game and team payload shapes stay stable.
"""

import pytest

from app import create_app
from app.extensions import db
from app.models import Game, Team
from app.services import qr_service


@pytest.fixture()
def app():
    test_app = create_app("testing")
    with test_app.app_context():
        db.create_all()
    yield test_app


@pytest.fixture()
def client(app):
    return app.test_client()


def _create_game(client):
    response = client.post("/api/games")
    assert response.status_code == 201
    return response.get_json()["data"]


def _create_team(client, game_id):
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"team_name": "Team A", "username": "Juan"},
    )
    assert response.status_code == 201
    return response.get_json()["data"]


# ---------------------------------------------------------------------------
# Game payloads
# ---------------------------------------------------------------------------


def test_qr_uses_explicit_config_override(app, client):
    app.config["QR_BASE_URL"] = "https://game.example.com"
    game = _create_game(client)
    with app.app_context(), app.test_request_context(
        "/", base_url="http://internal:5000"
    ):
        payload = qr_service.game_qr_payload(db.session.get(Game, game["game_id"]))
    assert payload == "https://game.example.com/join/game/{}".format(game["game_code"])


def test_qr_falls_back_to_request_origin_for_localhost(app, client):
    game = _create_game(client)
    with app.app_context(), app.test_request_context(
        "/", base_url="http://localhost:5000"
    ):
        payload = qr_service.game_qr_payload(db.session.get(Game, game["game_id"]))
    assert payload == "http://localhost:5000/join/game/{}".format(game["game_code"])


def test_qr_falls_back_to_request_origin_for_lan_ip(app, client):
    game = _create_game(client)
    with app.app_context(), app.test_request_context(
        "/", base_url="http://192.168.1.50:5000"
    ):
        payload = qr_service.game_qr_payload(db.session.get(Game, game["game_id"]))
    assert payload == "http://192.168.1.50:5000/join/game/{}".format(game["game_code"])


def test_qr_honors_cloudflare_proxy_headers(app, client):
    game = _create_game(client)
    with app.app_context(), app.test_request_context(
        "/",
        base_url="http://internal-tunnel:5000",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "game.example.com",
        },
    ):
        payload = qr_service.game_qr_payload(db.session.get(Game, game["game_id"]))
    assert payload == "https://game.example.com/join/game/{}".format(game["game_code"])


def test_qr_never_returns_empty_origin(app, client):
    game = _create_game(client)
    with app.app_context(), app.test_request_context("/", base_url="http://localhost/"):
        payload = qr_service.game_qr_payload(db.session.get(Game, game["game_id"]))
    assert payload.startswith("http://")


# ---------------------------------------------------------------------------
# Team payloads
# ---------------------------------------------------------------------------


def test_team_qr_payload_contains_both_codes(app, client):
    game = _create_game(client)
    team = _create_team(client, game["game_id"])
    with app.app_context(), app.test_request_context(
        "/", base_url="http://localhost:5000"
    ):
        big_payload = qr_service.team_qr_payload(db.session.get(Team, team["team_id"]))
    assert big_payload == "http://localhost:5000/join/team/{}?game={}".format(
        team["team_code"], game["game_code"]
    )


def test_team_qr_payload_respects_override(app, client):
    app.config["QR_BASE_URL"] = "https://game.example.com"
    game = _create_game(client)
    team = _create_team(client, game["game_id"])
    with app.app_context(), app.test_request_context(
        "/", base_url="http://internal:5000"
    ):
        big_payload = qr_service.team_qr_payload(db.session.get(Team, team["team_id"]))
    assert big_payload == "https://game.example.com/join/team/{}?game={}".format(
        team["team_code"], game["game_code"]
    )


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


def test_game_api_qr_payload_uses_request_origin(client):
    game = _create_game(client)
    headers = {"X-Host-Token": game["host_session_token"]}
    response = client.get(
        "/api/games/{}/qr".format(game["game_id"]),
        headers=headers,
        base_url="http://192.168.1.50:5000",
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["data"]["payload"].startswith(
        "http://192.168.1.50:5000/join/game/"
    )