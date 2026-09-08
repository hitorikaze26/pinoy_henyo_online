import pytest

from app import create_app
from app.extensions import db
from app.models import Game, GameEvent
from app.services import game_service
from app.services.game_service import GameStateError

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
    body = response.get_json()
    assert body["success"] is True
    return body["data"]


def _create_direct(game_code, status=Game.STATUS_LOBBY, current_round=None):
    game = Game(
        game_code=game_code,
        host_session_token="host-token",
        status=status,
        current_round=current_round,
    )
    db.session.add(game)
    db.session.commit()
    return game


# ---------------------------------------------------------------------------
# Game creation
# ---------------------------------------------------------------------------


def test_create_game_returns_expected_fields(client):
    data = _create_game(client)
    assert set(data) == {
        "game_id",
        "game_code",
        "host_session_token",
        "status",
    }
    assert data["status"] == Game.STATUS_LOBBY
    assert data["game_code"].startswith("PH")
    assert len(data["game_code"]) == 6
    assert data["host_session_token"]


def test_game_codes_are_unique(app, client):
    codes = set()
    for _ in range(25):
        codes.add(_create_game(client)["game_code"])
    assert len(codes) == 25


def test_game_created_event_recorded(app, client):
    data = _create_game(client)
    with app.app_context():
        events = (
            db.session.query(GameEvent)
            .filter_by(game_id=data["game_id"])
            .all()
        )
        assert [e.event_type for e in events] == ["GAME_CREATED"]


# ---------------------------------------------------------------------------
# Game retrieval & status
# ---------------------------------------------------------------------------


def test_get_game_returns_basic_info(client):
    data = _create_game(client)
    response = client.get("/api/games/{}".format(data["game_id"]))
    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["game_id"] == data["game_id"]
    assert body["game_code"] == data["game_code"]
    assert body["status"] == Game.STATUS_LOBBY
    assert "host_session_token" not in body


def test_get_game_status(client):
    data = _create_game(client)
    response = client.get("/api/games/{}/status".format(data["game_id"]))
    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["status"] == Game.STATUS_LOBBY
    assert body["current_round"] is None
    assert body["current_match_id"] is None
    assert body["created_at"] is not None
    assert body["started_at"] is None
    assert body["ended_at"] is None
    # Word pool is NOT locked while the game is still in LOBBY/SETUP.
    assert body["word_pool_locked"] is False


def test_get_game_status_reflects_word_pool_lock(client):
    data = _create_game(client)
    game_id = data["game_id"]
    token = data["host_session_token"]
    # Start the game (leaves LOBBY/SETUP) -> word pool becomes locked.
    start = client.post(
        "/api/games/{}/start".format(game_id), headers={HOST_TOKEN_HEADER: token}
    )
    assert start.status_code == 200
    body = client.get("/api/games/{}/status".format(game_id)).get_json()["data"]
    assert body["word_pool_locked"] is True


def test_get_missing_game_returns_404(client):
    assert client.get("/api/games/999999").status_code == 404
    assert client.get("/api/games/999999/status").status_code == 404


# ---------------------------------------------------------------------------
# Host authorization
# ---------------------------------------------------------------------------


def _start(client, game_id, token=None):
    headers = {}
    if token is not None:
        headers[HOST_TOKEN_HEADER] = token
    return client.post("/api/games/{}/start".format(game_id), headers=headers)


def test_start_requires_host_token(client):
    data = _create_game(client)
    assert _start(client, data["game_id"]).status_code == 401


def test_start_rejects_invalid_host_token(client):
    data = _create_game(client)
    assert _start(client, data["game_id"], token="wrong-token").status_code == 401


def test_start_accepts_bearer_token(client):
    data = _create_game(client)
    response = client.post(
        "/api/games/{}/start".format(data["game_id"]),
        headers={"Authorization": "Bearer {}".format(data["host_session_token"])},
    )
    assert response.status_code == 200


