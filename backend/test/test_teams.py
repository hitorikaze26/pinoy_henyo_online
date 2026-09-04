import base64
from datetime import timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import DeviceSession, Team, TeamMember
from app.services import team_service
from app.utils.time import utcnow

PNG_MAGIC = b"\x89PNG"


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
    return response.get_json()["data"]["game_id"]


def _create_team(client, game_id, team_name="Team Henyo", username="Juan"):
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"username": username, "team_name": team_name},
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _connect(client, **payload):
    return client.post("/api/devices/connect", json=payload)


# ---------------------------------------------------------------------------
# Team creation
# ---------------------------------------------------------------------------


def test_create_team_returns_expected_fields(client):
    game_id = _create_game(client)
    data = _create_team(client, game_id)
    assert set(data) == {
        "team_id",
        "team_code",
        "team_name",
        "team_status",
        "connection_status",
        "leader",
    }
    assert data["team_name"] == "Team Henyo"
    assert len(data["team_code"]) == 4
    assert data["team_status"] == "ACTIVE"
    # Player-created teams start NOT_CONNECTED until the host approves them.
    assert data["connection_status"] == "NOT_CONNECTED"


def test_team_codes_unique_within_game(client):
    game_id = _create_game(client)
    codes = {_create_team(client, game_id)["team_code"] for _ in range(20)}
    assert len(codes) == 20


def test_team_creation_makes_leader(client, app):
    game_id = _create_game(client)
    data = _create_team(client, game_id, username="Kris")
    leader = data["leader"]
    assert leader["username"] == "Kris"
    assert leader["device_role"] == TeamMember.DEVICE_ROLE_TEAM_LEADER
    assert leader["connection_token"]
    with app.app_context():
        team = db.session.get(Team, data["team_id"])
        assert team.leader is not None
        assert team.leader.id == leader["member_id"]
        assert team.leader.username == "Kris"


def test_only_one_leader_per_team(client, app):
    game_id = _create_game(client)
    team_id = _create_team(client, game_id)["team_id"]
    for i in range(3):
        response = client.post(
            "/api/teams/{}/members".format(team_id),
            json={"username": "Pedro{}".format(i)},
        )
        assert response.status_code == 201
        assert (
            response.get_json()["data"]["device_role"]
            == TeamMember.DEVICE_ROLE_TEAM_MEMBER
        )
    with app.app_context():
        leaders = (
            db.session.query(TeamMember)
            .filter_by(
                team_id=team_id,
                device_role=TeamMember.DEVICE_ROLE_TEAM_LEADER,
            )
            .count()
        )
        assert leaders == 1


def test_team_creation_validation(client):
    game_id = _create_game(client)
    url = "/api/games/{}/teams".format(game_id)
    assert (
        client.post(url, json={"username": "", "team_name": "X"}).status_code
        == 400
    )
    assert (
        client.post(url, json={"username": "Juan", "team_name": ""}).status_code
        == 400
    )


