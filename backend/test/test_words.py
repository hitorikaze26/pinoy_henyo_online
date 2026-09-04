import pytest

from app import create_app
from app.extensions import db
from app.models import DeviceSession, Team, Word
from app.services import word_service

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


def _create_team(app, game_id, code, name="Team A"):
    """Create a team plus a leader member and return (team_id, session_token)."""
    from app.models import TeamMember

    with app.app_context():
        team = Team(game_id=game_id, team_code=code, team_name=name)
        db.session.add(team)
        db.session.flush()
        leader = TeamMember(
            team_id=team.id,
            username=name,
            device_role=TeamMember.DEVICE_ROLE_TEAM_LEADER,
            connection_token="ct-{}-{}".format(game_id, code),
        )
        db.session.add(leader)
        db.session.flush()
        team.leader_member_id = leader.id
        session = DeviceSession(
            game_id=game_id,
            team_id=team.id,
            member_id=leader.id,
            device_id="dev-{}-{}".format(game_id, code),
            session_token="sess-{}-{}".format(game_id, code),
            device_type="TEAM_LEADER",
        )
        db.session.add(session)
        leader.is_connected = True
        db.session.commit()
        return team.id, session.session_token


def _create_category(client, game_id, host_token, name):
    response = client.post(
        "/api/games/{}/categories".format(game_id),
        json={"name": name},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 201
    return response.get_json()["data"]["category_id"]


def _team_id(team):
    return team if isinstance(team, tuple) else (team, None)


def _submit(client, game_id, category_id, team, word_text, token=None):
    team_id, session_token = _team_id(team)
    headers = {}
    if token is not None:
        headers[HOST_TOKEN_HEADER] = token
    elif session_token is not None:
        headers[SESSION_TOKEN_HEADER] = session_token
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


def _ensure_active_wording(client, game_id, category_id, team_id, words):
    for word in words:
        assert _submit(client, game_id, category_id, team_id, word).status_code == 201


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def test_create_category(client):
    game_id, host_token = _create_game(client)
    response = client.post(
        "/api/games/{}/categories".format(game_id),
        json={"name": "  Food  "},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["name"] == "Food"
    assert data["game_id"] == game_id


def test_create_category_requires_host(client):
    game_id, host_token = _create_game(client)
    url = "/api/games/{}/categories".format(game_id)
    assert client.post(url, json={"name": "Food"}).status_code == 401
    assert (
        client.post(
            url,
            json={"name": "Food"},
            headers={HOST_TOKEN_HEADER: "wrong-token"},
        ).status_code
        == 401
    )


def test_create_category_invalid_names(client):
    game_id, host_token = _create_game(client)
    url = "/api/games/{}/categories".format(game_id)
    for bad in (None, "", "   ", "###", "X" * 51, "???$$$"):
        response = client.post(
            url, json={"name": bad}, headers={HOST_TOKEN_HEADER: host_token}
        )
        assert response.status_code == 400
        assert (
            response.get_json()["error"]["code"] == "CATEGORY_NAME_INVALID"
        )


def test_create_category_duplicate_case_insensitive(client):
    game_id, host_token = _create_game(client)
    url = "/api/games/{}/categories".format(game_id)
    assert (
        client.post(
            url, json={"name": "Food"}, headers={HOST_TOKEN_HEADER: host_token}
        ).status_code
        == 201
    )
    response = client.post(
        url, json={"name": "food"}, headers={HOST_TOKEN_HEADER: host_token}
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "DUPLICATE_CATEGORY"


def test_list_categories_without_auth(client):
    game_id, host_token = _create_game(client)
    _create_category(client, game_id, host_token, "Food")
    _create_category(client, game_id, host_token, "Animals")
    response = client.get("/api/games/{}/categories".format(game_id))
    assert response.status_code == 200
    categories = response.get_json()["data"]["categories"]
    assert len(categories) == 2
    for category in categories:
        assert category["word_count"] == 0
        assert category["ready"] is False


def test_patch_category(client):
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")
    response = client.patch(
        "/api/categories/{}".format(category_id),
        json={"name": "Drinks"},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["name"] == "Drinks"

    other_id = _create_category(client, game_id, host_token, "Animals")
    dup = client.patch(
        "/api/categories/{}".format(other_id),
        json={"name": "drinks"},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert dup.status_code == 409
    assert dup.get_json()["error"]["code"] == "DUPLICATE_CATEGORY"


def test_patch_category_requires_host(client):
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")
    assert (
        client.patch(
            "/api/categories/{}".format(category_id), json={"name": "X"}
        ).status_code
        == 401
    )


def test_delete_category_cascades_words(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    response = _submit(
        client, game_id, category_id, team_id, "Adobo", token=host_token
    )
    word_id = response.get_json()["data"]["word_id"]

    response = client.delete(
        "/api/categories/{}".format(category_id),
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 200
    gone = client.patch(
        "/api/words/{}".format(word_id),
        json={"word_text": "X"},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert gone.status_code == 404
    listed = client.get("/api/games/{}/categories".format(game_id))
    assert listed.get_json()["data"]["categories"] == []


def test_create_category_game_not_found(client):
    response = client.post(
        "/api/games/999999/categories",
        json={"name": "Food"},
        headers={HOST_TOKEN_HEADER: "token"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Team word submission & validation
# ---------------------------------------------------------------------------


def test_submit_word_normalizes(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")

    response = _submit(client, game_id, category_id, team_id, "  Adobo ")
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["word_text"] == "Adobo"
    assert data["normalized_word"] == "adobo"
    assert data["status"] == Word.STATUS_AVAILABLE


def test_duplicate_word_detection(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")

    assert _submit(client, game_id, category_id, team_id, "Adobo").status_code == 201
    response = _submit(client, game_id, category_id, team_id, " ADOBO ")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "DUPLICATE_WORD"


def test_same_word_allowed_in_different_category(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    food = _create_category(client, game_id, host_token, "Food")
    animals = _create_category(client, game_id, host_token, "Animals")
    assert _submit(client, game_id, food, team_id, "Tiger").status_code == 201
    assert _submit(client, game_id, animals, team_id, "tiger").status_code == 201


def test_max_five_words_per_team_category(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    words = ["One", "Two", "Three", "Four", "Five"]
    _ensure_active_wording(client, game_id, category_id, team_id, words)
    response = _submit(client, game_id, category_id, team_id, "Six")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "WORD_LIMIT_EXCEEDED"


def test_word_limit_is_per_team_and_category(client, app):
    game_id, host_token = _create_game(client)
    team_a = _create_team(app, game_id, "A1")
    team_b = _create_team(app, game_id, "B1", name="Team B")
    food = _create_category(client, game_id, host_token, "Food")
    animals = _create_category(client, game_id, host_token, "Animals")

    _ensure_active_wording(
        client, game_id, food, team_a, ["One", "Two", "Three", "Four", "Five"]
    )
    assert _submit(client, game_id, food, team_b, "Six").status_code == 201
    assert _submit(client, game_id, animals, team_a, "Six").status_code == 201


def test_category_not_ready_until_three_words(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")

    _submit(client, game_id, category_id, team_id, "One")
    _submit(client, game_id, category_id, team_id, "Two")
    body = client.get("/api/games/{}/categories".format(game_id)).get_json()["data"]
    category = [c for c in body["categories"] if c["category_id"] == category_id][0]
    assert category["word_count"] == 2
    assert category["ready"] is False

    _submit(client, game_id, category_id, team_id, "Three")
    body = client.get("/api/games/{}/categories".format(game_id)).get_json()["data"]
    category = [c for c in body["categories"] if c["category_id"] == category_id][0]
    assert category["word_count"] == 3
    assert category["ready"] is True


def test_english_and_filipino_words_allowed(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    english = _create_category(client, game_id, host_token, "Nature")
    filipino = _create_category(client, game_id, host_token, "Pagkain")

    assert _submit(client, game_id, english, team_id, "Butterfly").status_code == 201
    assert _submit(client, game_id, filipino, team_id, "Pera").status_code == 201


def test_submit_word_validation_errors(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")

    missing_cat = _submit(
        client, game_id, None, team_id, "Adobo"
    )
    assert missing_cat.status_code == 400
    assert missing_cat.get_json()["error"]["code"] == "CATEGORY_REQUIRED"

    blank = _submit(client, game_id, category_id, team_id, "   ")
    assert blank.status_code == 400
    assert blank.get_json()["error"]["code"] == "WORD_TEXT_INVALID"

    no_team = client.post(
        "/api/games/{}/words".format(game_id),
        json={"category_id": category_id, "word_text": "Adobo"},
    )
    assert no_team.status_code == 401
    assert no_team.get_json()["error"]["code"] == "SESSION_REQUIRED"


def test_submit_word_team_not_in_game(client, app):
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")
    other_game_id, _ = _create_game(client)
    outsider_team = _create_team(app, other_game_id, "Z9")

    response = _submit(
        client, game_id, category_id, outsider_team, "Adobo", token=host_token
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "TEAM_NOT_IN_GAME"


def test_submit_word_category_not_in_game(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    other_game_id, other_token = _create_game(client)
    outsider_category = _create_category(
        client, other_game_id, other_token, "Food"
    )

    response = _submit(client, game_id, outsider_category, team_id, "Adobo")
    assert response.status_code == 400
    assert (
        response.get_json()["error"]["code"] == "CATEGORY_NOT_IN_GAME"
    )


def test_submit_word_requires_game(client):
    response = _submit(client, 999999, 1, 1, "Adobo")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Session-based team resolution
# ---------------------------------------------------------------------------


def _make_session(app, game_id, team_id, token="sess-token-1", device_id="dev-1"):
    with app.app_context():
        session = DeviceSession(
            game_id=game_id,
            team_id=team_id,
            device_id=device_id,
            session_token=token,
            device_type="TEAM_MEMBER",
        )
        db.session.add(session)
        db.session.commit()
        return session.id


def test_session_token_resolves_submitting_team(client, app):
    game_id, host_token = _create_game(client)
    team_a, _ = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    _make_session(app, game_id, team_a, token="sess-team-a")

    response = client.post(
        "/api/games/{}/words".format(game_id),
        json={"category_id": category_id, "word_text": "Adobo"},
        headers={SESSION_TOKEN_HEADER: "sess-team-a"},
    )
    assert response.status_code == 201
    assert response.get_json()["data"]["submitted_by_team_id"] == team_a


def test_invalid_session_token_rejected(client, app):
    game_id, host_token = _create_game(client)
    team_a, _ = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    _make_session(app, game_id, team_a, token="sess-team-a")

    response = client.post(
        "/api/games/{}/words".format(game_id),
        json={"category_id": category_id, "word_text": "Adobo"},
        headers={SESSION_TOKEN_HEADER: "bogus"},
    )
    assert response.status_code == 401


def test_session_team_mismatch_rejected(client, app):
    game_id, host_token = _create_game(client)
    team_a, _ = _create_team(app, game_id, "A1")
    team_b, _ = _create_team(app, game_id, "B1", name="Team B")
    category_id = _create_category(client, game_id, host_token, "Food")
    _make_session(app, game_id, team_a, token="sess-team-a")

    response = client.post(
        "/api/games/{}/words".format(game_id),
        json={
            "team_id": team_b,
            "category_id": category_id,
            "word_text": "Adobo",
        },
        headers={SESSION_TOKEN_HEADER: "sess-team-a"},
    )
    assert response.status_code == 409
    assert (
        response.get_json()["error"]["code"] == "SESSION_TEAM_MISMATCH"
    )


# ---------------------------------------------------------------------------
# Host word management
# ---------------------------------------------------------------------------


def test_host_adds_word(client, app):
    game_id, host_token = _create_game(client)
    team_id, _ = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")

    response = _submit(
        client, game_id, category_id, team_id, "Adobo", token=host_token
    )
    assert response.status_code == 201
    assert response.get_json()["data"]["submitted_by_team_id"] == team_id


def test_host_word_management_view_list(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1", name="Discovers")
    category_id = _create_category(client, game_id, host_token, "Food")
    _submit(client, game_id, category_id, team_id, "Adobo")

    response = client.get(
        "/api/games/{}/words".format(game_id),
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 200
    words = response.get_json()["data"]["words"]
    assert len(words) == 1
    assert words[0]["category_name"] == "Food"
    assert words[0]["team_name"] == "Discovers"


def test_list_words_requires_host(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    _submit(client, game_id, category_id, team_id, "Adobo")

    assert (
        client.get("/api/games/{}/words".format(game_id)).status_code == 401
    )


def test_host_edits_word(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    word_id = _submit(client, game_id, category_id, team_id, "Adobo").get_json()[
        "data"
    ]["word_id"]

    response = client.patch(
        "/api/words/{}".format(word_id),
        json={"word_text": "Sinigang"},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["word_text"] == "Sinigang"
    assert data["normalized_word"] == "sinigang"


def test_host_disables_word(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    _ensure_active_wording(
        client, game_id, category_id, team_id, ["One", "Two", "Three"]
    )
    with app.app_context():
        words = (
            db.session.query(Word)
            .filter_by(category_id=category_id)
            .order_by(Word.id)
            .all()
        )
    target = words[0]

    response = client.post(
        "/api/words/{}/disable".format(target.id),
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == Word.STATUS_DISABLED

    body = client.get("/api/games/{}/categories".format(game_id)).get_json()["data"]
    category = [c for c in body["categories"] if c["category_id"] == category_id][0]
    assert category["word_count"] == 2
    assert category["ready"] is False


def test_host_cannot_add_word_after_game_locked(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    _start(client, game_id, host_token)

    added = _submit(
        client, game_id, category_id, team_id, "Adobo", token=host_token
    )
    assert added.status_code == 409
    assert added.get_json()["error"]["code"] == "WORD_LOCKED"


# ---------------------------------------------------------------------------
# Word locking
# ---------------------------------------------------------------------------


def test_word_locked_after_game_starts_for_players(client, app):
    game_id, host_token = _create_game(client)
    team_id = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    _start(client, game_id, host_token)

    response = _submit(client, game_id, category_id, team_id, "Adobo")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "WORD_LOCKED"


def test_edit_word_owner_and_other_team(client, app):
    game_id, host_token = _create_game(client)
    team_a, sess_a = _create_team(app, game_id, "A1")
    team_b, sess_b = _create_team(app, game_id, "B1", name="Team B")
    category_id = _create_category(client, game_id, host_token, "Food")
    word_id = _submit(
        client, game_id, category_id, (team_a, sess_a), "Adobo"
    ).get_json()["data"]["word_id"]

    ok = client.patch(
        "/api/words/{}".format(word_id),
        json={"team_id": team_a, "word_text": "Sinigang"},
        headers={SESSION_TOKEN_HEADER: sess_a},
    )
    assert ok.status_code == 200
    assert ok.get_json()["data"]["word_text"] == "Sinigang"

    denied = client.patch(
        "/api/words/{}".format(word_id),
        json={"team_id": team_b, "word_text": "Lechon"},
        headers={SESSION_TOKEN_HEADER: sess_b},
    )
    assert denied.status_code == 409
    assert denied.get_json()["error"]["code"] == "WORD_OWNERSHIP"


def test_player_and_host_edit_locked_after_start(client, app):
    game_id, host_token = _create_game(client)
    team_id, sess = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    word_id = _submit(
        client, game_id, category_id, (team_id, sess), "Adobo"
    ).get_json()["data"]["word_id"]
    _start(client, game_id, host_token)

    denied = client.patch(
        "/api/words/{}".format(word_id),
        json={"team_id": team_id, "word_text": "Sinigang"},
        headers={SESSION_TOKEN_HEADER: sess},
    )
    assert denied.status_code == 409
    assert denied.get_json()["error"]["code"] == "WORD_LOCKED"

    host_denied = client.patch(
        "/api/words/{}".format(word_id),
        json={"word_text": "Sinigang"},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert host_denied.status_code == 409
    assert host_denied.get_json()["error"]["code"] == "WORD_LOCKED"


def test_delete_word_owner(client, app):
    game_id, host_token = _create_game(client)
    team_id, sess = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    word_id = _submit(
        client, game_id, category_id, (team_id, sess), "Adobo"
    ).get_json()["data"]["word_id"]

    response = client.delete(
        "/api/words/{}".format(word_id),
        json={"team_id": team_id},
        headers={SESSION_TOKEN_HEADER: sess},
    )
    assert response.status_code == 200

    gone = client.patch(
        "/api/words/{}".format(word_id),
        json={"team_id": team_id, "word_text": "X"},
        headers={SESSION_TOKEN_HEADER: sess},
    )
    assert gone.status_code == 404


def test_word_not_found(client):
    assert (
        client.patch(
            "/api/words/999999", json={"word_text": "X"}
        ).status_code
        == 404
    )
    assert (
        client.post("/api/words/999999/disable").status_code == 404
    )


# ---------------------------------------------------------------------------
# Own-team word restriction (game rule for assignment)
# ---------------------------------------------------------------------------


def test_own_team_word_restriction(app):
    with app.app_context():
        team_a = Team(game_id=1, team_code="A1", team_name="Team A")
        team_b = Team(game_id=1, team_code="B1", team_name="Team B")
        db.session.add_all([team_a, team_b])
        db.session.flush()
        word = Word(
            game_id=1,
            category_id=1,
            submitted_by_team_id=team_a.id,
            word_text="Adobo",
            normalized_word="adobo",
        )
        db.session.add(word)
        db.session.flush()

        assert word_service.word_can_be_received(word, team_b.id) is True
        assert word_service.word_can_be_received(word, team_a.id) is False
        assert word_service.word_can_be_received(word, None) is True

        assert word_service.assert_word_assignable(word, team_b.id) is True
        with pytest.raises(word_service.GameRuleError):
            word_service.assert_word_assignable(word, team_a.id)
        db.session.rollback()