from datetime import timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import Game, Match, Score, TeamMember, Turn, TurnWord
from app.utils.time import utcnow

HOST_TOKEN_HEADER = "X-Host-Token"
SESSION_TOKEN_HEADER = "X-Session-Token"

MANGHUHULA = TeamMember.GAMEPLAY_ROLE_MANGHUHULA
TAGASAGOT = TeamMember.GAMEPLAY_ROLE_TAGASAGOT
CORRECT = TurnWord.RESULT_CORRECT
PASSED = TurnWord.RESULT_PASSED


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


def _create_game(client):
    response = client.post("/api/games")
    assert response.status_code == 201
    data = response.get_json()["data"]
    return data["game_id"], data["host_session_token"]


def _create_team(client, game_id, name="Team A", username=None):
    response = client.post(
        "/api/games/{}/teams".format(game_id),
        json={"team_name": name, "username": username or name.split()[-1]},
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _add_member(client, team_id, username):
    response = client.post(
        "/api/teams/{}/members".format(team_id), json={"username": username}
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _connect(client, member, device_id="dev"):
    response = client.post(
        "/api/devices/connect",
        json={"connection_token": member["connection_token"], "device_id": device_id},
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _create_category(client, game_id, host_token, name):
    response = client.post(
        "/api/games/{}/categories".format(game_id),
        json={"name": name},
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 201
    return response.get_json()["data"]["category_id"]


def _submit_words(client, game_id, team_id, category_id, words, session_token=None):
    ids = []
    for word in words:
        headers = {}
        if session_token is not None:
            headers[SESSION_TOKEN_HEADER] = session_token
        response = client.post(
            "/api/games/{}/words".format(game_id),
            json={
                "team_id": team_id,
                "category_id": category_id,
                "word_text": word,
            },
            headers=headers,
        )
        assert response.status_code == 201
        ids.append(response.get_json()["data"]["word_id"])
    return ids


def _assign_roles(client, team, roles, token):
    response = client.post(
        "/api/teams/{}/roles".format(team["team_id"]),
        json={
            "roles": [
                {"member_id": member_id, "gameplay_role": role}
                for member_id, role in roles
            ]
        },
        headers={HOST_TOKEN_HEADER: token},
    )
    assert response.status_code == 200
    return response


def _create_matches(client, game_id, host, round_number, matches):
    return client.post(
        "/api/games/{}/matches".format(game_id),
        json={"round_number": round_number, "matches": matches},
        headers={HOST_TOKEN_HEADER: host},
    )


def _assign_turn_words(client, host, match_id, word_ids=None, count=None):
    body = {}
    if word_ids is not None:
        body["word_ids"] = word_ids
    if count is not None:
        body["count"] = count
    response = client.post(
        "/api/matches/{}/turns".format(match_id),
        json=body,
        headers={HOST_TOKEN_HEADER: host},
    )
    return response


def _setup(client, assign_roles=True):
    game_id, host = _create_game(client)
    team_a = _create_team(client, game_id, "Team A")
    team_b = _create_team(client, game_id, "Team B")
    leader_a = team_a["leader"]
    leader_b = team_b["leader"]
    sess_a = _connect(client, leader_a)["session_token"]
    sess_b = _connect(client, leader_b)["session_token"]
    member_a = _add_member(client, team_a["team_id"], "Maria")
    member_b = _add_member(client, team_b["team_id"], "Kris")

    cats = [
        _create_category(client, game_id, host, "Food"),
        _create_category(client, game_id, host, "Animals"),
    ]
    words_a0 = _submit_words(
        client, game_id, team_a["team_id"], cats[0], ["a01", "a02", "a03", "a04", "a05"], sess_a
    )
    words_b0 = _submit_words(
        client, game_id, team_b["team_id"], cats[0], ["b01", "b02", "b03", "b04", "b05"], sess_b
    )
    words_a1 = _submit_words(
        client, game_id, team_a["team_id"], cats[1], ["a11", "a12", "a13", "a14", "a15"], sess_a
    )
    words_b1 = _submit_words(
        client, game_id, team_b["team_id"], cats[1], ["b11", "b12", "b13", "b14", "b15"], sess_b
    )

    if assign_roles:
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

    assert client.post(
        "/api/games/{}/rounds".format(game_id),
        json={"round_number": 1},
        headers={HOST_TOKEN_HEADER: host},
    ).status_code == 201
    assert client.post(
        "/api/games/{}/rounds/1/categories".format(game_id),
        json={"category_ids": cats},
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
        leader_a=leader_a,
        leader_b=leader_b,
        sess_a=sess_a,
        sess_b=sess_b,
        member_a=member_a,
        member_b=member_b,
        cats=cats,
        words_a0=words_a0,
        words_b0=words_b0,
        words_a1=words_a1,
        words_b1=words_b1,
        match_a=match_a,
        match_b=match_b,
    )


def _donor_words(s, match):
    return s.words_b0 if match["team_id"] == s.team_a["team_id"] else s.words_a0


def _play_match(client, s, match, action, words=None):
    donor = _donor_words(s, match)
    if words is None:
        words = donor[:3]
    resp = _assign_turn_words(client, s.host, match["match_id"], word_ids=words)
    assert resp.status_code == 201
    turn_id = resp.get_json()["data"]["turn_id"]
    response = client.post(
        "/api/matches/{}/turn/start".format(match["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    for _ in range(len(words)):
        response = client.post(
            "/api/turns/{}/{}".format(turn_id, action),
            headers={HOST_TOKEN_HEADER: s.host},
        )
        assert response.status_code == 200
    return turn_id, words


# ---------------------------------------------------------------------------
# Start turn
# ---------------------------------------------------------------------------


def test_start_turn_activates_turn(client):
    s = _setup(client)
    donor = s.words_b0[:3]
    turn = _assign_turn_words(client, s.host, s.match_a["match_id"], word_ids=donor).get_json()["data"]
    response = client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["turn_id"] == turn["turn_id"]
    assert data["status"] == Turn.STATUS_ACTIVE
    assert data["starting_seconds"] == 60
    assert 0 < data["remaining_seconds"] <= 60
    assert data["current_word_text"] == "b01"
    assert data["correct_words"] == 0
    assert data["match_status"] == Match.STATUS_ACTIVE


def test_start_turn_unknown_match(client):
    response = client.post(
        "/api/matches/999999/turn/start", headers={HOST_TOKEN_HEADER: "x"}
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "MATCH_NOT_FOUND"


def test_start_turn_requires_auth(client):
    s = _setup(client)
    donor = s.words_b0[:3]
    _assign_turn_words(client, s.host, s.match_a["match_id"], word_ids=donor)
    response = client.post("/api/matches/{}/turn/start".format(s.match_a["match_id"]))
    assert response.status_code == 401


def test_start_turn_rejects_missing_roles(client):
    s = _setup(client, assign_roles=False)
    donor = s.words_b0[:3]
    _assign_turn_words(client, s.host, s.match_a["match_id"], word_ids=donor)
    response = client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ROLES_NOT_ASSIGNED"


def test_start_turn_rejects_without_words(client):
    s = _setup(client)
    response = client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "NO_TURN_AVAILABLE"


def test_start_turn_duplicate_active_turn(client):
    s = _setup(client)
    donor = s.words_b0[:3]
    _assign_turn_words(client, s.host, s.match_a["match_id"], word_ids=donor)
    _assign_turn_words(client, s.host, s.match_a["match_id"], word_ids=s.words_b1[:3])
    first = client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "DUPLICATE_ACTIVE_TURN"


def test_start_turn_with_team_session(client):
    s = _setup(client)
    donor = s.words_b0[:3]
    _assign_turn_words(client, s.host, s.match_a["match_id"], word_ids=donor)
    session = _connect(client, s.leader_a)
    response = client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={SESSION_TOKEN_HEADER: session["session_token"]},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Correct
# ---------------------------------------------------------------------------


def test_correct_moves_to_next_word_and_scores(client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:3]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    response = client.post(
        "/api/turns/{}/correct".format(turn["turn_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == Turn.STATUS_ACTIVE
    assert data["current_word_text"] == "b02"
    assert data["correct_words"] == 1
    assert data["words"][0]["result"] == CORRECT
    assert data["outcome"]["won"] is False
    scores = client.get(
        "/api/games/{}/scores".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]["scores"]
    assert len(scores) == 1
    assert scores[0]["team_id"] == s.team_a["team_id"]
    assert scores[0]["points"] == 1
    assert scores[0]["correct_words"] == 1


def test_correct_requires_host(client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:3]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    session = _connect(client, s.leader_a)
    response = client.post(
        "/api/turns/{}/correct".format(turn["turn_id"]),
        headers={SESSION_TOKEN_HEADER: session["session_token"]},
    )
    assert response.status_code == 401


def test_correct_unknown_turn(client):
    response = client.post(
        "/api/turns/999999/correct", headers={HOST_TOKEN_HEADER: "x"}
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "TURN_NOT_FOUND"


def test_correct_when_not_active(client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:3]
    ).get_json()["data"]
    response = client.post(
        "/api/turns/{}/correct".format(turn["turn_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "TURN_NOT_ACTIVE"


# ---------------------------------------------------------------------------
# Win condition
# ---------------------------------------------------------------------------


def test_three_correct_completes_turn_and_wins_match(app, client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:4]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    response = None
    for _ in range(3):
        response = client.post(
            "/api/turns/{}/correct".format(turn["turn_id"]),
            headers={HOST_TOKEN_HEADER: s.host},
        )
        assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == Turn.STATUS_COMPLETED
    assert data["correct_words"] == 3
    assert data["outcome"]["won"] is True
    assert data["match_status"] == Match.STATUS_COMPLETED
    assert data["match_winner_team_id"] == s.team_a["team_id"]
    assert data["words"][3]["result"] == TurnWord.RESULT_PENDING

    with app.app_context():
        score = (
            db.session.query(Score)
            .filter_by(game_id=s.game_id, match_id=s.match_a["match_id"])
            .one()
        )
        assert score.points == 3
        assert score.correct_words == 3


def test_pairing_resolves_winner_when_opponent_fails(client):
    s = _setup(client)
    turn_b = _assign_turn_words(
        client, s.host, s.match_b["match_id"], word_ids=s.words_a0[:3]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_b["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    for _ in range(3):
        assert client.post(
            "/api/turns/{}/correct".format(turn_b["turn_id"]),
            headers={HOST_TOKEN_HEADER: s.host},
        ).status_code == 200

    turn_a = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[3:5]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    response = None
    for _ in range(2):
        response = client.post(
            "/api/turns/{}/correct".format(turn_a["turn_id"]),
            headers={HOST_TOKEN_HEADER: s.host},
        )
        assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == Turn.STATUS_COMPLETED
    assert data["outcome"]["won"] is False
    pairing = data["outcome"]["pairing"]
    assert pairing is not None
    assert pairing["tie"] is False
    assert pairing["winner_team_id"] == s.team_b["team_id"]


# ---------------------------------------------------------------------------
# Pass
# ---------------------------------------------------------------------------


def test_pass_moves_to_next_word_zero_points(app, client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:3]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    response = client.post(
        "/api/turns/{}/pass".format(turn["turn_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == Turn.STATUS_ACTIVE
    assert data["current_word_text"] == "b02"
    assert data["passed_words"] == 1
    assert data["correct_words"] == 0
    assert data["words"][0]["result"] == PASSED
    with app.app_context():
        score = (
            db.session.query(Score)
            .filter_by(game_id=s.game_id, match_id=s.match_a["match_id"])
            .one()
        )
        assert score.points == 0
        assert score.passed_words == 1


def test_passed_word_cannot_return(client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:3]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert client.post(
        "/api/turns/{}/pass".format(turn["turn_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 200
    passed_id = s.words_b0[0]
    assert client.post(
        "/api/turns/{}/correct".format(turn["turn_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 200
    data = client.get(
        "/api/turns/{}".format(turn["turn_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]
    assert data["current_word_id"] != passed_id
    assert data["words"][0]["result"] == PASSED
    assert data["correct_words"] == 1


def test_pass_allowed_with_team_session(client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:3]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    session = _connect(client, s.leader_a)
    response = client.post(
        "/api/turns/{}/pass".format(turn["turn_id"]),
        headers={SESSION_TOKEN_HEADER: session["session_token"]},
    )
    assert response.status_code == 200


def test_pass_when_not_active(client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:3]
    ).get_json()["data"]
    response = client.post(
        "/api/turns/{}/pass".format(turn["turn_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "TURN_NOT_ACTIVE"


# ---------------------------------------------------------------------------
# Word exhaustion (no win)
# ---------------------------------------------------------------------------


def test_turn_ends_without_win_when_words_exhausted(client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:2]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    response = None
    for _ in range(2):
        response = client.post(
            "/api/turns/{}/correct".format(turn["turn_id"]),
            headers={HOST_TOKEN_HEADER: s.host},
        )
        assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == Turn.STATUS_COMPLETED
    assert data["correct_words"] == 2
    assert data["outcome"]["won"] is False
    assert data["match_status"] == Match.STATUS_COMPLETED
    assert data["match_winner_team_id"] is None


def test_no_turn_available_after_all_played(app, client):
    s = _setup(client)
    _play_match(client, s, s.match_a, "correct", words=s.words_b0[:2])
    with app.app_context():
        match = db.session.get(Match, s.match_a["match_id"])
        match.status = Match.STATUS_PENDING
        db.session.commit()
    response = client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "NO_TURN_AVAILABLE"


# ---------------------------------------------------------------------------
# Word limit
# ---------------------------------------------------------------------------


def test_word_ids_over_limit_rejected(client):
    s = _setup(client)
    too_many = s.words_b0 + s.words_b1[:1]
    response = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=too_many
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "WORD_LIMIT_EXCEEDED"


def test_random_count_over_limit_rejected(client):
    s = _setup(client)
    response = _assign_turn_words(
        client, s.host, s.match_a["match_id"], count=6
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "WORD_LIMIT_EXCEEDED"


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_explicit_timeout_endpoint(client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:3]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    response = client.post(
        "/api/turns/{}/timeout".format(turn["turn_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == Turn.STATUS_TIMEOUT
    assert data["remaining_seconds"] == 0
    assert data["correct_words"] == 0
    assert data["match_status"] == Match.STATUS_COMPLETED
    scores = client.get(
        "/api/games/{}/scores".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]["scores"]
    assert scores == []


def test_timeout_requires_host(client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:3]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    response = client.post(
        "/api/turns/{}/timeout".format(turn["turn_id"]),
        headers={SESSION_TOKEN_HEADER: "bogus"},
    )
    assert response.status_code == 401


def test_lazy_timeout_blocks_correct(app, client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:3]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    with app.app_context():
        row = db.session.get(Turn, turn["turn_id"])
        row.started_at = utcnow() - timedelta(seconds=61)
        db.session.commit()
    response = client.post(
        "/api/turns/{}/correct".format(turn["turn_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "TURN_TIMED_OUT"
    data = client.get(
        "/api/turns/{}".format(turn["turn_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]
    assert data["status"] == Turn.STATUS_TIMEOUT
    assert data["correct_words"] == 0


# ---------------------------------------------------------------------------
# Tie detection & tie-breaker
# ---------------------------------------------------------------------------


def test_tie_break_created_when_both_win(client):
    s = _setup(client)
    _play_match(client, s, s.match_a, "correct", words=s.words_b0[:3])
    response = None
    donor = s.words_a0[:3]
    turn = _assign_turn_words(
        client, s.host, s.match_b["match_id"], word_ids=donor
    ).get_json()["data"]
    assert client.post(
        "/api/matches/{}/turn/start".format(s.match_b["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 200
    for _ in range(3):
        response = client.post(
            "/api/turns/{}/correct".format(turn["turn_id"]),
            headers={HOST_TOKEN_HEADER: s.host},
        )
        assert response.status_code == 200
    data = response.get_json()["data"]
    pairing = data["outcome"]["pairing"]
    assert pairing is not None
    assert pairing["tie"] is True
    assert pairing["created"] is True
    tie_id = pairing["tie_breaker_match_id"]
    assert tie_id is not None

    listed = client.get(
        "/api/games/{}/matches".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]["matches"]
    tie = next(m for m in listed if m["match_id"] == tie_id)
    assert tie["round_number"] == 3
    assert tie["team_id"] == s.team_a["team_id"]
    assert tie["opponent_team_id"] == s.team_b["team_id"]


def test_tie_breaker_match_is_playable(client):
    s = _setup(client)
    _play_match(client, s, s.match_a, "correct", words=s.words_b0[:3])
    donor = s.words_a0[:3]
    turn = _assign_turn_words(
        client, s.host, s.match_b["match_id"], word_ids=donor
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_b["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    last = None
    for _ in range(3):
        last = client.post(
            "/api/turns/{}/correct".format(turn["turn_id"]),
            headers={HOST_TOKEN_HEADER: s.host},
        )
    tie_id = last.get_json()["data"]["outcome"]["pairing"]["tie_breaker_match_id"]

    tie_turn = _assign_turn_words(
        client, s.host, tie_id, word_ids=s.words_b1[:3]
    ).get_json()["data"]
    assert client.post(
        "/api/matches/{}/turn/start".format(tie_id),
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 200
    last = None
    for _ in range(3):
        last = client.post(
            "/api/turns/{}/correct".format(tie_turn["turn_id"]),
            headers={HOST_TOKEN_HEADER: s.host},
        )
    assert last.status_code == 200
    data = last.get_json()["data"]
    assert data["status"] == Turn.STATUS_COMPLETED
    assert data["match_status"] == Match.STATUS_COMPLETED
    assert data["match_winner_team_id"] == s.team_a["team_id"]


def test_get_turn_state(client):
    s = _setup(client)
    turn = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b0[:3]
    ).get_json()["data"]
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    response = client.get(
        "/api/turns/{}".format(turn["turn_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == Turn.STATUS_ACTIVE
    assert len(data["words"]) == 3
    assert data["total_words"] == 3