def test_control_on_missing_game_returns_404(client):
    response = client.post(
        "/api/games/999999/start",
        headers={HOST_TOKEN_HEADER: "any-token"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


def test_start_moves_game_to_ready(client):
    data = _create_game(client)
    response = _start(client, data["game_id"], data["host_session_token"])
    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["status"] == Game.STATUS_READY

    status = client.get("/api/games/{}/status".format(data["game_id"]))
    status_body = status.get_json()["data"]
    assert status_body["status"] == Game.STATUS_READY
    assert status_body["started_at"] is not None


def test_start_auto_creates_rounds_and_single_team_matches(client, app):
    from app.models import Match, Round, Team, TeamMember

    data = _create_game(client)
    with app.app_context():
        for idx, code in enumerate(("AA", "BB"), start=1):
            team = Team(
                game_id=data["game_id"],
                team_code=code,
                team_name="Team {}".format(code),
            )
            db.session.add(team)
            db.session.flush()
            leader = TeamMember(
                team_id=team.id,
                username="Leader {}".format(code),
                device_role=TeamMember.DEVICE_ROLE_TEAM_LEADER,
                connection_token="ct-{}".format(code),
            )
            db.session.add(leader)
            db.session.flush()
            team.leader_member_id = leader.id
            team.status = Team.STATUS_ACTIVE
        db.session.commit()

    assert _start(client, data["game_id"], data["host_session_token"]).status_code == 200

    with app.app_context():
        rounds = Round.query.filter_by(game_id=data["game_id"]).order_by(
            Round.round_number
        ).all()
        assert [r.round_number for r in rounds] == [1, 2]
        for round_obj in rounds:
            matches = Match.query.filter_by(round_id=round_obj.id).order_by(
                Match.match_order
            ).all()
            assert len(matches) == 2
            assert [m.team_id for m in matches] == [
                team.id for team in Team.query.filter_by(
                    game_id=data["game_id"]
                ).order_by(Team.id).all()
            ]
            assert all(m.opponent_team_id is None for m in matches)


def test_advance_round_auto_creates_matches_for_next_round(client, app):
    from app.models import Match, Round, Team, TeamMember

    data = _create_game(client)
    with app.app_context():
        for idx, code in enumerate(("AA", "BB"), start=1):
            team = Team(
                game_id=data["game_id"],
                team_code=code,
                team_name="Team {}".format(code),
            )
            db.session.add(team)
            db.session.flush()
            leader = TeamMember(
                team_id=team.id,
                username="Leader {}".format(code),
                device_role=TeamMember.DEVICE_ROLE_TEAM_LEADER,
                connection_token="ct-{}".format(code),
            )
            db.session.add(leader)
            db.session.flush()
            team.leader_member_id = leader.id
            team.status = Team.STATUS_ACTIVE
        db.session.commit()

    token = data["host_session_token"]
    assert _start(client, data["game_id"], token).status_code == 200
    # The Round 2 gate requires every Round 1 match to be completed first.
    with app.app_context():
        round_one = Round.query.filter_by(
            game_id=data["game_id"], round_number=1
        ).one()
        for match in round_one.matches:
            match.status = Match.STATUS_COMPLETED
        db.session.commit()
    response = client.post(
        "/api/games/{}/rounds/1/advance".format(data["game_id"]),
        headers={HOST_TOKEN_HEADER: token},
    )
    assert response.status_code == 200
    with app.app_context():
        round_two = Round.query.filter_by(
            game_id=data["game_id"], round_number=2
        ).one()
        assert len(Match.query.filter_by(round_id=round_two.id).all()) == 2


def test_duplicate_start_is_rejected(client):
    data = _create_game(client)
    token = data["host_session_token"]
    assert _start(client, data["game_id"], token).status_code == 200
    response = _start(client, data["game_id"], token)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "INVALID_TRANSITION"


def test_end_after_start_reaches_game_complete(client):
    data = _create_game(client)
    token = data["host_session_token"]
    assert _start(client, data["game_id"], token).status_code == 200
    response = client.post(
        "/api/games/{}/end".format(data["game_id"]),
        headers={HOST_TOKEN_HEADER: token},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == Game.STATUS_GAME_COMPLETE

    status = client.get("/api/games/{}/status".format(data["game_id"]))
    status_body = status.get_json()["data"]
    assert status_body["status"] == Game.STATUS_GAME_COMPLETE
    assert status_body["ended_at"] is not None


def test_end_from_lobby_is_forbidden(client):
    data = _create_game(client)
    response = client.post(
        "/api/games/{}/end".format(data["game_id"]),
        headers={HOST_TOKEN_HEADER: data["host_session_token"]},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "INVALID_TRANSITION"


def test_pause_from_ready_is_invalid(app, client):
    data = _create_game(client)
    token = data["host_session_token"]
    assert _start(client, data["game_id"], token).status_code == 200
    response = client.post(
        "/api/games/{}/pause".format(data["game_id"]),
        headers={HOST_TOKEN_HEADER: token},
    )
    assert response.status_code == 409


def test_pause_resume_requires_active_round(app):
    with app.app_context():
        game = _create_direct("TESTAA", status=Game.STATUS_ROUND_1)
        response = game_service.pause_game(game)
        assert response["status"] == Game.STATUS_PAUSED

        response = game_service.resume_game(game)
        assert response["status"] == Game.STATUS_ROUND_1

        second_response = game_service.pause_game(game)
        assert second_response["status"] == Game.STATUS_PAUSED
        with pytest.raises(GameStateError):
            game_service.pause_game(game)
        db.session.rollback()


def test_resume_paused_round_two_returns_round_two(app):
    with app.app_context():
        game = _create_direct("TESTBB", status=Game.STATUS_ROUND_2, current_round=2)
        game_service.pause_game(game)
        assert game.status == Game.STATUS_PAUSED
        game_service.resume_game(game)
        assert game.status == Game.STATUS_ROUND_2


def test_end_from_active_round(app):
    with app.app_context():
        game = _create_direct("TESTCC", status=Game.STATUS_ROUND_1)
        response = game_service.end_game(game)
        assert response["status"] == Game.STATUS_GAME_COMPLETE
        assert game.ended_at is not None


def test_actions_record_events(app, client):
    data = _create_game(client)
    token = data["host_session_token"]
    assert _start(client, data["game_id"], token).status_code == 200
    response = client.post(
        "/api/games/{}/end".format(data["game_id"]),
        headers={HOST_TOKEN_HEADER: token},
    )
    assert response.status_code == 200

    with app.app_context():
        events = (
            db.session.query(GameEvent)
            .filter_by(game_id=data["game_id"])
            .order_by(GameEvent.id)
            .all()
        )
        assert [e.event_type for e in events] == [
            "GAME_CREATED",
            "GAME_STARTED",
            "GAME_ENDED",
        ]


def test_game_creation_rate_limited(client, app):
    created = 0
    status = None
    for _ in range(31):
        r = client.post("/api/games")
        status = r.status_code
        if status == 201:
            created += 1
        elif status == 429:
            break
    assert created == 30
    assert status == 429
    # 429 must surface a Retry-After hint to the frontend (M4).
    assert int(r.headers.get("Retry-After", "0")) > 0
    assert r.get_json()["error"]["retry_after"] > 0
    assert r.get_json()["error"]["code"] == "RATE_LIMITED"
