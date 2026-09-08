import json

import pytest

from app import create_app
from app.extensions import db
from app.models import AIGenerationLog, DeviceSession, TeamMember

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
    from app.models import Team

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


def _submit_word(client, game_id, category_id, team_id, word, token=None):
    headers = {}
    if token is not None:
        headers[HOST_TOKEN_HEADER] = token
    return client.post(
        "/api/games/{}/words".format(game_id),
        json={
            "team_id": team_id,
            "category_id": category_id,
            "word_text": word,
        },
        headers=headers,
    )


def _generate(client, game_id, category_id, host_token=None, session_token=None, **body):
    headers = {}
    if host_token is not None:
        headers[HOST_TOKEN_HEADER] = host_token
    if session_token is not None:
        headers[SESSION_TOKEN_HEADER] = session_token
    payload = {"category_id": category_id, "count": body.get("count", 5)}
    for key in ("language", "exclude_words"):
        if key in body:
            payload[key] = body[key]
    return client.post(
        "/api/games/{}/ai/generate-words".format(game_id),
        json=payload,
        headers=headers,
    )


def _fake_words(*words):
    def fake(prompt):
        assert "Pinoy Henyo" in prompt
        return json.dumps({"words": list(words)})

    return fake


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_generate_requires_actor(client):
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")
    response = _generate(client, game_id, category_id)
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "SESSION_REQUIRED"


def test_generate_invalid_host_token(client):
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")
    response = _generate(client, game_id, category_id, host_token="wrong")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_generate_invalid_session_token(client, app):
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")
    response = _generate(client, game_id, category_id, session_token="bogus")
    assert response.status_code == 401


