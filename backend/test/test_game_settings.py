import pytest

from app import create_app
from app.extensions import db
from app.models import DeviceSession, Game, GameSettings, Team, TeamMember
from app.services import team_service, word_service

HOST_TOKEN_HEADER = "X-Host-Token"
SESSION_TOKEN_HEADER = "X-Session-Token"


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


def _get_settings(client, game_id):
    response = client.get("/api/games/{}/settings".format(game_id))
    assert response.status_code == 200
    return response.get_json()["data"]


def _put_settings(client, game_id, host_token, payload):
    return client.put(
        "/api/games/{}/settings".format(game_id),
        json=payload,
        headers={HOST_TOKEN_HEADER: host_token},
    )


def _create_team(client, game_id, team_name="Team A", username="Juan"):
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"team_name": team_name, "username": username},
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


def _create_category(client, game_id, host_token, name="Animals"):
    response = client.post(
        "/api/games/{}/categories".format(game_id),
        json={"name": name},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 201
    return response.get_json()["data"]["category_id"]


def _submit_word(client, game_id, category_id, team_id, word_text, session=None):
    headers = {}
    if session is not None:
        headers[SESSION_TOKEN_HEADER] = session
    return client.post(
        "/api/games/{}/words".format(game_id),
        json={
            "team_id": team_id,
            "category_id": category_id,
            "word_text": word_text,
        },
        headers=headers,
    )


def _start(client, game_id, host_token):
    response = client.post(
        "/api/games/{}/start".format(game_id),
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Settings lifecycle: defaults, create-on-game, GET/PUT, validation
# ---------------------------------------------------------------------------


def test_game_creation_creates_settings_row(app, client):
    game_id, host = _create_game(client)
    payload = _get_settings(client, game_id)
    assert payload["game_id"] == game_id
    assert payload["max_words_per_category"] == 5
    assert payload["penalty_seconds"] == 3
    assert payload["allow_new_teams"] is True
    assert payload["auto_approve_connections"] is False
    assert payload["max_teams"] == 8
    assert payload["max_members"] == 6
    for flag in (
        "show_player_names",
        "show_role_labels",
        "show_scores",
        "show_qr_code",
        "show_round_category",
    ):
        assert payload[flag] is True
    with app.app_context():
        settings = db.session.get(GameSettings, game_id)
        assert settings is not None


def test_legacy_game_without_settings_row_inferred_via_ensure(app, client):
    game_id, host = _create_game(client)
    with app.app_context():
        game = db.session.get(Game, game_id)
        db.session.delete(game.settings)
        db.session.commit()
        assert db.session.get(GameSettings, game_id) is None
    payload = _get_settings(client, game_id)
    assert payload["max_words_per_category"] == 5
    with app.app_context():
        assert db.session.get(GameSettings, game_id) is not None


def test_settings_get_is_anonymous_and_has_no_secrets(client):
    game_id, host = _create_game(client)
    response = client.get("/api/games/{}/settings".format(game_id))
    assert response.status_code == 200
    body = response.get_json()["data"]
    assert "host_session_token" not in body


def test_settings_put_requires_host(client):
    game_id, host = _create_game(client)
    response = client.put(
        "/api/games/{}/settings".format(game_id), json={"penalty_seconds": 10}
    )
    assert response.status_code == 401


def test_settings_partial_update(app, client):
    game_id, host = _create_game(client)
    response = _put_settings(client, game_id, host, {"penalty_seconds": 10})
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["penalty_seconds"] == 10
    assert payload["max_words_per_category"] == 5
    # untouched values persist
    assert _get_settings(client, game_id)["penalty_seconds"] == 10


def test_settings_invalid_enum_rejected(app, client):
    game_id, host = _create_game(client)
    for bad in (7, 2, "x"):
        response = _put_settings(client, game_id, host, {"penalty_seconds": bad})
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "SETTINGS_INVALID"


def test_settings_unknown_field_rejected(app, client):
    game_id, host = _create_game(client)
    response = _put_settings(client, game_id, host, {"not_a_setting": True})
    assert response.status_code == 400


def test_settings_invalid_boolean_rejected(app, client):
    game_id, host = _create_game(client)
    response = _put_settings(client, game_id, host, {"show_scores": "banana"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Locking: caps freeze once game leaves LOBBY/SETUP
# ---------------------------------------------------------------------------


def test_caps_lock_after_game_starts(client):
    game_id, host = _create_game(client)
    _start(client, game_id, host)
    for field in ("max_words_per_category", "max_teams", "max_members"):
        response = _put_settings(client, game_id, host, {field: 10})
        assert response.status_code == 409
        assert response.get_json()["error"]["code"] == "SETTINGS_LOCKED"


def test_live_settings_editable_after_game_starts(client):
    game_id, host = _create_game(client)
    _start(client, game_id, host)
    updates = (
        {"penalty_seconds": 10},
        {"allow_new_teams": False},
        {"auto_approve_connections": True},
        {"show_player_names": False},
        {"show_scores": False},
    )
    for payload in updates:
        response = _put_settings(client, game_id, host, payload)
        assert response.status_code == 200, payload


# ---------------------------------------------------------------------------
# Team gates: allow_new_teams / max_teams
# ---------------------------------------------------------------------------


def test_allow_new_teams_off_blocks_creation(client):
    game_id, host = _create_game(client)
    assert _put_settings(client, game_id, host, {"allow_new_teams": False}).status_code == 200
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"team_name": "Team B", "username": "Maria"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "ALLOW_NEW_TEAMS_DISABLED"


def test_max_teams_blocks_creation(client):
    game_id, host = _create_game(client)
    assert _put_settings(client, game_id, host, {"max_teams": 4}).status_code == 200
    for i in range(4):
        _create_team(client, game_id, "Team {}".format(i), "User {}".format(i))
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"team_name": "Overflow", "username": "Cap"},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "TEAM_LIMIT_EXCEEDED"


# ---------------------------------------------------------------------------
# Member cap: max_members
# ---------------------------------------------------------------------------


def test_max_members_enforced_on_add(app, client):
    game_id, host = _create_game(client)
    _put_settings(client, game_id, host, {"max_members": 4})
    team = _create_team(client, game_id)
    for i in range(3):
        response = client.post(
            "/api/teams/{}/members".format(team["team_id"]),
            json={"username": "Member {}".format(i)},
        )
        assert response.status_code == 201
    response = client.post(
        "/api/teams/{}/members".format(team["team_id"]),
        json={"username": "Too Many"},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "MEMBER_LIMIT_EXCEEDED"


# ---------------------------------------------------------------------------
# Auto-approve connections
# ---------------------------------------------------------------------------


def test_request_connection_auto_approves_with_setting(client):
    game_id, host = _create_game(client)
    _put_settings(client, game_id, host, {"auto_approve_connections": True})
    team = _create_team(client, game_id)
    session = _leader_session(client, team)
    response = client.post(
        "/api/games/{}/connection-request".format(game_id),
        headers={SESSION_TOKEN_HEADER: session},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["connection_status"] == "CONNECTED"
    assert data["requested_now"] is True


def test_auto_approve_on_approves_already_pending(app, client):
    game_id, host = _create_game(client)
    team = _create_team(client, game_id)
    session = _leader_session(client, team)
    response = client.post(
        "/api/games/{}/connection-request".format(game_id),
        headers={SESSION_TOKEN_HEADER: session},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["connection_status"] == "CONNECTION_REQUESTED"
    response = _put_settings(client, game_id, host, {"auto_approve_connections": True})
    assert response.status_code == 200
    status = response.get_json()["data"]["auto_approve_connections"]
    assert status is True
    with app.app_context():
        team_row = db.session.get(Team, team["team_id"])
        assert team_row.connection_status == Team.CONNECTION_CONNECTED


def test_auto_approve_off_still_requires_approval(client):
    game_id, host = _create_game(client)
    team = _create_team(client, game_id)
    session = _leader_session(client, team)
    response = client.post(
        "/api/games/{}/connection-request".format(game_id),
        headers={SESSION_TOKEN_HEADER: session},
    )
    assert response.get_json()["data"]["connection_status"] == "CONNECTION_REQUESTED"


# ---------------------------------------------------------------------------
# Per-category word cap
# ---------------------------------------------------------------------------


def _setup_word_submit(app, client):
    game_id, host = _create_game(client)
    _put_settings(client, game_id, host, {"max_words_per_category": 3})
    team = _create_team(client, game_id)
    team_id = team["team_id"]
    with app.app_context():
        team_obj = db.session.get(Team, team_id)
        # Team must be CONNECTED for word submission to be valid gameplay state.
        team_obj.connection_status = Team.CONNECTION_CONNECTED
        db.session.commit()
        member = team_obj.members[0]
        session = DeviceSession(
            game_id=game_id,
            team_id=team_id,
            member_id=member.id,
            device_id="dev-submit",
            session_token="sess-submit",
            device_type="TEAM_MEMBER",
        )
        db.session.add(session)
        member.is_connected = True
        db.session.commit()
    category_id = _create_category(client, game_id, host, "Pets")
    return game_id, team_id, category_id, host, "sess-submit"


def test_word_cap_uses_configured_value(app, client):
    game_id, team_id, category_id, host, session = _setup_word_submit(app, client)
    for w in ("aso", "pusa", "ibon"):
        response = _submit_word(client, game_id, category_id, team_id, w, session=session)
        assert response.status_code == 201, response.get_json()
    response = _submit_word(client, game_id, category_id, team_id, "isda", session=session)
    assert response.status_code == 409
    body = response.get_json()
    assert body["error"]["code"] == "WORD_LIMIT_EXCEEDED"
    assert "3" in body["error"]["message"]


def test_word_cap_is_per_category(app, client):
    game_id, team_id, category_id, host, session = _setup_word_submit(app, client)
    for w in ("aso", "pusa", "ibon"):
        assert _submit_word(
            client, game_id, category_id, team_id, w, session=session
        ).status_code == 201
    other_cat = _create_category(client, game_id, host, "Food")
    assert _submit_word(
        client, game_id, other_cat, team_id, "kanin", session=session
    ).status_code == 201