from datetime import timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import Match, Penalty, Round, Score, TeamMember, Turn
from app.utils.time import utcnow
from test_turns import (
    HOST_TOKEN_HEADER,
    MANGHUHULA,
    TAGASAGOT,
    _add_member,
    _assign_roles,
    _assign_turn_words,
    _connect,
    _create_category,
    _create_game,
    _create_matches,
    _create_team,
    _submit_words,
)

MAX_TIMER = 300


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


class Setup:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _setup(client, timer_seconds=60, timer_mode=Round.TIMER_MODE_COUNTDOWN):
    game_id, host = _create_game(client)
    team_a = _create_team(client, game_id, "Team A")
    team_b = _create_team(client, game_id, "Team B")
    leader_a = team_a["leader"]
    leader_b = team_b["leader"]
    sess_a = _connect(client, leader_a)["session_token"]
    sess_b = _connect(client, leader_b)["session_token"]
    member_a = _add_member(client, team_a["team_id"], "Maria")
    member_b = _add_member(client, team_b["team_id"], "Kris")

    cat = _create_category(client, game_id, host, "Food")
    words_a0 = _submit_words(
        client, game_id, team_a["team_id"], cat, ["a01", "a02", "a03", "a04", "a05"], sess_a
    )
    words_b0 = _submit_words(
        client, game_id, team_b["team_id"], cat, ["b01", "b02", "b03", "b04", "b05"], sess_b
    )

    _assign_roles(
        client,
        team_a,
        [(leader_a["member_id"], MANGHUHULA), (member_a["member_id"], TAGASAGOT)],
        host,
    )
    _assign_roles(
        client,
        team_b,
        [(leader_b["member_id"], MANGHUHULA), (member_b["member_id"], TAGASAGOT)],
        host,
    )

    resp = client.post(
        "/api/games/{}/rounds".format(game_id),
        json={
            "round_number": 1,
            "timer_seconds": timer_seconds,
            "timer_mode": timer_mode,
        },
        headers={HOST_TOKEN_HEADER: host},
    )
    assert resp.status_code == 201
    assert client.post(
        "/api/games/{}/rounds/1/categories".format(game_id),
        json={"category_ids": [cat]},
        headers={HOST_TOKEN_HEADER: host},
    ).status_code == 200
    resp = _create_matches(
        client,
        game_id,
        host,
        1,
        [
            {"team_id": team_a["team_id"], "opponent_team_id": team_b["team_id"]},
            {"team_id": team_b["team_id"], "opponent_team_id": team_a["team_id"]},
        ],
    )
    assert resp.status_code == 201
    matches = resp.get_json()["data"]["matches"]
    match_a = next(m for m in matches if m["team_id"] == team_a["team_id"])
    match_b = next(m for m in matches if m["team_id"] == team_b["team_id"])

    return Setup(
        game_id=game_id,
        host=host,
        team_a=team_a,
        team_b=team_b,
        member_a=member_a,
        words_a0=words_a0,
        words_b0=words_b0,
        match_a=match_a,
        match_b=match_b,
    )


def _add_turn(client, s, match, count=3):
    donor = s.words_b0 if match["team_id"] == s.team_a["team_id"] else s.words_a0
    resp = _assign_turn_words(
        client, s.host, match["match_id"], word_ids=donor[:count]
    )
    assert resp.status_code == 201
    return resp.get_json()["data"]["turn_id"]


