from datetime import timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import Game, TeamMember
from app.services import game_service, team_service
from app.services.maintenance import (
    expire_stale_device_sessions,
    reconcile_orphaned_games,
)
from app.utils.time import utcnow


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
    body = response.get_json()
    return body["data"]


def _set_host_absent(app, game_id, never_connected=False):
    with app.app_context():
        game = db.session.get(Game, game_id)
        if never_connected:
            game.host_last_seen_at = None
            game.created_at = utcnow() - timedelta(seconds=9999)
        else:
            game.host_last_seen_at = utcnow() - timedelta(seconds=9999)
        db.session.commit()
        return game


def _reconcile(app, timeout=100):
    with app.app_context():
        return reconcile_orphaned_games(host_timeout_seconds=timeout)


def test_reconcile_expires_game_whose_host_has_been_absent(app, client):
    data = _create_game(client)
    _set_host_absent(app, data["game_id"])

    expired = _reconcile(app)

    with app.app_context():
        game = db.session.get(Game, data["game_id"])
        assert expired == 1
        assert game.status == Game.STATUS_EXPIRED
        assert game.ended_at is not None


def test_reconcile_ignores_game_with_recent_host_activity(app, client):
    data = _create_game(client)
    with app.app_context():
        game = db.session.get(Game, data["game_id"])
        game.host_last_seen_at = utcnow()
        db.session.commit()

    expired = _reconcile(app)

    with app.app_context():
        game = db.session.get(Game, data["game_id"])
        assert expired == 0
        assert game.status != Game.STATUS_EXPIRED


def test_reconcile_expires_game_never_connected_too_old(app, client):
    data = _create_game(client)
    _set_host_absent(app, data["game_id"], never_connected=True)

    expired = _reconcile(app)

    with app.app_context():
        game = db.session.get(Game, data["game_id"])
        assert expired == 1
        assert game.status == Game.STATUS_EXPIRED


def test_reconcile_skips_terminal_games(app, client):
    data = _create_game(client)
    with app.app_context():
        game = db.session.get(Game, data["game_id"])
        game.host_last_seen_at = utcnow() - timedelta(seconds=9999)
        game.status = Game.STATUS_GAME_COMPLETE
        db.session.commit()

    expired = _reconcile(app)

    with app.app_context():
        game = db.session.get(Game, data["game_id"])
        assert expired == 0
        assert game.status == Game.STATUS_GAME_COMPLETE


def test_expired_game_is_frozen_and_rejects_new_team(app, client):
    data = _create_game(client)
    _set_host_absent(app, data["game_id"])
    assert _reconcile(app) == 1

    response = client.post(
        "/api/games/{}/teams".format(data["game_id"]),
        json={"team_name": "Team A", "username": "Juan"},
    )
    assert response.status_code == 409
    body = response.get_json()
    assert body["error"]["code"] == "GAME_FROZEN"


def test_mark_game_expired_is_idempotent(app, client):
    data = _create_game(client)

    with app.app_context():
        game = db.session.get(Game, data["game_id"])
        assert game_service.mark_game_expired(game) is True
        db.session.commit()
        status_after_first = game.status

        assert game_service.mark_game_expired(game) is False
        db.session.commit()
        assert status_after_first == Game.STATUS_EXPIRED
        assert game.status == Game.STATUS_EXPIRED


def test_expire_stale_device_sessions_marks_disconnected(app, client):
    data = _create_game(client)
    game_id = data["game_id"]

    team_resp = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"team_name": "Team A", "username": "Juan"},
    )
    assert team_resp.status_code == 201
    leader = team_resp.get_json()["data"]["leader"]

    conn_resp = client.post(
        "/api/devices/connect",
        json={"connection_token": leader["connection_token"], "device_id": "dev-1"},
    )
    assert conn_resp.status_code == 201
    session_token = conn_resp.get_json()["data"]["session_token"]

    with app.app_context():
        sess = team_service._get_device_session(session_token)
        sess.last_heartbeat = utcnow() - timedelta(seconds=9999)
        db.session.commit()
        sess_id = sess.id
        count = expire_stale_device_sessions(timeout_seconds=60)
        assert count >= 1

    with app.app_context():
        sess = team_service._get_device_session(session_token)
        assert sess.disconnected_at is not None