def test_generate_game_not_found(client):
    response = client.post(
        "/api/games/999999/ai/generate-words",
        json={"category_id": 1, "count": 5},
        headers={HOST_TOKEN_HEADER: "token"},
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "GAME_NOT_FOUND"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_generate_requires_category(client):
    game_id, host_token = _create_game(client)
    response = client.post(
        "/api/games/{}/ai/generate-words".format(game_id),
        json={"count": 5},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "CATEGORY_REQUIRED"


def test_generate_category_not_in_game(client):
    game_id, host_token = _create_game(client)
    other_id, other_token = _create_game(client)
    category_id = _create_category(client, other_id, other_token, "Food")
    response = _generate(client, game_id, category_id, host_token=host_token)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "CATEGORY_NOT_IN_GAME"


def test_generate_count_invalid(client):
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")
    for bad in (0, 21, -3, "five", 2.5, True):
        response = _generate(
            client, game_id, category_id, host_token=host_token, count=bad
        )
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "AI_WORD_COUNT_INVALID"


def test_generate_language_invalid(client):
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")
    response = _generate(
        client,
        game_id,
        category_id,
        host_token=host_token,
        language="klingon",
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "AI_LANGUAGE_INVALID"


def test_generate_exclude_words_not_list(client):
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")
    response = _generate(
        client,
        game_id,
        category_id,
        host_token=host_token,
        exclude_words="Adobo",
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "AI_EXCLUDE_WORDS_INVALID"


# ---------------------------------------------------------------------------
# Successful generation
# ---------------------------------------------------------------------------


def test_generate_host_success(client, app, monkeypatch):
    from app.services import ai_word_service

    monkeypatch.setattr(ai_word_service, "_generate_text", _fake_words("Adobo", "Sisig"))
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")

    response = _generate(
        client, game_id, category_id, host_token=host_token, count=2
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["category_id"] == category_id
    assert data["category_name"] == "Food"
    assert data["language"] == "tagalog"
    assert data["suggestions"] == ["Adobo", "Sisig"]
    assert data["available_slots"] is None  # host has no per-category cap

    # Generation alone must never insert words.
    words = client.get(
        "/api/games/{}/words".format(game_id),
        headers={HOST_TOKEN_HEADER: host_token},
    ).get_json()["data"]["words"]
    assert words == []


def test_generate_player_success(client, app, monkeypatch):
    from app.services import ai_word_service

    monkeypatch.setattr(ai_word_service, "_generate_text", _fake_words("Adobo"))
    game_id, host_token = _create_game(client)
    team_id, session_token = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")

    response = _generate(
        client, game_id, category_id, session_token=session_token, count=1
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["suggestions"] == ["Adobo"]
    assert data["available_slots"] == 5  # max_words_per_category default 5, nothing used


def test_generate_player_slots_account_for_existing_words(client, app, monkeypatch):
    from app.services import ai_word_service

    monkeypatch.setattr(ai_word_service, "_generate_text", _fake_words("Carrot"))
    game_id, host_token = _create_game(client)
    team_id, session_token = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    _submit_word(client, game_id, category_id, team_id, "Potato", token=host_token)

    response = _generate(
        client, game_id, category_id, session_token=session_token, count=1
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["available_slots"] == 4


def test_generate_both_languages(client, app, monkeypatch):
    from app.services import ai_word_service

    monkeypatch.setattr(ai_word_service, "_generate_text", _fake_words("Mabuhay"))
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")

    response = _generate(
        client,
        game_id,
        category_id,
        host_token=host_token,
        count=1,
        language="both",
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["language"] == "both"
    assert response.get_json()["data"]["suggestions"] == ["Mabuhay"]


def test_generate_place_category_ignores_language(client, app, monkeypatch):
    from app.services import ai_word_service

    monkeypatch.setattr(ai_word_service, "_generate_text", _fake_words("Boracay"))
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Lugar / place")

    # Invalid language is tolerated — place names are locale-agnostic.
    response = _generate(
        client,
        game_id,
        category_id,
        host_token=host_token,
        count=1,
        language="klingon",
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["language"] is None
    assert data["suggestions"] == ["Boracay"]


# ---------------------------------------------------------------------------
# Sanitization, dedupe, authoritative exclusions
# ---------------------------------------------------------------------------


def test_generate_sanitizes_and_dedupes(client, app, monkeypatch):
    from app.services import ai_word_service

    long_word = "x" * 101
    monkeypatch.setattr(
        ai_word_service,
        "_generate_text",
        _fake_words(
            "Adobo",
            "adobo",  # dup -> dropped
            "Halo halo",
            "bad,word",  # punctuation -> dropped
            long_word,  # too long -> dropped
            "",
            "Sisig",
        ),
    )
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")

    response = _generate(
        client, game_id, category_id, host_token=host_token, count=7
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["suggestions"] == ["Adobo", "Halo halo", "Sisig"]
    # Log reflects accepted (kept) count, not the requested count.
    with app.app_context():
        logs = AIGenerationLog.query.all()
        assert len(logs) == 1
        assert logs[0].requested_count == 7
        assert logs[0].accepted_count == 3
        assert logs[0].success is True
        assert logs[0].actor_type == AIGenerationLog.ACTOR_HOST
        assert logs[0].category_name == "Food"
        assert logs[0].language == "tagalog"


def test_generate_drops_existing_words(client, app, monkeypatch):
    from app.services import ai_word_service

    monkeypatch.setattr(ai_word_service, "_generate_text", _fake_words("Potato", "Carrot"))
    game_id, host_token = _create_game(client)
    team_id, _ = _create_team(app, game_id, "A1")
    category_id = _create_category(client, game_id, host_token, "Food")
    _submit_word(client, game_id, category_id, team_id, "Potato", token=host_token)

    response = _generate(
        client, game_id, category_id, host_token=host_token, count=2
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["suggestions"] == ["Carrot"]


def test_generate_drops_client_exclusions(client, app, monkeypatch):
    from app.services import ai_word_service

    monkeypatch.setattr(ai_word_service, "_generate_text", _fake_words("Adobo", "Sisig"))
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")

    response = _generate(
        client,
        game_id,
        category_id,
        host_token=host_token,
        count=2,
        exclude_words=["adobo"],
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["suggestions"] == ["Sisig"]


def test_generate_never_duplicates_across_categories(client, app, monkeypatch):
    from app.services import ai_word_service

    monkeypatch.setattr(ai_word_service, "_generate_text", _fake_words("Tiger"))
    game_id, host_token = _create_game(client)
    team_id, _ = _create_team(app, game_id, "A1")
    food = _create_category(client, game_id, host_token, "Food")
    animals = _create_category(client, game_id, host_token, "Animals")
    _submit_word(client, game_id, food, team_id, "Tiger", token=host_token)

    # Same word exists in Food -> still fine in Animals (uniqueness is per category).
    response = _generate(
        client, game_id, animals, host_token=host_token, count=1
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["suggestions"] == ["Tiger"]


# ---------------------------------------------------------------------------
# Upstream failures
# ---------------------------------------------------------------------------


def test_generate_not_configured(client):
    # TestingConfig.GEMINI_API_KEY is "" -> real _generate_text raises
    # AINotConfiguredError without monkeypatching.
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")
    response = _generate(
        client, game_id, category_id, host_token=host_token, count=5
    )
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "AI_NOT_CONFIGURED"


def test_generate_upstream_unavailable(client, app, monkeypatch):
    from app.services import ai_word_service

    def boom(prompt):
        raise ai_word_service.AIUnavailableError("down")

    monkeypatch.setattr(ai_word_service, "_generate_text", boom)
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")
    response = _generate(
        client, game_id, category_id, host_token=host_token, count=5
    )
    assert response.status_code == 502
    assert response.get_json()["error"]["code"] == "AI_GENERATION_UNAVAILABLE"


def test_generate_malformed_then_success_retries_once(client, app, monkeypatch):
    from app.services import ai_word_service

    calls = []

    def flaky(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return "not json at all"
        return json.dumps({"words": ["Adobo"]})

    monkeypatch.setattr(ai_word_service, "_generate_text", flaky)
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")

    response = _generate(
        client, game_id, category_id, host_token=host_token, count=1
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["suggestions"] == ["Adobo"]
    assert len(calls) == 2  # one retry


def test_generate_malformed_twice(client, app, monkeypatch):
    from app.services import ai_word_service

    monkeypatch.setattr(
        ai_word_service,
        "_generate_text",
        lambda prompt: json.dumps({"nope": []}),
    )
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")

    response = _generate(
        client, game_id, category_id, host_token=host_token, count=1
    )
    assert response.status_code == 502
    assert response.get_json()["error"]["code"] == "AI_GENERATION_INVALID_RESPONSE"


def test_generate_empty_output(client, app, monkeypatch):
    from app.services import ai_word_service

    monkeypatch.setattr(ai_word_service, "_generate_text", lambda prompt: "")
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")

    response = _generate(
        client, game_id, category_id, host_token=host_token, count=1
    )
    assert response.status_code == 502
    assert response.get_json()["error"]["code"] == "AI_GENERATION_INVALID_RESPONSE"


# ---------------------------------------------------------------------------
# Limits: cooldown + per-IP rate limit
# ---------------------------------------------------------------------------


def test_generate_cooldown_per_game_actor(client, app, monkeypatch):
    from app.services import ai_word_service

    app.config["AI_REQUEST_COOLDOWN_SECONDS"] = 60
    monkeypatch.setattr(ai_word_service, "_generate_text", _fake_words("Adobo"))
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")

    first = _generate(
        client, game_id, category_id, host_token=host_token, count=1
    )
    assert first.status_code == 200

    second = _generate(
        client, game_id, category_id, host_token=host_token, count=1
    )
    assert second.status_code == 429
    assert second.get_json()["error"]["code"] == "AI_RATE_LIMITED"
    assert second.headers["Retry-After"]


def test_generate_rate_limit_per_ip(client, app, monkeypatch):
    from app.services import ai_word_service

    # Cooldown is per (game, actor), so different games/actors let us isolate
    # the per-IP sliding-window limit.
    app.config["AI_MAX_REQUESTS_PER_MINUTE"] = 2
    monkeypatch.setattr(ai_word_service, "_generate_text", _fake_words("Adobo"))

    games = [_create_game(client) for _ in range(3)]
    response = None
    for game_id, host_token in games:
        category_id = _create_category(client, game_id, host_token, "Food")
        response = _generate(
            client, game_id, category_id, host_token=host_token, count=1
        )
    assert response.status_code == 429  # third request this window (limit 2)
    assert response.get_json()["error"]["code"] == "AI_RATE_LIMITED"


def test_generate_failure_is_logged(client, app, monkeypatch):
    from app.services import ai_word_service

    monkeypatch.setattr(ai_word_service, "_generate_text", lambda prompt: "garbage")
    game_id, host_token = _create_game(client)
    category_id = _create_category(client, game_id, host_token, "Food")

    response = _generate(
        client, game_id, category_id, host_token=host_token, count=1
    )
    assert response.status_code == 502

    with app.app_context():
        logs = AIGenerationLog.query.all()
        assert len(logs) >= 1
        bad = logs[-1]
        assert bad.success is False
        assert bad.error_code == "AI_GENERATION_INVALID_RESPONSE"
        assert bad.category_name == "Food"
        assert bad.requested_count == 1
        assert bad.accepted_count == 0