def _start(client, s, match):
    resp = client.post(
        "/api/matches/{}/turn/start".format(match["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]


def _get_turn(client, s, turn_id):
    return client.get(
        "/api/turns/{0}".format(turn_id), headers={HOST_TOKEN_HEADER: s.host}
    )


def _backdate(app, turn_id, seconds):
    with app.app_context():
        turn = db.session.get(Turn, turn_id)
        turn.started_at = utcnow() - timedelta(seconds=seconds)
        db.session.commit()


def _turn_from_db(turn_id):
    return db.session.get(Turn, turn_id)


# ---------------------------------------------------------------------------
# Configuration: 5-minute maximum
# ---------------------------------------------------------------------------


def test_round_timer_never_exceeds_300(app, client):
    game_id, host = _create_game(client)
    response = client.post(
        "/api/games/{0}/rounds".format(game_id),
        json={"round_number": 1, "timer_seconds": 301},
        headers={HOST_TOKEN_HEADER: host},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "TIMER_CONFIG_INVALID"

    response = client.post(
        "/api/games/{0}/rounds".format(game_id),
        json={"round_number": 1, "timer_seconds": MAX_TIMER},
        headers={HOST_TOKEN_HEADER: host},
    )
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["timer_seconds"] == MAX_TIMER
    assert data["timer_mode"] == Round.TIMER_MODE_COUNTDOWN


def test_round_timer_config_validation(app, client):
    game_id, host = _create_game(client)
    for seconds in (0, -5):
        response = client.post(
            "/api/games/{0}/rounds".format(game_id),
            json={"round_number": 1, "timer_seconds": seconds},
            headers={HOST_TOKEN_HEADER: host},
        )
        assert response.status_code == 400
    response = client.post(
        "/api/games/{0}/rounds".format(game_id),
        json={"round_number": 2, "timer_seconds": 60, "timer_mode": "STOPWATCH"},
        headers={HOST_TOKEN_HEADER: host},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "TIMER_CONFIG_INVALID"


# ---------------------------------------------------------------------------
# Countdown
# ---------------------------------------------------------------------------


def test_countdown_decrements_from_configured_time(app, client):
    s = _setup(client, timer_seconds=120)
    turn_id = _add_turn(client, s, s.match_a)
    data = _start(client, s, s.match_a)
    assert data["timer_mode"] == Round.TIMER_MODE_COUNTDOWN
    assert data["starting_seconds"] == 120
    assert data["remaining_seconds"] in (119, 120)
    assert data["elapsed_seconds"] == 0

    _backdate(app, turn_id, 5)
    data = _get_turn(client, s, turn_id).get_json()["data"]
    assert 113 <= data["remaining_seconds"] <= 116
    assert 4 <= data["elapsed_seconds"] <= 6


# ---------------------------------------------------------------------------
# Count-up
# ---------------------------------------------------------------------------


def test_countup_increments_toward_configured_time(app, client):
    s = _setup(client, timer_seconds=120, timer_mode=Round.TIMER_MODE_COUNTUP)
    turn_id = _add_turn(client, s, s.match_a)
    data = _start(client, s, s.match_a)
    assert data["timer_mode"] == Round.TIMER_MODE_COUNTUP
    assert data["elapsed_seconds"] == 0
    assert data["remaining_seconds"] in (119, 120)

    _backdate(app, turn_id, 5)
    data = _get_turn(client, s, turn_id).get_json()["data"]
    assert 4 <= data["elapsed_seconds"] <= 6
    assert 113 <= data["remaining_seconds"] <= 116


# ---------------------------------------------------------------------------
# Pause / Resume
# ---------------------------------------------------------------------------


def test_pause_freezes_timer_until_resume(app, client):
    s = _setup(client, timer_seconds=60)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    _backdate(app, turn_id, 4)

    paused = client.post(
        "/api/turns/{0}/pause".format(turn_id), headers={HOST_TOKEN_HEADER: s.host}
    )
    assert paused.status_code == 200
    data = paused.get_json()["data"]
    assert data["status"] == Turn.STATUS_PAUSED
    assert data["paused_at"] is not None
    frozen_remaining = data["remaining_seconds"]
    frozen_elapsed = data["elapsed_seconds"]
    assert 55 <= frozen_remaining <= 57

    # Time passing while paused must not move the server clock.
    _backdate(app, turn_id, 8)
    data = _get_turn(client, s, turn_id).get_json()["data"]
    assert data["status"] == Turn.STATUS_PAUSED
    assert data["remaining_seconds"] == frozen_remaining
    assert data["elapsed_seconds"] == frozen_elapsed

    # Pausing again is invalid.
    again = client.post(
        "/api/turns/{0}/pause".format(turn_id), headers={HOST_TOKEN_HEADER: s.host}
    )
    assert again.status_code == 409
    assert again.get_json()["error"]["code"] == "TURN_NOT_ACTIVE"


def test_resume_restarts_countdown(app, client):
    s = _setup(client, timer_seconds=60)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    _backdate(app, turn_id, 4)
    client.post(
        "/api/turns/{0}/pause".format(turn_id), headers={HOST_TOKEN_HEADER: s.host}
    )

    resumed = client.post(
        "/api/turns/{0}/resume".format(turn_id), headers={HOST_TOKEN_HEADER: s.host}
    )
    assert resumed.status_code == 200
    data = resumed.get_json()["data"]
    assert data["status"] == Turn.STATUS_ACTIVE
    assert data["paused_at"] is None

    _backdate(app, turn_id, 3)
    data = _get_turn(client, s, turn_id).get_json()["data"]
    assert data["status"] == Turn.STATUS_ACTIVE
    assert 52 <= data["remaining_seconds"] <= 54

    again = client.post(
        "/api/turns/{0}/resume".format(turn_id), headers={HOST_TOKEN_HEADER: s.host}
    )
    assert again.status_code == 409
    assert again.get_json()["error"]["code"] == "TURN_NOT_ACTIVE"


# ---------------------------------------------------------------------------
# +3 seconds / -3 seconds and penalties
# ---------------------------------------------------------------------------


def test_time_add_three_seconds(app, client):
    s = _setup(client, timer_seconds=60)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    _backdate(app, turn_id, 2)
    before = _get_turn(client, s, turn_id).get_json()["data"]["remaining_seconds"]

    response = client.post(
        "/api/turns/{0}/time/add".format(turn_id),
        json={"seconds": 3, "reason": "Judge correction for the word."},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["adjustment_seconds"] == 3
    assert data["remaining_seconds"] == before + 3
    assert data["remaining_seconds"] > before

    with app.app_context():
        penalties = Penalty.query.filter_by(turn_id=turn_id).all()
        assert len(penalties) == 1
        assert penalties[0].type == Penalty.TYPE_ADD_TIME
        assert penalties[0].seconds == 3
        assert penalties[0].reason == "Judge correction for the word."
        score = Score.query.filter_by(
            match_id=_turn_from_db(turn_id).match_id
        ).first()
        assert score.time_bonus_seconds == 3


def test_time_remove_three_seconds(app, client):
    s = _setup(client, timer_seconds=60)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    _backdate(app, turn_id, 2)
    before = _get_turn(client, s, turn_id).get_json()["data"]["remaining_seconds"]

    response = client.post(
        "/api/turns/{0}/time/remove".format(turn_id),
        json={"seconds": 3, "reason": "Oo/Hindi misuse."},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["adjustment_seconds"] == -3
    assert data["remaining_seconds"] == before - 3
    assert data["remaining_seconds"] < before

    with app.app_context():
        penalty = Penalty.query.filter_by(turn_id=turn_id).first()
        assert penalty is not None
        assert penalty.type == Penalty.TYPE_REMOVE_TIME
        assert penalty.seconds == 3
        assert penalty.reason == "Oo/Hindi misuse."
        match_id = _turn_from_db(turn_id).match_id
        score = Score.query.filter_by(match_id=match_id).first()
        assert score.penalty_seconds == 3


def test_penalty_correction_restores_time(app, client):
    s = _setup(client, timer_seconds=85)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    _backdate(app, turn_id, 1)
    before = _get_turn(client, s, turn_id).get_json()["data"]["remaining_seconds"]
    assert before in (82, 83, 84)

    removed = client.post(
        "/api/turns/{0}/time/remove".format(turn_id),
        json={"seconds": 3},
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]
    assert removed["adjustment_seconds"] == -3
    assert removed["remaining_seconds"] == before - 3 or removed["remaining_seconds"] == before - 2

    added = client.post(
        "/api/turns/{0}/time/add".format(turn_id),
        json={"seconds": 3},
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]
    assert added["adjustment_seconds"] == 0
    assert before - 1 <= added["remaining_seconds"] <= before + 1

    with app.app_context():
        assert Penalty.query.filter_by(turn_id=turn_id).count() == 2
        score = Score.query.filter_by(match_id=_turn_from_db(turn_id).match_id).first()
        assert score.time_bonus_seconds == 3
        assert score.penalty_seconds == 3


# ---------------------------------------------------------------------------
# Timer reaching zero
# ---------------------------------------------------------------------------


def test_timer_reaching_zero_times_out(app, client):
    s = _setup(client, timer_seconds=5)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    _backdate(app, turn_id, 8)

    data = _get_turn(client, s, turn_id).get_json()["data"]
    assert data["remaining_seconds"] == 0

    response = client.post(
        "/api/turns/{0}/correct".format(turn_id), headers={HOST_TOKEN_HEADER: s.host}
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "TURN_TIMED_OUT"

    data = _get_turn(client, s, turn_id).get_json()["data"]
    assert data["status"] == Turn.STATUS_TIMEOUT
    assert data["remaining_seconds"] == 0
    assert data["match_status"] == Match.STATUS_COMPLETED
    assert data["match_winner_team_id"] is None


def test_removal_can_reach_zero_and_timeout(app, client):
    s = _setup(client, timer_seconds=60)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    _backdate(app, turn_id, 57)
    live = _get_turn(client, s, turn_id).get_json()["data"]["remaining_seconds"]
    assert 1 <= live <= 3

    response = client.post(
        "/api/turns/{0}/time/remove".format(turn_id),
        json={"seconds": live},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == Turn.STATUS_TIMEOUT
    assert data["remaining_seconds"] == 0
    assert data["match_status"] == Match.STATUS_COMPLETED


# ---------------------------------------------------------------------------
# Invalid timer modifications
# ---------------------------------------------------------------------------


def test_invalid_time_delta_rejected(app, client):
    s = _setup(client, timer_seconds=60)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)

    for body in ({}, {"seconds": 0}, {"seconds": -3}, {"seconds": "x"}):
        response = client.post(
            "/api/turns/{0}/time/add".format(turn_id),
            json=body,
            headers={HOST_TOKEN_HEADER: s.host},
        )
        assert response.status_code == 400, body
        assert response.get_json()["error"]["code"] == "INVALID_TIME_DELTA"


def test_remove_below_zero_rejected(app, client):
    s = _setup(client, timer_seconds=60)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    _backdate(app, turn_id, 58)
    assert 1 <= _get_turn(client, s, turn_id).get_json()["data"]["remaining_seconds"] <= 3

    response = client.post(
        "/api/turns/{0}/time/remove".format(turn_id),
        json={"seconds": 5},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "TIME_BELOW_ZERO"


def test_add_above_max_rejected(app, client):
    s = _setup(client, timer_seconds=MAX_TIMER)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    _backdate(app, turn_id, 1)
    before = _get_turn(client, s, turn_id).get_json()["data"]["remaining_seconds"]
    assert before <= MAX_TIMER - 1

    ok = client.post(
        "/api/turns/{0}/time/add".format(turn_id),
        json={"seconds": 1},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert ok.status_code == 200
    assert ok.get_json()["data"]["remaining_seconds"] == before + 1

    over = client.post(
        "/api/turns/{0}/time/add".format(turn_id),
        json={"seconds": 5},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert over.status_code == 400
    assert over.get_json()["error"]["code"] == "TIME_ABOVE_MAX"


def test_timer_controls_require_active_turn(app, client):
    s = _setup(client, timer_seconds=60)
    turn_id = _add_turn(client, s, s.match_a)

    for path in ("pause", "resume", "time/add", "time/remove", "end"):
        response = client.post(
            "/api/turns/{0}/{1}".format(turn_id, path),
            json={"seconds": 3},
            headers={HOST_TOKEN_HEADER: s.host},
        )
        assert response.status_code == 409, path
        assert response.get_json()["error"]["code"] == "TURN_NOT_ACTIVE", path


def test_timer_controls_are_host_only(app, client):
    s = _setup(client, timer_seconds=60)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    session = _connect(client, s.member_a, "dev-timer")
    headers = {"X-Session-Token": session["session_token"]}

    response = client.post("/api/turns/{0}/pause".format(turn_id), headers=headers)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Server authority
# ---------------------------------------------------------------------------


def test_client_timer_values_are_ignored(app, client):
    s = _setup(client, timer_seconds=60)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    _backdate(app, turn_id, 5)
    real = _get_turn(client, s, turn_id).get_json()["data"]["remaining_seconds"]
    assert real < 60

    response = client.post(
        "/api/turns/{0}/time/add".format(turn_id),
        json={
            "seconds": 1,
            "remaining_seconds": 999,
            "timer_seconds": 999,
            "elapsed_seconds": 999,
        },
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["remaining_seconds"] == real + 1
    assert data["elapsed_seconds"] <= 6
    assert data["remaining_seconds"] != 1000


# ---------------------------------------------------------------------------
# Host /end
# ---------------------------------------------------------------------------


def test_host_end_ends_turn_without_win(app, client):
    s = _setup(client, timer_seconds=60)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    _backdate(app, turn_id, 2)

    response = client.post(
        "/api/turns/{0}/end".format(turn_id), headers={HOST_TOKEN_HEADER: s.host}
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == Turn.STATUS_TIMEOUT
    assert data["remaining_seconds"] > 0
    assert data["match_status"] == Match.STATUS_COMPLETED
    assert data["match_winner_team_id"] is None

    with app.app_context():
        match_id = _turn_from_db(turn_id).match_id
        score = Score.query.filter_by(match_id=match_id).first()
        assert score is not None
        assert score.points == 0
        assert score.failed_words > 0


def test_timer_controls_are_server_authoritative_on_resume(app, client):
    s = _setup(client, timer_seconds=60)
    turn_id = _add_turn(client, s, s.match_a)
    _start(client, s, s.match_a)
    _backdate(app, turn_id, 4)
    client.post(
        "/api/turns/{0}/pause".format(turn_id), headers={HOST_TOKEN_HEADER: s.host}
    )
    _backdate(app, turn_id, 30)
    client.post(
        "/api/turns/{0}/time/add".format(turn_id),
        json={"seconds": 999},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert client.post(
        "/api/turns/{0}/resume".format(turn_id), headers={HOST_TOKEN_HEADER: s.host}
    ).status_code == 200