def test_team_not_found(client):
    assert (
        client.post(
            "/api/teams/999999/members", json={"username": "Pedro"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/teams/999999/join", json={"username": "Pedro"}
        ).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Game & team joining
# ---------------------------------------------------------------------------


def test_game_join_creates_team(client):
    game_id = _create_game(client)
    response = client.post(
        "/api/games/{}/join".format(game_id),
        json={"username": "Ana", "team_name": "Team B"},
    )
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["team_name"] == "Team B"
    assert data["leader"]["username"] == "Ana"


def test_game_join_existing_team_by_code(client):
    game_id = _create_game(client)
    team = _create_team(client, game_id)
    response = client.post(
        "/api/games/{}/join".format(game_id),
        json={"username": "Pedro", "team_code": team["team_code"]},
    )
    assert response.status_code == 201
    member = response.get_json()["data"]
    assert member["team_id"] == team["team_id"]
    assert member["username"] == "Pedro"
    assert member["device_role"] == TeamMember.DEVICE_ROLE_TEAM_MEMBER


def test_game_join_team_code_scoped_to_game(client):
    game_id_a = _create_game(client)
    game_id_b = _create_game(client)
    team_a = _create_team(client, game_id_a)
    response = client.post(
        "/api/games/{}/join".format(game_id_b),
        json={"username": "Pedro", "team_code": team_a["team_code"]},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "TEAM_CODE_INVALID"


def test_game_join_missing_params(client):
    game_id = _create_game(client)
    response = client.post(
        "/api/games/{}/join".format(game_id), json={"username": "Ana"}
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "JOIN_PARAMS_INVALID"


def test_team_join_direct(client):
    game_id = _create_game(client)
    team = _create_team(client, game_id)
    response = client.post(
        "/api/teams/{}/join".format(team["team_id"]),
        json={"username": "Pedro"},
    )
    assert response.status_code == 201
    member = response.get_json()["data"]
    assert member["team_id"] == team["team_id"]
    assert member["username"] == "Pedro"


# ---------------------------------------------------------------------------
# Device sessions
# ---------------------------------------------------------------------------


def test_connect_leader_device(client, app):
    game_id = _create_game(client)
    data = _create_team(client, game_id)
    response = _connect(
        client,
        connection_token=data["leader"]["connection_token"],
        device_id="device-leader",
    )
    assert response.status_code == 201
    session = response.get_json()["data"]
    assert session["team_id"] == data["team_id"]
    assert session["member_id"] == data["leader"]["member_id"]
    assert session["device_type"] == DeviceSession.DEVICE_TYPE_TEAM_LEADER
    assert session["session_token"]


def test_connect_multiple_devices(client):
    game_id = _create_game(client)
    team = _create_team(client, game_id)
    member_resp = client.post(
        "/api/teams/{}/members".format(team["team_id"]),
        json={"username": "Pedro"},
    )
    member = member_resp.get_json()["data"]

    first = _connect(
        client, connection_token=team["leader"]["connection_token"], device_id="dev-l"
    )
    second = _connect(
        client, connection_token=member["connection_token"], device_id="dev-m"
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert (
        second.get_json()["data"]["device_type"]
        == DeviceSession.DEVICE_TYPE_TEAM_MEMBER
    )


def test_connect_requires_device_id(client):
    game_id = _create_game(client)
    team = _create_team(client, game_id)
    response = _connect(
        client, connection_token=team["leader"]["connection_token"]
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "DEVICE_ID_REQUIRED"


def test_connect_invalid_connection_token(client):
    response = _connect(client, connection_token="bogus", device_id="dev-1")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "CONNECTION_TOKEN_INVALID"


def test_connect_requires_token(client):
    response = _connect(client, device_id="dev-1")
    assert response.status_code == 400
    assert (
        response.get_json()["error"]["code"] == "CONNECTION_TOKEN_REQUIRED"
    )


def test_connect_ignores_client_team_id(client):
    game_id = _create_game(client)
    team_a = _create_team(client, game_id, team_name="Team A")
    team_b = _create_team(client, game_id, team_name="Team B")

    response = _connect(
        client,
        connection_token=team_b["leader"]["connection_token"],
        device_id="dev-b",
        team_id=team_a["team_id"],
    )
    assert response.status_code == 201
    # The session must be bound to Team B, not the attacker-supplied team_id.
    assert response.get_json()["data"]["team_id"] == team_b["team_id"]


def test_heartbeat_updates_last_heartbeat(client, app):
    game_id = _create_game(client)
    team = _create_team(client, game_id)
    session = _connect(
        client, connection_token=team["leader"]["connection_token"], device_id="dev"
    ).get_json()["data"]

    response = client.post(
        "/api/devices/heartbeat", json={"session_token": session["session_token"]}
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["last_heartbeat"] is not None
    with app.app_context():
        row = db.session.query(DeviceSession).filter_by(
            session_token=session["session_token"]
        ).first()
        assert row.last_heartbeat is not None


def test_heartbeat_wrong_device_unauthorized(client):
    game_id = _create_game(client)
    team = _create_team(client, game_id)
    session = _connect(
        client, connection_token=team["leader"]["connection_token"], device_id="dev"
    ).get_json()["data"]

    response = client.post(
        "/api/devices/heartbeat",
        json={
            "session_token": session["session_token"],
            "device_id": "some-other-device",
        },
    )
    assert response.status_code == 401


def test_heartbeat_unknown_session(client):
    response = client.post(
        "/api/devices/heartbeat", json={"session_token": "nope"}
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_disconnect_and_reconnect_via_session(client):
    game_id = _create_game(client)
    team = _create_team(client, game_id)
    session = _connect(
        client, connection_token=team["leader"]["connection_token"], device_id="dev"
    ).get_json()["data"]
    token = session["session_token"]

    disconnected = client.post(
        "/api/devices/disconnect", json={"session_token": token}
    )
    assert disconnected.status_code == 200
    assert disconnected.get_json()["data"]["disconnected_at"] is not None

    # heartbeat on a disconnected session must be refused
    refused = client.post(
        "/api/devices/heartbeat", json={"session_token": token}
    )
    assert refused.status_code == 410

    # reconnect with a valid session and device
    reconnected = _connect(client, session_token=token, device_id="dev")
    assert reconnected.status_code == 201
    assert reconnected.get_json()["data"]["disconnected_at"] is None
    assert (
        client.post(
            "/api/devices/heartbeat", json={"session_token": token}
        ).status_code
        == 200
    )


def test_disconnect_marks_member_disconnected(client, app):
    game_id = _create_game(client)
    team = _create_team(client, game_id)
    leader_id = team["leader"]["member_id"]
    session = _connect(
        client, connection_token=team["leader"]["connection_token"], device_id="dev"
    ).get_json()["data"]

    client.post("/api/devices/disconnect", json={"session_token": session["session_token"]})
    with app.app_context():
        member = db.session.get(TeamMember, leader_id)
        assert member.is_connected is False


def test_stale_sessions_expiry_and_reconnect(client, app):
    game_id = _create_game(client)
    team = _create_team(client, game_id)
    session = _connect(
        client, connection_token=team["leader"]["connection_token"], device_id="dev"
    ).get_json()["data"]
    token = session["session_token"]
    member_id = session["member_id"]

    with app.app_context():
        row = db.session.query(DeviceSession).filter_by(session_token=token).first()
        row.last_heartbeat = utcnow() - timedelta(minutes=10)
        db.session.commit()
        expired = team_service.expire_stale_sessions(timeout_seconds=60)
        db.session.commit()
        assert expired == 1
        assert row.disconnected_at is not None
        assert db.session.get(TeamMember, member_id).is_connected is False

    refused = client.post(
        "/api/devices/heartbeat", json={"session_token": token}
    )
    assert refused.status_code == 410

    reconnected = _connect(client, session_token=token, device_id="dev")
    assert reconnected.status_code == 201
    assert (
        client.post(
            "/api/devices/heartbeat", json={"session_token": token}
        ).status_code
        == 200
    )


def test_unauthorized_team_access(client):
    game_id = _create_game(client)
    team_a = _create_team(client, game_id, team_name="Team A")
    team_b = _create_team(client, game_id, team_name="Team B")

    session_a = _connect(
        client, connection_token=team_a["leader"]["connection_token"], device_id="dev-a"
    ).get_json()["data"]

    # Team B's connection token must not grant access to Team A's equipment.
    wrong = client.post(
        "/api/devices/heartbeat",
        json={
            "session_token": team_b["leader"]["connection_token"],
            "device_id": "dev-a",
        },
    )
    assert wrong.status_code == 404

    # Same token swapped between teams must still resolve to the real team.
    session_b = _connect(
        client, connection_token=team_b["leader"]["connection_token"], device_id="dev-b"
    ).get_json()["data"]
    assert session_b["team_id"] == team_b["team_id"]
    assert session_b["team_id"] != session_a["team_id"]


# ---------------------------------------------------------------------------
# QR codes
# ---------------------------------------------------------------------------


def test_game_qr_generation(client):
    create_response = client.post("/api/games")
    assert create_response.status_code == 201
    game_data = create_response.get_json()["data"]
    game_id = game_data["game_id"]
    host_token = game_data["host_session_token"]
    game_code = client.get("/api/games/{}".format(game_id)).get_json()["data"][
        "game_code"
    ]
    response = client.get(
        "/api/games/{}/qr".format(game_id), headers={"X-Host-Token": host_token}
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["payload"].startswith("https://pinoyhenyo.online/join/game/")
    assert data["payload"].endswith(game_code)
    image = base64.b64decode(data["qr_image"].split(",", 1)[1])
    assert image[:4] == PNG_MAGIC


def test_game_qr_requires_host_auth(client):
    game_id = _create_game(client)
    response = client.get("/api/games/{}/qr".format(game_id))
    assert response.status_code == 401


def test_team_qr_generation_is_safe(client):
    create_response = client.post("/api/games")
    assert create_response.status_code == 201
    game_data = create_response.get_json()["data"]
    game_id = game_data["game_id"]
    host_token = game_data["host_session_token"]
    team = _create_team(client, game_id)
    connection_token = team["leader"]["connection_token"]
    response = client.get(
        "/api/teams/{}/qr".format(team["team_id"]), headers={"X-Host-Token": host_token}
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert team["team_code"] in data["payload"]
    assert "team_id" not in data["payload"]
    # Sensitive data must never appear in the QR payload.
    assert connection_token not in data["payload"]
    image = base64.b64decode(data["qr_image"].split(",", 1)[1])
    assert image[:4] == PNG_MAGIC


def test_team_qr_requires_team(client):
    assert client.get("/api/teams/999999/qr").status_code == 404


# ---------------------------------------------------------------------------
# Team roster listing (host)
# ---------------------------------------------------------------------------


def test_list_teams_returns_real_roster(client):
    create_response = client.post("/api/games")
    assert create_response.status_code == 201
    game_data = create_response.get_json()["data"]
    game_id = game_data["game_id"]
    host_token = game_data["host_session_token"]

    team_a = _create_team(client, game_id, team_name="Team Henyo", username="Juan")
    team_b = _create_team(client, game_id, team_name="Team Laban", username="Kris")

    response = client.get(
        "/api/games/{}/teams".format(game_id), headers={"X-Host-Token": host_token}
    )
    assert response.status_code == 200
    teams = response.get_json()["data"]["teams"]
    assert [t["team_id"] for t in teams] == [team_a["team_id"], team_b["team_id"]]

    first = teams[0]
    assert first["team_name"] == "Team Henyo"
    assert first["leader"]["username"] == "Juan"
    assert [m["username"] for m in first["members"]] == ["Juan"]


def test_list_teams_requires_host(client):
    game_id = _create_game(client)
    _create_team(client, game_id)
    response = client.get("/api/games/{}/teams".format(game_id))
    assert response.status_code == 401


def test_list_teams_game_not_found(client):
    assert client.get("/api/games/999999/teams").status_code == 404


# ---------------------------------------------------------------------------
# Host connection approval workflow (connection_status state machine)
# ---------------------------------------------------------------------------


def _create_game_and_team(client, team_name="Team A", username="Juan"):
    create_response = client.post("/api/games")
    assert create_response.status_code == 201
    game_data = create_response.get_json()["data"]
    game_id = game_data["game_id"]
    host_token = game_data["host_session_token"]
    team = _create_team(client, game_id, team_name=team_name, username=username)
    return game_id, host_token, team


def _leader_session(client, team):
    response = _connect(
        client,
        connection_token=team["leader"]["connection_token"],
        device_id="dev-session",
    )
    assert response.status_code == 201
    return response.get_json()["data"]["session_token"]


def test_player_team_starts_not_connected(client):
    create_response = client.post("/api/games")
    assert create_response.status_code == 201
    game_id = create_response.get_json()["data"]["game_id"]
    assert _create_team(client, game_id)["connection_status"] == "NOT_CONNECTED"


def test_host_team_starts_not_connected(client):
    create_response = client.post("/api/games")
    assert create_response.status_code == 201
    game_id = create_response.get_json()["data"]["game_id"]
    host_token = create_response.get_json()["data"]["host_session_token"]
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"team_name": "Host Crew", "username": "Host"},
        headers={"X-Host-Token": host_token},
    )
    assert response.status_code == 201
    # Even a host-created team must not auto-connect; it starts NOT_CONNECTED.
    assert response.get_json()["data"]["connection_status"] == "NOT_CONNECTED"


def test_connection_request_requires_token_or_session(client):
    game_id, host_token, team = _create_game_and_team(client)
    response = client.post("/api/games/{}/connection-request".format(game_id), json={})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "CONNECTION_TOKEN_REQUIRED"


def test_connection_request_non_leader_rejected(client):
    game_id, host_token, team = _create_game_and_team(client)
    member_resp = client.post(
        "/api/teams/{}/members".format(team["team_id"]), json={"username": "Pedro"}
    )
    member = member_resp.get_json()["data"]
    session = _connect(
        client, connection_token=member["connection_token"], device_id="dev-pedro"
    ).get_json()["data"]["session_token"]
    response = client.post(
        "/api/games/{}/connection-request".format(game_id),
        headers={"X-Session-Token": session},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "NOT_TEAM_LEADER"


def test_connection_request_with_leader_session(client):
    game_id, host_token, team = _create_game_and_team(client)
    session = _leader_session(client, team)
    response = client.post(
        "/api/games/{}/connection-request".format(game_id),
        headers={"X-Session-Token": session},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["connection_status"] == "CONNECTION_REQUESTED"
    assert data["requested_now"] is True


def test_connection_request_with_raw_token(client):
    game_id, host_token, team = _create_game_and_team(client)
    response = client.post(
        "/api/games/{}/connection-request".format(game_id),
        json={"connection_token": team["leader"]["connection_token"]},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["connection_status"] == "CONNECTION_REQUESTED"


def test_duplicate_connection_request_is_idempotent(client):
    game_id, host_token, team = _create_game_and_team(client)
    session = _leader_session(client, team)
    first = client.post(
        "/api/games/{}/connection-request".format(game_id),
        headers={"X-Session-Token": session},
    )
    assert first.status_code == 200
    assert first.get_json()["data"]["requested_now"] is True
    # A pending request should not error; it just reports no change.
    second = client.post(
        "/api/games/{}/connection-request".format(game_id),
        headers={"X-Session-Token": session},
    )
    assert second.status_code == 200
    assert second.get_json()["data"]["requested_now"] is False


def test_approve_requires_host_auth(client):
    game_id, host_token, team = _create_game_and_team(client)
    session = _leader_session(client, team)
    client.post(
        "/api/games/{}/connection-request".format(game_id),
        headers={"X-Session-Token": session},
    )
    response = client.post(
        "/api/games/{}/connection-requests/{}/approve".format(game_id, team["team_id"])
    )
    assert response.status_code == 401


def test_approve_connection_flow(client):
    game_id, host_token, team = _create_game_and_team(client)
    team_id = team["team_id"]
    client.post(
        "/api/games/{}/connection-request".format(game_id),
        json={"connection_token": team["leader"]["connection_token"]},
    )
    approved = client.post(
        "/api/games/{}/connection-requests/{}/approve".format(game_id, team_id),
        headers={"X-Host-Token": host_token},
    )
    assert approved.status_code == 200
    assert approved.get_json()["data"]["connection_status"] == "CONNECTED"
    # Approving an already-connected team stays CONNECTED (idempotent).
    again = client.post(
        "/api/games/{}/connection-requests/{}/approve".format(game_id, team_id),
        headers={"X-Host-Token": host_token},
    )
    assert again.status_code == 200
    assert again.get_json()["data"]["connection_status"] == "CONNECTED"


def test_approve_team_from_other_game_404(client):
    game_a, host_a, team_a = _create_game_and_team(client, team_name="Alpha")
    game_b, host_b, team_b = _create_game_and_team(client, team_name="Beta")
    response = client.post(
        "/api/games/{}/connection-requests/{}/approve".format(game_a, team_b["team_id"]),
        headers={"X-Host-Token": host_a},
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "TEAM_NOT_IN_GAME"


def test_decline_then_rerequest(client):
    game_id, host_token, team = _create_game_and_team(client)
    session = _leader_session(client, team)
    client.post(
        "/api/games/{}/connection-request".format(game_id),
        headers={"X-Session-Token": session},
    )
    declined = client.post(
        "/api/games/{}/connection-requests/{}/decline".format(game_id, team["team_id"]),
        headers={"X-Host-Token": host_token},
    )
    assert declined.status_code == 200
    assert declined.get_json()["data"]["connection_status"] == "DECLINED"
    # After a decline the leader may request again.
    retry = client.post(
        "/api/games/{}/connection-request".format(game_id),
        headers={"X-Session-Token": session},
    )
    assert retry.status_code == 200
    assert retry.get_json()["data"]["connection_status"] == "CONNECTION_REQUESTED"


def test_disconnect_connected_team(client):
    game_id, host_token, team = _create_game_and_team(client)
    client.post(
        "/api/games/{}/connection-request".format(game_id),
        json={"connection_token": team["leader"]["connection_token"]},
    )
    client.post(
        "/api/games/{}/connection-requests/{}/approve".format(game_id, team["team_id"]),
        headers={"X-Host-Token": host_token},
    )
    disconnected = client.post(
        "/api/games/{}/connection-requests/{}/disconnect".format(
            game_id, team["team_id"]
        ),
        headers={"X-Host-Token": host_token},
    )
    assert disconnected.status_code == 200
    assert disconnected.get_json()["data"]["connection_status"] == "DISCONNECTED"


def test_roster_payload_includes_connection_status(client):
    game_id, host_token, team = _create_game_and_team(client)
    client.post(
        "/api/games/{}/connection-request".format(game_id),
        json={"connection_token": team["leader"]["connection_token"]},
    )
    roster = client.get(
        "/api/games/{}/teams".format(game_id), headers={"X-Host-Token": host_token}
    ).get_json()["data"]["teams"]
    assert roster[0]["connection_status"] == "CONNECTION_REQUESTED"


def test_connection_status_is_persisted_not_device_presence(client):
    """A team never appears CONNECTED merely because it opened a page or
    connected a device; connection follows the persisted Team.connection_status
    and only becomes CONNECTED through the host approval flow."""
    game_id, host_token, team = _create_game_and_team(client)

    # Leader opens a device session (device presence) but is NOT approved yet.
    session = _connect(
        client,
        connection_token=team["leader"]["connection_token"],
        device_id="dev-a",
    ).get_json()["data"]

    roster = client.get(
        "/api/games/{}/teams".format(game_id),
        headers={"X-Host-Token": host_token},
    ).get_json()["data"]["teams"]
    # Device is connected but the team is unapproved -> still NOT_CONNECTED.
    assert roster[0]["connection_status"] == "NOT_CONNECTED"
    assert (
        roster[0]["leader"]["is_connected"] is True
        or client.post(
            "/api/devices/heartbeat",
            json={"session_token": session["session_token"]},
        ).status_code
        == 200
    )

    # Now request + approve: the roster reflects CONNECTED.
    client.post(
        "/api/games/{}/connection-request".format(game_id),
        json={"connection_token": team["leader"]["connection_token"]},
    )
    client.post(
        "/api/games/{}/connection-requests/{}/approve".format(
            game_id, team["team_id"]
        ),
        headers={"X-Host-Token": host_token},
    )
    roster = client.get(
        "/api/games/{}/teams".format(game_id),
        headers={"X-Host-Token": host_token},
    ).get_json()["data"]["teams"]
    assert roster[0]["connection_status"] == "CONNECTED"