def test_expire_stale_sweep_reports_swept_sessions(app, client):
    data = _create_game(client)
    game_id = data["game_id"]

    team_resp = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"team_name": "Team A", "username": "Juan"},
    )
    assert team_resp.status_code == 201
    team_data = team_resp.get_json()["data"]
    leader = team_data["leader"]

    conn_resp = client.post(
        "/api/devices/connect",
        json={"connection_token": leader["connection_token"], "device_id": "dev-1"},
    )
    assert conn_resp.status_code == 201
    session_token = conn_resp.get_json()["data"]["session_token"]

    with app.app_context():
        sess = team_service._get_device_session(session_token)
        sess.last_heartbeat = utcnow() - timedelta(seconds=9999)
        db.session.commit()

        swept = team_service.expire_stale_sessions(timeout_seconds=60)
        assert swept == [(game_id, team_data["team_id"], leader["member_id"])]

        member = db.session.get(TeamMember, leader["member_id"])
        assert member.is_connected is False


def test_expire_stale_sweep_skips_fresh_sessions(app, client):
    data = _create_game(client)
    game_id = data["game_id"]

    team_resp = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"team_name": "Team A", "username": "Juan"},
    )
    assert team_resp.status_code == 201
    leader = team_resp.get_json()["data"]["leader"]

    conn_resp = client.post(
        "/api/devices/connect",
        json={"connection_token": leader["connection_token"], "device_id": "dev-1"},
    )
    assert conn_resp.status_code == 201
    session_token = conn_resp.get_json()["data"]["session_token"]

    with app.app_context():
        swept = team_service.expire_stale_sessions(timeout_seconds=60)
        assert swept == []
        sess = team_service._get_device_session(session_token)
        assert sess.disconnected_at is None


def test_reconcile_disabled_when_timeout_zero(app, client):
    data = _create_game(client)
    _set_host_absent(app, data["game_id"])

    expired = _reconcile(app, timeout=0)

    with app.app_context():
        game = db.session.get(Game, data["game_id"])
        assert expired == 0
        assert game.status != Game.STATUS_EXPIRED


def test_sweep_keeps_recent_heartbeat_within_grace(app, client):
    # A device that stopped beating for a while but is still inside the grace
    # window (DEVICE_HEARTBEAT_TIMEOUT * GRACE_MULTIPLIER) must NOT be swept.
    app.config["DEVICE_HEARTBEAT_TIMEOUT"] = 60
    app.config["DEVICE_HEARTBEAT_GRACE_MULTIPLIER"] = 3  # effective = 180s

    data = _create_game(client)
    team_resp = client.post(
        "/api/games/{}/teams".format(data["game_id"]),
        json={"team_name": "Team A", "username": "Juan"},
    )
    leader = team_resp.get_json()["data"]["leader"]
    conn_resp = client.post(
        "/api/devices/connect",
        json={"connection_token": leader["connection_token"], "device_id": "dev-1"},
    )
    session_token = conn_resp.get_json()["data"]["session_token"]

    with app.app_context():
        sess = team_service._get_device_session(session_token)
        # 120s stale: past the raw 60s timeout but inside the 180s grace.
        sess.last_heartbeat = utcnow() - timedelta(seconds=120)
        db.session.commit()

        from app.services.maintenance import _sweep

        _sweep(app)

        refreshed = team_service._get_device_session(session_token)
        assert refreshed.disconnected_at is None


def test_sweep_expires_heartbeat_beyond_grace(app, client):
    app.config["DEVICE_HEARTBEAT_TIMEOUT"] = 60
    app.config["DEVICE_HEARTBEAT_GRACE_MULTIPLIER"] = 3  # effective = 180s

    data = _create_game(client)
    team_resp = client.post(
        "/api/games/{}/teams".format(data["game_id"]),
        json={"team_name": "Team A", "username": "Juan"},
    )
    leader = team_resp.get_json()["data"]["leader"]
    conn_resp = client.post(
        "/api/devices/connect",
        json={"connection_token": leader["connection_token"], "device_id": "dev-1"},
    )
    session_token = conn_resp.get_json()["data"]["session_token"]

    with app.app_context():
        sess = team_service._get_device_session(session_token)
        sess.last_heartbeat = utcnow() - timedelta(seconds=9999)
        db.session.commit()

        from app.services.maintenance import _sweep

        _sweep(app)

        refreshed = team_service._get_device_session(session_token)
        assert refreshed.disconnected_at is not None
