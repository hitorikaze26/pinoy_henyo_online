import pytest

from app import create_app
from app.extensions import db
from app.models import DeviceSession, Team, Word, WordChangeRequest

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


def _submit(client, game_id, category_id, team_id, token, word_text):
    response = client.post(
        "/api/games/{}/words".format(game_id),
        json={
            "team_id": team_id,
            "category_id": category_id,
            "word_text": word_text,
        },
        headers={SESSION_TOKEN_HEADER: token},
    )
    assert response.status_code == 201
    return response.get_json()["data"]["word_id"]


def _list_host(client, game_id, host_token):
    return client.get(
        "/api/games/{}/word-change-requests".format(game_id),
        headers={HOST_TOKEN_HEADER: host_token},
    )


def _pending_for(client, game_id, session_token):
    return client.get(
        "/api/games/{}/word-change-requests".format(game_id),
        headers={SESSION_TOKEN_HEADER: session_token},
    )


def _create_request(client, game_id, host_token, team_id, word_id, comment):
    return client.post(
        "/api/games/{}/word-change-requests".format(game_id),
        json={
            "team_id": team_id,
            "word_id": word_id,
            "comment": comment,
        },
        headers={HOST_TOKEN_HEADER: host_token},
    )


def _resolve(client, request_id, session_token, word_text):
    return client.post(
        "/api/word-change-requests/{}/resolve".format(request_id),
        json={"word_text": word_text},
        headers={SESSION_TOKEN_HEADER: session_token},
    )


def _cancel(client, request_id, host_token):
    return client.post(
        "/api/word-change-requests/{}/cancel".format(request_id),
        headers={HOST_TOKEN_HEADER: host_token},
    )


def _word_status(app, word_id):
    with app.app_context():
        return db.session.get(Word, word_id).status, db.session.get(
            Word, word_id
        ).word_text


@pytest.fixture()
def game_setup(app, client):
    game_id, host_token = _create_game(client)
    team_a_id, token_a = _create_team(app, game_id, "AAA", name="Team A")
    team_b_id, token_b = _create_team(app, game_id, "BBB", name="Team B")
    category_id = _create_category(client, game_id, host_token, "Food")
    word_id = _submit(
        client, game_id, category_id, team_b_id, token_b, "Pancit"
    )
    return {
        "game_id": game_id,
        "host_token": host_token,
        "team_a_id": team_a_id,
        "token_a": token_a,
        "team_b_id": team_b_id,
        "token_b": token_b,
        "category_id": category_id,
        "word_id": word_id,
    }


# ---------------------------------------------------------------------------
# Creating requests (host only)
# ---------------------------------------------------------------------------


def test_create_request_marks_word_under_review(app, client, game_setup):
    response = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "Please reword this.",
    )
    assert response.status_code == 201
    body = response.get_json()["data"]
    assert body["status"] == "PENDING"
    assert body["word_text"] == "Pancit"
    assert body["comment"] == "Please reword this."

    status, _ = _word_status(app, game_setup["word_id"])
    assert status == Word.STATUS_UNDER_REVIEW

    pending = _pending_for(
        client,
        game_setup["game_id"],
        game_setup["token_a"],
    ).get_json()["data"]
    assert len(pending["requests"]) == 1


def test_create_request_requires_host(client, game_setup):
    response = client.post(
        "/api/games/{}/word-change-requests".format(game_setup["game_id"]),
        json={
            "team_id": game_setup["team_a_id"],
            "word_id": game_setup["word_id"],
            "comment": "x",
        },
        headers={SESSION_TOKEN_HEADER: game_setup["token_a"]},
    )
    assert response.status_code == 401


def test_create_request_duplicate_word_rejected(app, client, game_setup):
    _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "First.",
    )
    response = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "Second.",
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "WORD_UNDER_REVIEW"


def test_create_request_comment_required(client, game_setup):
    response = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        None,
    )
    assert response.status_code == 400
    assert (
        response.get_json()["error"]["code"] == "REQUEST_COMMENT_REQUIRED"
    )


def test_create_request_rejects_disabled_word(app, client, game_setup):
    disable = client.post(
        "/api/words/{}/disable".format(game_setup["word_id"]),
        json={},
        headers={HOST_TOKEN_HEADER: game_setup["host_token"]},
    )
    assert disable.status_code == 200
    response = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "x",
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "WORD_NOT_AVAILABLE"


