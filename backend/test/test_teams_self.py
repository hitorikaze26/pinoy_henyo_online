import pytest

from app import create_app
from app.extensions import db

SESSION_TOKEN_HEADER = "X-Session-Token"
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
    data = response.get_json()["data"]
    return data["game_id"], data["host_session_token"]


def _create_team(client, game_id, team_name="Team Henyo", username="Juan"):
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"username": username, "team_name": team_name},
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _add_member(client, team_id, username="Pedro"):
    response = client.post(
        "/api/teams/{}/members".format(team_id), json={"username": username}
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _connect(client, connection_token, device_id="dev-1"):
    response = client.post(
        "/api/devices/connect",
        json={"connection_token": connection_token, "device_id": device_id},
    )
    assert response.status_code == 201
    return response.get_json()["data"]["session_token"]


# ---------------------------------------------------------------------------
# GET /api/teams/<team_id>  (own-team roster via session, or host)
# ---------------------------------------------------------------------------


def test_get_own_team_roster_via_session(client):
    game_id, _ = _create_game(client)
    team_a = _create_team(client, game_id, team_name="Team Henyo", username="Juan")
    member = _add_member(client, team_a["team_id"], username="Pedro")
    session = _connect(client, team_a["leader"]["connection_token"], "dev-a")

    response = client.get(
        "/api/teams/{}".format(team_a["team_id"]),
        headers={SESSION_TOKEN_HEADER: session},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["team_name"] == "Team Henyo"
    assert data["team_code"] == team_a["team_code"]
    assert data["my_member_id"] == team_a["leader"]["member_id"]
    names = {m["username"] for m in data["members"]}
    assert names == {"Juan", "Pedro"}


def test_get_team_roster_from_other_team_rejected(client):
    game_id, _ = _create_game(client)
    team_a = _create_team(client, game_id, team_name="Team A", username="Juan")
    team_b = _create_team(client, game_id, team_name="Team B", username="Kris")
    session_b = _connect(client, team_b["leader"]["connection_token"], "dev-b")

    response = client.get(
        "/api/teams/{}".format(team_a["team_id"]),
        headers={SESSION_TOKEN_HEADER: session_b},
    )
    assert response.status_code == 401


def test_get_own_team_roster_by_host(client):
    game_id, host_token = _create_game(client)
    team_a = _create_team(client, game_id)
    response = client.get(
        "/api/teams/{}".format(team_a["team_id"]),
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["my_member_id"] is None


def test_get_team_roster_requires_auth(client):
    game_id, _ = _create_game(client)
    team_a = _create_team(client, game_id)
    assert client.get("/api/teams/{}".format(team_a["team_id"])).status_code == 401


# ---------------------------------------------------------------------------
# PATCH /api/teams/<team_id>  (team name)
# ---------------------------------------------------------------------------


def test_team_leader_updates_team_name(client):
    game_id, _ = _create_game(client)
    team_a = _create_team(client, game_id, team_name="Team Henyo", username="Juan")
    session = _connect(client, team_a["leader"]["connection_token"], "dev-a")

    response = client.patch(
        "/api/teams/{}".format(team_a["team_id"]),
        json={"team_name": "Team Henyo 2.0"},
        headers={SESSION_TOKEN_HEADER: session},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["team_name"] == "Team Henyo 2.0"


def test_team_member_cannot_update_team_name(client):
    game_id, _ = _create_game(client)
    team_a = _create_team(client, game_id, team_name="Team Henyo", username="Juan")
    member = _add_member(client, team_a["team_id"], username="Pedro")
    session = _connect(client, member["connection_token"], "dev-m")

    response = client.patch(
        "/api/teams/{}".format(team_a["team_id"]),
        json={"team_name": "Hacked"},
        headers={SESSION_TOKEN_HEADER: session},
    )
    assert response.status_code == 401


def test_host_updates_team_name(client):
    game_id, host_token = _create_game(client)
    team_a = _create_team(client, game_id, team_name="Team Henyo")
    response = client.patch(
        "/api/teams/{}".format(team_a["team_id"]),
        json={"team_name": "Renamed"},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 200


def test_team_name_validation(client):
    game_id, _ = _create_game(client)
    team_a = _create_team(client, game_id)
    session = _connect(client, team_a["leader"]["connection_token"], "dev-a")
    assert (
        client.patch(
            "/api/teams/{}".format(team_a["team_id"]),
            json={"team_name": ""},
            headers={SESSION_TOKEN_HEADER: session},
        ).status_code
        == 400
    )


# ---------------------------------------------------------------------------
# PATCH /api/members/<member_id>  (username)
# ---------------------------------------------------------------------------


def test_member_updates_own_username(client):
    game_id, _ = _create_game(client)
    team_a = _create_team(client, game_id, team_name="Team Henyo", username="Juan")
    session = _connect(client, team_a["leader"]["connection_token"], "dev-a")
    member_id = team_a["leader"]["member_id"]

    response = client.patch(
        "/api/members/{}".format(member_id),
        json={"username": "Juan Dela Cruz"},
        headers={SESSION_TOKEN_HEADER: session},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["username"] == "Juan Dela Cruz"


def test_member_cannot_update_another_member(client):
    game_id, _ = _create_game(client)
    team_a = _create_team(client, game_id, team_name="Team Henyo", username="Juan")
    member = _add_member(client, team_a["team_id"], username="Pedro")
    other = _add_member(client, team_a["team_id"], username="Ana")
    session_pedro = _connect(client, member["connection_token"], "dev-p")

    response = client.patch(
        "/api/members/{}".format(other["member_id"]),
        json={"username": "Hacked"},
        headers={SESSION_TOKEN_HEADER: session_pedro},
    )
    assert response.status_code == 401


def test_host_updates_member_username(client):
    game_id, host_token = _create_game(client)
    team_a = _create_team(client, game_id, team_name="Team Henyo", username="Juan")
    response = client.patch(
        "/api/members/{}".format(team_a["leader"]["member_id"]),
        json={"username": "Renamed"},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["username"] == "Renamed"


# ---------------------------------------------------------------------------
# GET /api/games/<game_id>/words/my  (own team's words)
# ---------------------------------------------------------------------------


def test_my_words_returns_own_team_words(client, app):
    game_id, host_token = _create_game(client)
    team_a = _create_team(client, game_id, team_name="Team A", username="Juan")
    team_b = _create_team(client, game_id, team_name="Team B", username="Kris")

    cat_resp = client.post(
        "/api/games/{}/categories".format(game_id),
        json={"name": "Food"},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    category_id = cat_resp.get_json()["data"]["category_id"]

    # Team A submits words directly (host path).
    for w in ("Adobo", "Lechon"):
        client.post(
            "/api/games/{}/words".format(game_id),
            json={"category_id": category_id, "word_text": w, "team_id": team_a["team_id"]},
            headers={HOST_TOKEN_HEADER: host_token},
        )
    client.post(
        "/api/games/{}/words".format(game_id),
        json={"category_id": category_id, "word_text": "Sisig", "team_id": team_b["team_id"]},
        headers={HOST_TOKEN_HEADER: host_token},
    )

    session_a = _connect(client, team_a["leader"]["connection_token"], "dev-a")
    response = client.get(
        "/api/games/{}/words/my".format(game_id),
        headers={SESSION_TOKEN_HEADER: session_a},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["team_id"] == team_a["team_id"]
    words = [w["word_text"] for w in data["words"]]
    assert sorted(words) == ["Adobo", "Lechon"]
    assert "Sisig" not in words


def test_my_words_requires_session(client, app):
    game_id, host_token = _create_game(client)
    team_a = _create_team(client, game_id)
    cat_resp = client.post(
        "/api/games/{}/categories".format(game_id),
        json={"name": "Food"},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    category_id = cat_resp.get_json()["data"]["category_id"]
    client.post(
        "/api/games/{}/words".format(game_id),
        json={"category_id": category_id, "word_text": "Adobo", "team_id": team_a["team_id"]},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert (
        client.get("/api/games/{}/words/my".format(game_id)).status_code == 401
    )
