"""Tests for CRUD & database service layer (Part 2)."""

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Category,
    DeviceSession,
    Game,
    GameEvent,
    Match,
    Penalty,
    Round,
    RoundCategory,
    Score,
    Team,
    TeamMember,
    Turn,
    TurnWord,
    Word,
    WordChangeRequest,
)

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
    return response.get_json()["data"]


def _create_team(client, game_id, team_name="Team A", username="Juan",
                 host_token=None):
    headers = {HOST_TOKEN_HEADER: host_token} if host_token else {}
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"username": username, "team_name": team_name},
        headers=headers,
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _add_member(client, team_id, username="Pedro"):
    response = client.post(
        "/api/teams/{}/members".format(team_id),
        json={"username": username},
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


# ---------------------------------------------------------------------------
# Game deletion (host history cleanup)
# ---------------------------------------------------------------------------


def test_delete_game_requires_host(client):
    g = _create_game(client)
    # No host token -> 401
    response = client.delete("/api/games/{}".format(g["game_id"]))
    assert response.status_code in (401, 404)
    # Wrong host token -> 401
    response = client.delete(
        "/api/games/{}".format(g["game_id"]),
        headers={HOST_TOKEN_HEADER: "wrong-token"},
    )
    assert response.status_code in (401, 404)


def test_delete_requires_confirmation(client, app):
    g = _create_game(client)
    from app.services import game_service
    with app.app_context():
        game = db.session.get(Game, g["game_id"])
        game.status = Game.STATUS_CANCELLED
        db.session.commit()
    # No confirm flag -> 400.
    response = client.delete(
        "/api/games/{}".format(g["game_id"]),
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "WITH_CONFIRMATION_REQUIRED"
    with app.app_context():
        assert db.session.get(Game, g["game_id"]) is not None


def test_delete_wrong_host_rejected(client, app):
    g = _create_game(client)
    other = _create_game(client)
    from app.services import game_service
    with app.app_context():
        game = db.session.get(Game, g["game_id"])
        game.status = Game.STATUS_CANCELLED
        db.session.commit()
    response = client.delete(
        "/api/games/{}".format(g["game_id"]),
        json={"confirm": True},
        headers={HOST_TOKEN_HEADER: other["host_session_token"]},
    )
    assert response.status_code in (401, 404)


def test_delete_looby_game_rejected(client):
    g = _create_game(client)
    response = client.delete(
        "/api/games/{}".format(g["game_id"]),
        json={"confirm": True},
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    # Only terminal games may be deleted; LOBBY is not terminal.
    assert response.status_code == 409


def test_delete_completed_game_removes_all_cascades(client, app):
    g = _create_game(client)
    team = _create_team(
        client, g["game_id"], host_token=g["host_session_token"]
    )
    team_id = team["team_id"]

    # Force the game to a terminal (cancelled) state via direct service call.
    from app.services import game_service
    with app.app_context():
        game = db.session.get(Game, g["game_id"])
        game.status = Game.STATUS_CANCELLED
        db.session.commit()

    response = client.delete(
        "/api/games/{}".format(g["game_id"]),
        json={"confirm": True},
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 200

    with app.app_context():
        assert db.session.get(Game, g["game_id"]) is None
        assert db.session.get(Team, team_id) is None


def test_delete_full_game_no_orphans(client, app):
    """Delete a fully-played game and verify every FK-referencing child is
    removed (rounds, matches with opponent/winner refs, turns, words, scores,
    events, members, categories) with no orphan rows and no FK violation."""
    g = _create_game(client)
    game_id = g["game_id"]

    with app.app_context():
        game = db.session.get(Game, game_id)
        game.status = Game.STATUS_ROUND_1

        cat_a = Category(game_id=game_id, name="Food")
        cat_b = Category(game_id=game_id, name="Places")
        db.session.add_all([cat_a, cat_b])
        db.session.flush()

        # Teams with leaders.
        team_a = Team(game_id=game_id, team_name="Alpha", team_code="AAA",
                      connection_status=Team.CONNECTION_CONNECTED)
        team_b = Team(game_id=game_id, team_name="Bravo", team_code="BBB",
                      connection_status=Team.CONNECTION_CONNECTED)
        db.session.add_all([team_a, team_b])
        db.session.flush()

        leader_a = TeamMember(team_id=team_a.id, username="ALead",
                              device_role=TeamMember.DEVICE_ROLE_TEAM_LEADER,
                              connection_token="tok-a")
        leader_b = TeamMember(team_id=team_b.id, username="BLead",
                              device_role=TeamMember.DEVICE_ROLE_TEAM_LEADER,
                              connection_token="tok-b")
        member_a = TeamMember(team_id=team_a.id, username="AMem",
                              device_role=TeamMember.DEVICE_ROLE_TEAM_MEMBER,
                              connection_token="tok-aa")
        db.session.add_all([leader_a, leader_b, member_a])
        db.session.flush()
        team_a.leader_member_id = leader_a.id
        team_b.leader_member_id = leader_b.id

        # Words submitted by both teams.
        w1 = Word(game_id=game_id, category_id=cat_a.id,
                  submitted_by_team_id=team_a.id, word_text="Apple",
                  normalized_word="apple")
        w2 = Word(game_id=game_id, category_id=cat_a.id,
                  submitted_by_team_id=team_b.id, word_text="Banana",
                  normalized_word="banana")
        db.session.add_all([w1, w2])
        db.session.flush()

        # Round 1 + matches capturing both opponent and winner references.
        r1 = Round(game_id=game_id, round_number=1, status=Round.STATUS_COMPLETED,
                   timer_seconds=60, timer_mode=Round.TIMER_MODE_COUNTDOWN)
        r2 = Round(game_id=game_id, round_number=2, status=Round.STATUS_COMPLETED,
                   timer_seconds=60, timer_mode=Round.TIMER_MODE_COUNTDOWN)
        db.session.add_all([r1, r2])
        db.session.flush()

        round_cat_a = RoundCategory(round_id=r1.id, category_id=cat_a.id)
        round_cat_b = RoundCategory(round_id=r2.id, category_id=cat_b.id)
        db.session.add_all([round_cat_a, round_cat_b])

        m1 = Match(game_id=game_id, round_id=r1.id, match_order=1,
                   team_id=team_a.id, opponent_team_id=team_b.id,
                   winner_team_id=team_a.id,
                   status=Match.STATUS_COMPLETED)
        m2 = Match(game_id=game_id, round_id=r2.id, match_order=2,
                   team_id=team_b.id, opponent_team_id=team_a.id,
                   winner_team_id=team_a.id,
                   status=Match.STATUS_COMPLETED)
        db.session.add_all([m1, m2])
        db.session.flush()
        game.current_match_id = m1.id

        # A turn with turn words + a penalty.
        t = Turn(match_id=m1.id, team_id=team_a.id, round_id=r1.id,
                 turn_order=1, status=Turn.STATUS_COMPLETED,
                 starting_seconds=60, remaining_seconds=0)
        db.session.add(t)
        db.session.flush()
        db.session.add(TurnWord(turn_id=t.id, word_id=w1.id, sequence=1,
                                result=TurnWord.RESULT_CORRECT))
        db.session.add(Penalty(turn_id=t.id, team_id=team_b.id, seconds=3,
                               type=Penalty.TYPE_ADD_TIME, reason="Late"))

        # Scores + devices + events.
        db.session.add(Score(game_id=game_id, team_id=team_a.id, round_id=r1.id,
                             match_id=m1.id, points=5, correct_words=5))
        db.session.add(DeviceSession(game_id=game_id, team_id=team_a.id,
                                     device_id="dev-a",
                                     session_token="sess-a",
                                     device_type=DeviceSession.DEVICE_TYPE_TEAM_LEADER))
        db.session.add(GameEvent(game_id=game_id, team_id=team_a.id,
                                 member_id=member_a.id, event_type="MEMBER_JOINED"))

        game.status = Game.STATUS_GAME_COMPLETE
        db.session.commit()

        ids = {
            "round": [r1.id, r2.id],
            "match": [m1.id, m2.id],
            "turn": [t.id],
            "word": [w1.id, w2.id],
            "team": [team_a.id, team_b.id],
            "member": [leader_a.id, leader_b.id, member_a.id],
            "score": [],
            "event": [],
            "device": [],
            "category": [cat_a.id, cat_b.id],
        }
        ids["score"].append(
            Score.query.filter_by(game_id=game_id).all()[0].id)
        ids["event"].append(
            GameEvent.query.filter_by(game_id=game_id).all()[0].id)
        ids["device"].append(
            DeviceSession.query.filter_by(game_id=game_id).all()[0].id)

    response = client.delete(
        "/api/games/{}".format(game_id),
        json={"confirm": True},
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 200

    with app.app_context():
        assert db.session.get(Game, game_id) is None
        for model, key in [
            (Round, "round"), (Match, "match"), (Turn, "turn"),
            (Word, "word"), (Team, "team"), (TeamMember, "member"),
            (Category, "category"),
        ]:
            for cid in ids[key]:
                assert db.session.get(model, cid) is None, (model, cid)
        for key in ("score", "event", "device"):
            for cid in ids[key]:
                assert db.session.get(
                    {"score": Score, "event": GameEvent,
                     "device": DeviceSession}[key], cid) is None


def test_delete_expired_game_with_word_change_requests(client, app):
    """Deleting an expired game that has word_change_requests must cascade
    successfully — no FK violation / 500."""
    g = _create_game(client)
    game_id = g["game_id"]

    with app.app_context():
        game = db.session.get(Game, game_id)
        game.status = Game.STATUS_EXPIRED

        team = Team(game_id=game_id, team_name="Alpha", team_code="AAA",
                     connection_status=Team.CONNECTION_CONNECTED)
        db.session.add(team)
        db.session.flush()

        wcr = WordChangeRequest(
            game_id=game_id, team_id=team.id,
            word_id=1, comment="Please fix",
        )
        db.session.add(wcr)
        wcr_id = wcr.id
        db.session.commit()

    response = client.delete(
        "/api/games/{}".format(game_id),
        json={"confirm": True},
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 200

    with app.app_context():
        assert db.session.get(Game, game_id) is None
        assert db.session.get(WordChangeRequest, wcr_id) is None


# ---------------------------------------------------------------------------
# Team deletion
# ---------------------------------------------------------------------------


def test_delete_team_requires_host(client):
    g = _create_game(client)
    team = _create_team(client, g["game_id"])
    response = client.delete("/api/teams/{}".format(team["team_id"]))
    assert response.status_code in (401, 404)


def test_delete_team_removes_team_and_members(client, app):
    g = _create_game(client)
    team = _create_team(client, g["game_id"])
    team_id = team["team_id"]
    member = _add_member(client, team_id)
    member_id = member["member_id"]

    response = client.delete(
        "/api/teams/{}".format(team_id),
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 200

    with app.app_context():
        assert db.session.get(Team, team_id) is None
        assert db.session.get(TeamMember, member_id) is None


def test_delete_connected_team_rejected(client, app):
    g = _create_game(client)
    team = _create_team(client, g["game_id"])
    team_id = team["team_id"]
    with app.app_context():
        t = db.session.get(Team, team_id)
        t.connection_status = Team.CONNECTION_CONNECTED
        db.session.commit()

    response = client.delete(
        "/api/teams/{}".format(team_id),
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 400


def test_delete_team_with_pending_match_slot_succeeds(client, app):
    g = _create_game(client)
    team_x = _create_team(client, g["game_id"], team_name="Team X")
    team_y = _create_team(client, g["game_id"], team_name="Team Y")
    team_x_id = team_x["team_id"]

    assert client.post(
        "/api/games/{}/rounds".format(g["game_id"]),
        json={"round_number": 1},
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    ).status_code == 201
    resp = client.post(
        "/api/games/{}/matches".format(g["game_id"]),
        json={
            "round_number": 1,
            "matches": [
                {"team_id": team_y["team_id"],
                 "opponent_team_id": team_x_id}
            ],
        },
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert resp.status_code == 201

    # A PENDING (never-played) setup slot does not block deletion: the team
    # has not started playing yet.
    response = client.delete(
        "/api/teams/{}".format(team_x_id),
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 200

    with app.app_context():
        assert db.session.get(Team, team_x_id) is None
        # The pending match slot referencing the deleted team is removed.
        assert Match.query.filter_by(opponent_team_id=team_x_id).count() == 0


def test_delete_started_team_rejected(client, app):
    g = _create_game(client)
    team_x = _create_team(client, g["game_id"], team_name="Team X")
    team_y = _create_team(client, g["game_id"], team_name="Team Y")
    team_x_id = team_x["team_id"]

    assert client.post(
        "/api/games/{}/rounds".format(g["game_id"]),
        json={"round_number": 1},
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    ).status_code == 201
    resp = client.post(
        "/api/games/{}/matches".format(g["game_id"]),
        json={
            "round_number": 1,
            "matches": [
                {"team_id": team_y["team_id"],
                 "opponent_team_id": team_x_id}
            ],
        },
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert resp.status_code == 201

    # Simulate the game having started play: the match is ACTIVE.
    with app.app_context():
        game = db.session.get(Game, g["game_id"])
        game.status = Game.STATUS_READY
        match = Match.query.filter_by(opponent_team_id=team_x_id).first()
        match.status = Match.STATUS_ACTIVE
        db.session.commit()

    response = client.delete(
        "/api/teams/{}".format(team_x_id),
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 409
    body = response.get_json()["error"]
    assert body["code"] == "TEAM_DELETE_BLOCKED_MATCH_REFERENCE"

    with app.app_context():
        assert db.session.get(Team, team_x_id) is not None
        assert Match.query.filter_by(opponent_team_id=team_x_id).count() == 1


def test_delete_team_detaches_historic_events(client, app):
    g = _create_game(client)
    team = _create_team(client, g["game_id"])
    team_id = team["team_id"]
    member = _add_member(client, team_id)
    member_id = member["member_id"]

    with app.app_context():
        db.session.add(
            GameEvent(
                game_id=g["game_id"],
                team_id=team_id,
                member_id=member_id,
                event_type="ROLE_CHANGED",
                event_data={"role": "MANGHUHULA"},
            )
        )
        db.session.commit()

    response = client.delete(
        "/api/teams/{}".format(team_id),
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 200

    with app.app_context():
        # Historical event rows are preserved, with FKs detached.
        events = GameEvent.query.filter_by(game_id=g["game_id"]).all()
        assert len(events) >= 1
        for event in events:
            assert event.team_id != team_id
            assert event.member_id != member_id
        assert db.session.get(Team, team_id) is None


# ---------------------------------------------------------------------------
# Member removal
# ---------------------------------------------------------------------------


def test_remove_member(client, app):
    g = _create_game(client)
    team = _create_team(client, g["game_id"])
    team_id = team["team_id"]
    member = _add_member(client, team_id)
    member_id = member["member_id"]

    leader_session = _leader_session(client, team)

    response = client.delete(
        "/api/members/{}".format(member_id),
        headers={"X-Session-Token": leader_session},
    )
    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(TeamMember, member_id) is None


def test_remove_member_detaches_game_events(client, app):
    g = _create_game(client)
    team = _create_team(client, g["game_id"])
    member = _add_member(client, team["team_id"], username="Elena")
    member_id = member["member_id"]

    with app.app_context():
        ev = GameEvent(
            game_id=g["game_id"],
            team_id=team["team_id"],
            member_id=member_id,
            event_type="TEST_EVENT",
        )
        db.session.add(ev)
        db.session.commit()
        event_id = ev.id

    leader_session = _leader_session(client, team)
    response = client.delete(
        "/api/members/{}".format(member_id),
        headers={"X-Session-Token": leader_session},
    )
    assert response.status_code == 200

    with app.app_context():
        assert db.session.get(TeamMember, member_id) is None
        event = db.session.get(GameEvent, event_id)
        # Historical event is retained and its member FK is detached (NULL).
        assert event is not None
        assert event.event_type == "TEST_EVENT"
        assert event.member_id is None

def test_remove_team_leader_rejected(client):
    g = _create_game(client)
    team = _create_team(client, g["game_id"])
    leader_id = team["leader"]["member_id"]

    response = client.delete(
        "/api/members/{}".format(leader_id),
        headers={HOST_TOKEN_HEADER: g["host_session_token"]},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Penalty revert
# ---------------------------------------------------------------------------


def _build_full_game(client, app):
    """Set up two teams with an active round/match/turn."""
    from app.services import gameplay_service, turn_service

    g = _create_game(client)
    host = g["host_session_token"]
    game_id = g["game_id"]

    # Create categories
    for name in ("Food", "Places"):
        client.post("/api/games/{}/categories".format(game_id),
                    json={"name": name},
                    headers={HOST_TOKEN_HEADER: host})

    # Create teams
    team_a = _create_team(client, game_id, team_name="Team A", username="A",
                           host_token=host)
    team_b = _create_team(client, game_id, team_name="Team B", username="B",
                           host_token=host)

    return {
        "client": client, "app": app, "host": host, "game_id": game_id,
        "team_a": team_a, "team_b": team_b,
    }