def test_create_request_rejects_foreign_word(client, game_setup):
    other_game_id, _ = _create_game(client)
    response = client.post(
        "/api/games/{}/word-change-requests".format(game_setup["game_id"]),
        json={
            "team_id": game_setup["team_a_id"],
            "word_id": 999999,
            "comment": "x",
        },
        headers={HOST_TOKEN_HEADER: game_setup["host_token"]},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "WORD_NOT_IN_GAME"
    assert other_game_id  # silence unused


# ---------------------------------------------------------------------------
# Resolving (request team's device only)
# ---------------------------------------------------------------------------


def test_resolve_updates_word_and_closes_request(app, client, game_setup):
    created = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "Please reword.",
    ).get_json()["data"]

    response = _resolve(
        client, created["id"], game_setup["token_a"], "Lugaw"
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == "RESOLVED"
    assert data["resolved_at"] is not None
    assert data["word_text"] == "Lugaw"

    status, word_text = _word_status(app, game_setup["word_id"])
    assert status == Word.STATUS_AVAILABLE
    assert word_text == "Lugaw"

    response2 = _resolve(
        client, created["id"], game_setup["token_a"], "Adobo"
    )
    assert response2.status_code == 409
    assert response2.get_json()["error"]["code"] == "REQUEST_NOT_PENDING"


def test_resolve_requires_request_team(app, client, game_setup):
    created = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "x",
    ).get_json()["data"]

    response = _resolve(
        client, created["id"], game_setup["token_b"], "Lugaw"
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "REQUEST_OWNERSHIP"


def test_resolve_rejects_invalid_characters(app, client, game_setup):
    created = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "x",
    ).get_json()["data"]

    response = _resolve(
        client, created["id"], game_setup["token_a"], "tess_la"
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "WORD_TEXT_INVALID"

    status, _ = _word_status(app, game_setup["word_id"])
    assert status == Word.STATUS_UNDER_REVIEW


def test_resolve_rejects_duplicate(app, client, game_setup):
    _submit(
        client,
        game_setup["game_id"],
        game_setup["category_id"],
        game_setup["team_a_id"],
        game_setup["token_a"],
        "Adobo",
    )
    created = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "x",
    ).get_json()["data"]

    response = _resolve(
        client, created["id"], game_setup["token_a"], "adobo"
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "DUPLICATE_WORD"

    status, _ = _word_status(app, game_setup["word_id"])
    assert status == Word.STATUS_UNDER_REVIEW


def test_resolve_preserves_category_and_capitalizes(app, client, game_setup):
    created = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "x",
    ).get_json()["data"]

    response = _resolve(
        client, created["id"], game_setup["token_a"], "adobo"
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["category_id"] == game_setup["category_id"]
    with app.app_context():
        word = db.session.get(Word, game_setup["word_id"])
        assert word.word_text == "Adobo"
        assert word.category_id == game_setup["category_id"]


def test_resolve_preserves_internal_spacing(app, client, game_setup):
    _submit(
        client,
        game_setup["game_id"],
        game_setup["category_id"],
        game_setup["team_b_id"],
        game_setup["token_b"],
        "Sinigang",
    )
    word2 = _submit(
        client,
        game_setup["game_id"],
        game_setup["category_id"],
        game_setup["team_b_id"],
        game_setup["token_b"],
        "Nilaga",
    )
    created = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        word2,
        "x",
    ).get_json()["data"]
    response = _resolve(
        client,
        created["id"],
        game_setup["token_a"],
        "Lugaw   na may   sabaw",
    )
    assert response.status_code == 200
    with app.app_context():
        word = db.session.get(Word, word2)
        assert word.word_text == "Lugaw   na may   sabaw"
    assert game_setup["word_id"]  # silence unused


# ---------------------------------------------------------------------------
# Cancelling (host only)
# ---------------------------------------------------------------------------


def test_cancel_returns_word_to_pool(app, client, game_setup):
    created = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "x",
    ).get_json()["data"]

    response = _cancel(client, created["id"], game_setup["host_token"])
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == WordChangeRequest.STATUS_CANCELLED

    status, _ = _word_status(app, game_setup["word_id"])
    assert status == Word.STATUS_AVAILABLE


def test_cancel_requires_host(client, game_setup):
    created = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "x",
    ).get_json()["data"]
    response = client.post(
        "/api/word-change-requests/{}/cancel".format(created["id"]),
        headers={SESSION_TOKEN_HEADER: game_setup["token_a"]},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_host_lists_all_requests(client, game_setup):
    created = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "x",
    ).get_json()["data"]
    body = _list_host(
        client, game_setup["game_id"], game_setup["host_token"]
    ).get_json()["data"]
    assert len(body["requests"]) == 1
    assert body["requests"][0]["id"] == created["id"]


def test_player_lists_only_own_pending(app, client, game_setup):
    _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "x",
    )
    body = _pending_for(
        client, game_setup["game_id"], game_setup["token_b"]
    ).get_json()["data"]
    assert len(body["requests"]) == 0
    body_a = _pending_for(
        client, game_setup["game_id"], game_setup["token_a"]
    ).get_json()["data"]
    assert len(body_a["requests"]) == 1


# ---------------------------------------------------------------------------
# Word/team deletion detaches + auto-cancels requests
# ---------------------------------------------------------------------------


def test_delete_word_cancels_pending_request(app, client, game_setup):
    created = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "x",
    ).get_json()["data"]

    response = client.delete(
        "/api/words/{}".format(game_setup["word_id"]),
        headers={HOST_TOKEN_HEADER: game_setup["host_token"]},
    )
    assert response.status_code == 200

    with app.app_context():
        req = db.session.get(WordChangeRequest, created["id"])
        assert req.status == WordChangeRequest.STATUS_CANCELLED
        assert req.word_id is None
        assert db.session.get(Word, game_setup["word_id"]) is None


def test_delete_team_detaches_requests(app, client, game_setup):
    created = _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "x",
    ).get_json()["data"]

    response = client.delete(
        "/api/teams/{}".format(game_setup["team_a_id"]),
        headers={HOST_TOKEN_HEADER: game_setup["host_token"]},
    )
    assert response.status_code == 200

    with app.app_context():
        req = db.session.get(WordChangeRequest, created["id"])
        assert req.team_id is None
        assert db.session.get(Team, game_setup["team_a_id"]) is None


def test_resolve_removed_from_pool_logically(app, client, game_setup):
    """Words under review are excluded from gameplay pool picks."""
    _create_request(
        client,
        game_setup["game_id"],
        game_setup["host_token"],
        game_setup["team_a_id"],
        game_setup["word_id"],
        "x",
    )
    with app.app_context():
        from app.models import Game
        from app.services import gameplay_service

        game = db.session.get(Game, game_setup["game_id"])
        game.status = Game.STATUS_SETUP
        ensured = gameplay_service.ensure_game_setup(game)
        assert ensured["matches"]
        pool = gameplay_service._round_word_pool(ensured["matches"][0])
        assert "Pancit" not in [word.word_text for word in pool]