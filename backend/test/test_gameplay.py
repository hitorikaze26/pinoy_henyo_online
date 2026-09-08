import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Category,
    Game,
    Match,
    Round,
    Score,
    TeamMember,
    Turn,
    TurnWord,
)
from app.services import gameplay_service

HOST_TOKEN_HEADER = "X-Host-Token"
SESSION_TOKEN_HEADER = "X-Session-Token"

MANGHUHULA = TeamMember.GAMEPLAY_ROLE_MANGHUHULA
TAGASAGOT = TeamMember.GAMEPLAY_ROLE_TAGASAGOT


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


def _connect(client, connection_token, device_id="dev"):
    response = client.post(
        "/api/devices/connect",
        json={"connection_token": connection_token, "device_id": device_id},
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


def _submit_words(
    client, game_id, team_id, category_id, words, session_token=None
):
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


def _assign_roles(client, team, roles, token=None):
    body = {
        "roles": [
            {"member_id": member_id, "gameplay_role": role}
            for member_id, role in roles
        ]
    }
    headers = {}
    if token is not None:
        headers[HOST_TOKEN_HEADER] = token
    return client.post(
        "/api/teams/{}/roles".format(team["team_id"]),
        json=body,
        headers=headers,
    )


def _create_round(client, game_id, host_token, round_number, timer_seconds=None):
    body = {"round_number": round_number}
    if timer_seconds is not None:
        body["timer_seconds"] = timer_seconds
    return client.post(
        "/api/games/{}/rounds".format(game_id),
        json=body,
        headers={HOST_TOKEN_HEADER: host_token},
    )


def _select_categories(client, game_id, host_token, round_number, category_ids):
    return client.post(
        "/api/games/{}/rounds/{}/categories".format(game_id, round_number),
        json={"category_ids": category_ids},
        headers={HOST_TOKEN_HEADER: host_token},
    )


def _create_matches(client, game_id, host_token, round_number, matches):
    return client.post(
        "/api/games/{}/matches".format(game_id),
        json={"round_number": round_number, "matches": matches},
        headers={HOST_TOKEN_HEADER: host_token},
    )


def _assign_turn_words(
    client, host_token, match_id, word_ids=None, count=None
):
    body = {}
    if word_ids is not None:
        body["word_ids"] = word_ids
    if count is not None:
        body["count"] = count
    return client.post(
        "/api/matches/{}/turns".format(match_id),
        json=body,
        headers={HOST_TOKEN_HEADER: host_token},
    )


def _basic_setup(client):
    game_id, host = _create_game(client)
    team_a = _create_team(client, game_id, "Team A")
    team_b = _create_team(client, game_id, "Team B")
    sess_a = _connect(client, team_a["leader"]["connection_token"])[
        "session_token"
    ]
    sess_b = _connect(client, team_b["leader"]["connection_token"])[
        "session_token"
    ]
    return Setup(
        game_id=game_id,
        host=host,
        team_a=team_a,
        team_b=team_b,
        leader_a=team_a["leader"],
        leader_b=team_b["leader"],
        sess_a=sess_a,
        sess_b=sess_b,
    )


def _full_setup(client, cat_count=2):
    s = _basic_setup(client)
    s.member_a = _add_member(client, s.team_a["team_id"], "Maria")
    s.member_b = _add_member(client, s.team_b["team_id"], "Kris")
    s.cats = [
        _create_category(client, s.game_id, s.host, "Cat{}".format(i))
        for i in range(cat_count)
    ]
    s.words_a = {}
    s.words_b = {}
    for index, cat_id in enumerate(s.cats):
        s.words_a[cat_id] = _submit_words(
            client, s.game_id, s.team_a["team_id"], cat_id, ["A{}{}".format(index, n) for n in range(1, 4)], s.sess_a
        )
        s.words_b[cat_id] = _submit_words(
            client, s.game_id, s.team_b["team_id"], cat_id, ["B{}{}".format(index, n) for n in range(1, 4)], s.sess_b
        )
    assert _assign_roles(
        client,
        s.team_a,
        [
            (s.leader_a["member_id"], MANGHUHULA),
            (s.member_a["member_id"], TAGASAGOT),
        ],
        token=s.host,
    ).status_code == 200
    assert _assign_roles(
        client,
        s.team_b,
        [
            (s.leader_b["member_id"], MANGHUHULA),
            (s.member_b["member_id"], TAGASAGOT),
        ],
        token=s.host,
    ).status_code == 200
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    assert _create_round(client, s.game_id, s.host, 2).status_code == 201
    assert _select_categories(
        client, s.game_id, s.host, 1, [s.cats[0]]
    ).status_code == 200
    assert _create_matches(
        client,
        s.game_id,
        s.host,
        1,
        [{"team_id": s.team_a["team_id"], "opponent_team_id": s.team_b["team_id"]}],
    ).status_code == 201
    assert _create_matches(
        client,
        s.game_id,
        s.host,
        2,
        [{"team_id": s.team_a["team_id"], "opponent_team_id": s.team_b["team_id"]}],
    ).status_code == 201
    matches = client.get(
        "/api/games/{}/matches".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]["matches"]
    s.match_a = next(m for m in matches if m["round_number"] == 1)
    s.match_a_round2 = next(m for m in matches if m["round_number"] == 2)
    assert _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b[s.cats[0]][-1:]
    ).status_code == 201
    assert _assign_turn_words(
        client, s.host, s.match_a_round2["match_id"], word_ids=s.words_b[s.cats[1]][-1:]
    ).status_code == 201
    return s


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


def test_assign_roles_requires_auth(client):
    s = _basic_setup(client)
    response = _assign_roles(
        client, s.team_a, [(s.leader_a["member_id"], MANGHUHULA)]
    )
    assert response.status_code == 401


def test_list_matches_auto_sets_up_slots_as_soon_as_teams_join(client):
    """The dashboard's Current Turn dropdown lists teams the moment they
    join, so GET /games/<id>/matches must create the Round 1 play slots per
    team while the game is still in LOBBY (not only at SETUP/game start)."""
    game_id, host_token = _create_game(client)

    def _matches():
        response = client.get(
            "/api/games/{}/matches".format(game_id),
            headers={HOST_TOKEN_HEADER: host_token},
        )
        assert response.status_code == 200
        return response.get_json()["data"]["matches"]

    # A single team joining the LOBBY produces a Round-1 slot for it.
    team_a = _create_team(client, game_id, name="Alpha")
    matches = _matches()
    assert len(matches) == 1
    assert {m["team_id"] for m in matches} == {team_a["team_id"]}
    assert {m["round_number"] for m in matches} == {1}
    assert all(m["match_order"] >= 1 for m in matches)

    # A second team joining appends a slot for it too, and re-fetching is
    # idempotent (no duplicate slots accumulate across GETs).
    team_b = _create_team(client, game_id, name="Bravo")
    matches = _matches()
    assert len(matches) == 2
    assert {m["team_id"] for m in matches} == {
        team_a["team_id"],
        team_b["team_id"],
    }
    assert _matches() == matches

    # The auto-setup must not bump the game out of LOBBY.
    status = client.get(
        "/api/games/{}/status".format(game_id)
    ).get_json()["data"]["status"]
    assert status == Game.STATUS_LOBBY


def test_list_matches_after_start_creates_slot_for_late_team(client):
    """Teams that join AFTER the game starts must still get a play slot in
    the round being played, or the dashboard's Current Turn dropdown shows
    'No playing teams yet' with no way to pick them."""
    game_id, host_token = _create_game(client)

    # Start BEFORE any teams exist (no rounds created by start_game yet).
    started = client.post(
        "/api/games/{}/start".format(game_id),
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert started.status_code == 200, started.get_json()
    status = client.get(
        "/api/games/{}/status".format(game_id)
    ).get_json()["data"]["status"]
    assert status == Game.STATUS_READY

    # A late team gets a Round-1 slot once the dashboard lists matches.
    team_late = _create_team(client, game_id, name="Late Join")
    response = client.get(
        "/api/games/{}/matches".format(game_id),
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert response.status_code == 200
    matches = response.get_json()["data"]["matches"]
    assert {m["team_id"] for m in matches} == {team_late["team_id"]}
    assert {m["round_number"] for m in matches} == {1}
    assert all(m["status"] == Match.STATUS_PENDING for m in matches)

    # Idempotent: a second fetch does not duplicate the slot.
    again = client.get(
        "/api/games/{}/matches".format(game_id),
        headers={HOST_TOKEN_HEADER: host_token},
    )
    assert again.get_json()["data"]["matches"] == matches


def test_host_assigns_roles(client):
    s = _basic_setup(client)
    s.member_a = _add_member(client, s.team_a["team_id"], "Maria")
    response = _assign_roles(
        client,
        s.team_a,
        [
            (s.leader_a["member_id"], MANGHUHULA),
            (s.member_a["member_id"], TAGASAGOT),
        ],
        token=s.host,
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["leader"]["gameplay_role"] == MANGHUHULA
    assert len(data["leader"]["gameplay_role"]) > 0


def test_team_leader_can_assign_roles(client):
    s = _basic_setup(client)
    s.member_a = _add_member(client, s.team_a["team_id"], "Maria")
    session = _connect(client, s.leader_a["connection_token"], "dev-leader")
    response = client.post(
        "/api/teams/{}/roles".format(s.team_a["team_id"]),
        json={
            "roles": [
                {"member_id": s.member_a["member_id"], "gameplay_role": TAGASAGOT}
            ]
        },
        headers={SESSION_TOKEN_HEADER: session["session_token"]},
    )
    assert response.status_code == 200


def test_regular_member_cannot_assign_roles(client):
    s = _basic_setup(client)
    s.member_a = _add_member(client, s.team_a["team_id"], "Maria")
    session = _connect(client, s.member_a["connection_token"], "dev-member")
    response = client.post(
        "/api/teams/{}/roles".format(s.team_a["team_id"]),
        json={
            "roles": [{"member_id": s.leader_a["member_id"], "gameplay_role": MANGHUHULA}]
        },
        headers={SESSION_TOKEN_HEADER: session["session_token"]},
    )
    assert response.status_code == 401


def test_leader_session_cannot_assign_other_team_roles(client):
    s = _basic_setup(client)
    session = _connect(client, s.leader_a["connection_token"], "dev-leader")
    response = client.post(
        "/api/teams/{}/roles".format(s.team_b["team_id"]),
        json={
            "roles": [
                {"member_id": s.leader_b["member_id"], "gameplay_role": MANGHUHULA}
            ]
        },
        headers={SESSION_TOKEN_HEADER: session["session_token"]},
    )
    assert response.status_code == 401


def test_invalid_role_value(client):
    s = _basic_setup(client)
    response = _assign_roles(
        client, s.team_a, [(s.leader_a["member_id"], "DRAWER")], token=s.host
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "ROLE_INVALID"


def test_duplicate_manghuhula_rejected(client):
    s = _basic_setup(client)
    s.member_a = _add_member(client, s.team_a["team_id"], "Maria")
    assert _assign_roles(
        client, s.team_a, [(s.leader_a["member_id"], MANGHUHULA)], token=s.host
    ).status_code == 200
    response = _assign_roles(
        client, s.team_a, [(s.member_a["member_id"], MANGHUHULA)], token=s.host
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "DUPLICATE_MANGHUHULA"


def test_multiple_tagasagot_allowed(client):
    s = _basic_setup(client)
    s.member_a = _add_member(client, s.team_a["team_id"], "Maria")
    response = _assign_roles(
        client,
        s.team_a,
        [
            (s.leader_a["member_id"], TAGASAGOT),
            (s.member_a["member_id"], TAGASAGOT),
        ],
        token=s.host,
    )
    assert response.status_code == 200


def test_role_assignment_member_not_in_team(client):
    s = _basic_setup(client)
    response = _assign_roles(
        client, s.team_a, [(s.leader_b["member_id"], TAGASAGOT)], token=s.host
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "MEMBER_NOT_IN_TEAM"


def test_roles_locked_when_game_complete(app, client):
    s = _basic_setup(client)
    with app.app_context():
        game = db.session.get(Game, s.game_id)
        game.status = Game.STATUS_GAME_COMPLETE
        db.session.commit()
    response = _assign_roles(
        client, s.team_a, [(s.leader_a["member_id"], MANGHUHULA)], token=s.host
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "GAME_FROZEN"


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------


def test_create_round(client):
    s = _basic_setup(client)
    response = _create_round(client, s.game_id, s.host, 1, timer_seconds=90)
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["round_number"] == 1
    assert data["status"] == "PENDING"
    assert data["timer_seconds"] == 90
    assert data["selected_category_ids"] == []


def test_create_round_invalid_number(client):
    s = _basic_setup(client)
    response = _create_round(client, s.game_id, s.host, 4)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "ROUND_NUMBER_INVALID"


def test_create_round_round_three(client):
    s = _basic_setup(client)
    response = _create_round(client, s.game_id, s.host, 3)
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["round_number"] == 3
    assert data["status"] == "PENDING"
    assert data["timer_seconds"] == 60


def test_create_round_invalid_timer(client):
    s = _basic_setup(client)
    response = _create_round(client, s.game_id, s.host, 1, timer_seconds=0)
    assert response.status_code == 400


def test_create_round_duplicate(client):
    s = _basic_setup(client)
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = _create_round(client, s.game_id, s.host, 1)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ROUND_EXISTS"


def test_list_rounds(client):
    s = _basic_setup(client)
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    assert _create_round(client, s.game_id, s.host, 2).status_code == 201
    response = client.get(
        "/api/games/{}/rounds".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    rounds = response.get_json()["data"]["rounds"]
    assert [r["round_number"] for r in rounds] == [1, 2]


def test_rounds_require_host(client):
    s = _basic_setup(client)
    assert client.post(
        "/api/games/{}/rounds".format(s.game_id), json={"round_number": 1}
    ).status_code == 401


# ---------------------------------------------------------------------------
# Round category selection
# ---------------------------------------------------------------------------


def test_select_round1_categories(client):
    s = _basic_setup(client)
    s.cats = [
        _create_category(client, s.game_id, s.host, "Food"),
        _create_category(client, s.game_id, s.host, "Animals"),
    ]
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = _select_categories(client, s.game_id, s.host, 1, s.cats)
    assert response.status_code == 200
    assert response.get_json()["data"]["selected_category_ids"] == sorted(s.cats)


def test_select_categories_requires_selection(client):
    s = _basic_setup(client)
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = _select_categories(client, s.game_id, s.host, 1, [])
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "CATEGORIES_REQUIRED"


def test_select_category_not_in_game(client):
    s = _basic_setup(client)
    other_game_id, other_host = _create_game(client)
    other_cat = _create_category(client, other_game_id, other_host, "Food")
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = _select_categories(client, s.game_id, s.host, 1, [other_cat])
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "CATEGORY_NOT_IN_GAME"


def test_select_round2_allowed(client):
    s = _basic_setup(client)
    s.cat = _create_category(client, s.game_id, s.host, "Food")
    assert _create_round(client, s.game_id, s.host, 2).status_code == 201
    response = _select_categories(client, s.game_id, s.host, 2, [s.cat])
    assert response.status_code == 200
    assert response.get_json()["data"]["round_number"] == 2


def test_round1_lists_only_selected(client):
    s = _basic_setup(client)
    s.cats = [
        _create_category(client, s.game_id, s.host, "Food"),
        _create_category(client, s.game_id, s.host, "Animals"),
    ]
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    _select_categories(client, s.game_id, s.host, 1, [s.cats[0]])
    response = client.get(
        "/api/games/{}/rounds/1/categories".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    names = [c["name"] for c in response.get_json()["data"]["categories"]]
    assert names == ["Food"]


def test_round2_lists_all_categories(client):
    s = _basic_setup(client)
    s.cats = [
        _create_category(client, s.game_id, s.host, "Food"),
        _create_category(client, s.game_id, s.host, "Animals"),
    ]
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    assert _create_round(client, s.game_id, s.host, 2).status_code == 201
    _select_categories(client, s.game_id, s.host, 1, [s.cats[0]])
    response = client.get(
        "/api/games/{}/rounds/2/categories".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    names = [c["name"] for c in response.get_json()["data"]["categories"]]
    assert names == ["Animals", "Food"]


def test_round_categories_round_not_found(client):
    s = _basic_setup(client)
    response = client.get(
        "/api/games/{}/rounds/5/categories".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "ROUND_NOT_FOUND"


# ---------------------------------------------------------------------------
# Per-word round assignment
# ---------------------------------------------------------------------------


def test_select_categories_does_not_reassign_words(client):
    """The picker re-scopes rounds by category, not by word round field."""
    s = _basic_setup(client)
    s.cats = [
        _create_category(client, s.game_id, s.host, "Food"),
        _create_category(client, s.game_id, s.host, "Animals"),
    ]
    s.words_a = {
        c: _submit_words(
            client, s.game_id, s.team_a["team_id"], c, ["a{}".format(i)], s.sess_a
        )
        for i, c in enumerate(s.cats)
    }
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    assert _select_categories(
        client, s.game_id, s.host, 1, [s.cats[0]]
    ).status_code == 200

    words = client.get(
        "/api/games/{}/words".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]["words"]
    rounds = {w["word_text"]: w["assigned_round"] for w in words}
    # Round membership is category-driven now; selecting a category for
    # Round 1 must leave the per-word field alone.
    assert rounds["A0"] == 1
    assert rounds["A1"] == 1


def test_word_round_drives_round2_pool(client):
    s = _full_setup(client)
    # Enable only cats[1] for Round 2: the Round 2 pool must draw from it.
    assert _select_categories(
        client, s.game_id, s.host, 2, [s.cats[1]]
    ).status_code == 200

    # B13 was already assigned to the Round 2 match by the setup; the random
    # draw must stay inside cats[1] and never reuse a dealt word.
    response = _assign_turn_words(
        client, s.host, s.match_a_round2["match_id"], count=1
    )
    assert response.status_code == 201
    turn_words = {w["word_text"] for w in response.get_json()["data"]["words"]}
    assert len(turn_words) == 1
    assert next(iter(turn_words)).startswith("B1")


def test_word_round_change_rescopes_pool(client):
    s = _full_setup(client)
    assert _select_categories(
        client, s.game_id, s.host, 2, [s.cats[1]]
    ).status_code == 200
    target = s.words_b[s.cats[0]][0]  # a cats[0] word

    # Round 2 (enabled set cats[1]) must reject a cats[0] word.
    denied = _assign_turn_words(
        client, s.host, s.match_a_round2["match_id"], word_ids=[target]
    )
    assert denied.status_code == 409
    assert denied.get_json()["error"]["code"] == "WORD_NOT_IN_ROUND"

    # Round 1 (enabled set cats[0]) accepts it.
    ok = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=[target]
    )
    assert ok.status_code == 201


def test_readiness_detects_empty_round2(client):
    s = _basic_setup(client)
    s.cat = _create_category(client, s.game_id, s.host, "Food")
    s.empty_cat = _create_category(client, s.game_id, s.host, "Empty")
    _submit_words(
        client, s.game_id, s.team_a["team_id"], s.cat, ["apple"], s.sess_a
    )
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    assert _create_round(client, s.game_id, s.host, 2).status_code == 201
    _select_categories(client, s.game_id, s.host, 1, [s.cat])
    assert _select_categories(
        client, s.game_id, s.host, 2, [s.empty_cat]
    ).status_code == 200
    response = client.get(
        "/api/games/{}/readiness".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    issues = response.get_json()["data"]["issues"]
    assert any("Round 2 has no assigned words" in issue for issue in issues)


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------


def test_create_round_matches(client):
    s = _basic_setup(client)
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = _create_matches(
        client,
        s.game_id,
        s.host,
        1,
        [{"team_id": s.team_a["team_id"], "opponent_team_id": s.team_b["team_id"]}],
    )
    assert response.status_code == 201
    match = response.get_json()["data"]["matches"][0]
    assert match["match_order"] == 1
    assert match["team_id"] == s.team_a["team_id"]
    assert match["opponent_team_id"] == s.team_b["team_id"]
    assert match["round_number"] == 1


def test_create_matches_requires_entries(client):
    s = _basic_setup(client)
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = _create_matches(client, s.game_id, s.host, 1, [])
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "MATCHES_REQUIRED"


def test_create_matches_duplicate_team(client):
    s = _basic_setup(client)
    s.team_c = _create_team(client, s.game_id, "Team C", "Cece")
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = _create_matches(
        client,
        s.game_id,
        s.host,
        1,
        [
            {"team_id": s.team_a["team_id"], "opponent_team_id": s.team_b["team_id"]},
            {"team_id": s.team_a["team_id"], "opponent_team_id": s.team_c["team_id"]},
        ],
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "DUPLICATE_TEAM_IN_ROUND"


def test_create_matches_self_play(client):
    s = _basic_setup(client)
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = _create_matches(
        client,
        s.game_id,
        s.host,
        1,
        [{"team_id": s.team_a["team_id"], "opponent_team_id": s.team_a["team_id"]}],
    )
    assert response.status_code == 400


def test_create_matches_team_not_in_game(client):
    s = _basic_setup(client)
    other_game_id, _ = _create_game(client)
    other_team = _create_team(client, other_game_id, "Team X", "Xia")
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = _create_matches(
        client,
        s.game_id,
        s.host,
        1,
        [{"team_id": other_team["team_id"]}],
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "TEAM_NOT_IN_GAME"


def test_create_matches_existing_blocked(client):
    s = _basic_setup(client)
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    entries = [
        {"team_id": s.team_a["team_id"], "opponent_team_id": s.team_b["team_id"]}
    ]
    assert (
        _create_matches(client, s.game_id, s.host, 1, entries).status_code == 201
    )
    response = _create_matches(client, s.game_id, s.host, 1, entries)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "MATCHES_EXIST"


def test_create_matches_round_not_found(client):
    s = _basic_setup(client)
    response = _create_matches(
        client,
        s.game_id,
        s.host,
        2,
        [{"team_id": s.team_a["team_id"]}],
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "ROUND_NOT_FOUND"


def test_reorder_matches(client):
    s = _basic_setup(client)
    s.team_c = _create_team(client, s.game_id, "Team C", "Cece")
    s.team_d = _create_team(client, s.game_id, "Team D", "Dina")
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = _create_matches(
        client,
        s.game_id,
        s.host,
        1,
        [
            {"team_id": s.team_a["team_id"], "opponent_team_id": s.team_b["team_id"]},
            {"team_id": s.team_c["team_id"], "opponent_team_id": s.team_d["team_id"]},
        ],
    )
    matches = response.get_json()["data"]["matches"]
    first, second = matches[0]["match_id"], matches[1]["match_id"]
    response = client.patch(
        "/api/matches/{}".format(first),
        json={"match_order": 2},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["match_order"] == 2
    listed = client.get(
        "/api/games/{}/matches".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    ).get_json()["data"]["matches"]
    assert [m["match_id"] for m in listed] == [second, first]
    assert listed[0]["match_order"] == 1
    assert listed[1]["match_order"] == 2


def test_reorder_invalid_order(client):
    s = _basic_setup(client)
    s.team_c = _create_team(client, s.game_id, "Team C", "Cece")
    s.team_d = _create_team(client, s.game_id, "Team D", "Dina")
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = _create_matches(
        client,
        s.game_id,
        s.host,
        1,
        [
            {"team_id": s.team_a["team_id"], "opponent_team_id": s.team_b["team_id"]},
            {"team_id": s.team_c["team_id"], "opponent_team_id": s.team_d["team_id"]},
        ],
    )
    match_id = response.get_json()["data"]["matches"][0]["match_id"]
    response = client.patch(
        "/api/matches/{}".format(match_id),
        json={"match_order": 0},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "MATCH_ORDER_INVALID"


def test_reorder_locked_after_round_starts(app, client):
    s = _basic_setup(client)
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = _create_matches(
        client,
        s.game_id,
        s.host,
        1,
        [{"team_id": s.team_a["team_id"], "opponent_team_id": s.team_b["team_id"]}],
    )
    match_id = response.get_json()["data"]["matches"][0]["match_id"]
    with app.app_context():
        match = db.session.get(Match, match_id)
        match.round.status = "ACTIVE"
        db.session.commit()
    response = client.patch(
        "/api/matches/{}".format(match_id),
        json={"match_order": 1},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "MATCH_REORDER_LOCKED"


def test_matches_endpoints_require_host(client):
    s = _basic_setup(client)
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    assert client.post(
        "/api/games/{}/matches".format(s.game_id),
        json={"round_number": 1, "matches": []},
    ).status_code == 401


# ---------------------------------------------------------------------------
# Per-turn category pick (Round 1)
# ---------------------------------------------------------------------------


def test_select_match_category_by_team(client):
    s = _full_setup(client)
    response = client.post(
        "/api/matches/{}/category".format(s.match_a["match_id"]),
        json={"category_id": s.cats[0]},
        headers={SESSION_TOKEN_HEADER: s.sess_a},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["match_id"] == s.match_a["match_id"]
    assert data["category_id"] == s.cats[0]


def test_select_match_category_by_host(client):
    s = _full_setup(client)
    response = client.post(
        "/api/matches/{}/category".format(s.match_a["match_id"]),
        json={"category_id": s.cats[0]},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["category_id"] == s.cats[0]


def test_select_match_category_requires_auth(client):
    s = _full_setup(client)
    assert client.post(
        "/api/matches/{}/category".format(s.match_a["match_id"]),
        json={"category_id": s.cats[0]},
    ).status_code == 401


def test_select_match_category_rejects_disabled(client):
    s = _full_setup(client)
    # Round 1 enabled set is cats[0]; cats[1] must be rejected.
    response = client.post(
        "/api/matches/{}/category".format(s.match_a["match_id"]),
        json={"category_id": s.cats[1]},
        headers={SESSION_TOKEN_HEADER: s.sess_a},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ROUND_CATEGORY_NOT_ALLOWED"


def test_select_match_category_round2_not_allowed(client):
    s = _full_setup(client)
    response = client.post(
        "/api/matches/{}/category".format(s.match_a_round2["match_id"]),
        json={"category_id": s.cats[0]},
        headers={SESSION_TOKEN_HEADER: s.sess_a},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ROUND_CATEGORY_NOT_ALLOWED"


def test_select_match_category_not_in_game(client):
    s = _full_setup(client)
    other_game_id, other_host = _create_game(client)
    other_cat = _create_category(client, other_game_id, other_host, "Other")
    response = client.post(
        "/api/matches/{}/category".format(s.match_a["match_id"]),
        json={"category_id": other_cat},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "CATEGORY_NOT_IN_GAME"


def test_selected_category_scopes_round1_pool(client):
    s = _full_setup(client)
    assert client.post(
        "/api/matches/{}/category".format(s.match_a["match_id"]),
        json={"category_id": s.cats[0]},
        headers={HOST_TOKEN_HEADER: s.host},
    ).status_code == 200
    # A cats[1] word cannot enter the Round 1 match once the category is set.
    denied = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=[s.words_b[s.cats[1]][0]]
    )
    assert denied.status_code == 409
    assert denied.get_json()["error"]["code"] == "WORD_NOT_IN_ROUND"
    # A cats[0] word still works.
    ok = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=[s.words_b[s.cats[0]][0]]
    )
    assert ok.status_code == 201
    assert ok.get_json()["data"]["category_id"] == s.cats[0]


# ---------------------------------------------------------------------------
# Word assignment
# ---------------------------------------------------------------------------


def test_manual_word_assignment(client):
    s = _full_setup(client)
    response = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b[s.cats[0]][:1]
    )
    assert response.status_code == 201
    turn = response.get_json()["data"]
    assert turn["status"] == Turn.STATUS_WAITING
    assert [w["word_text"] for w in turn["words"]] == ["B01"]
    assert turn["current_word_id"] == turn["words"][0]["word_id"]


def test_assign_own_team_word_rejected(client):
    s = _full_setup(client)
    response = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_a[s.cats[0]][:1]
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "WORD_OWN_TEAM"


def test_assign_word_not_in_game(client):
    s = _full_setup(client)
    other_game_id, other_host = _create_game(client)
    other_team = _create_team(client, other_game_id, "Team X", "Xia")
    other_session = _connect(
        client, other_team["leader"]["connection_token"]
    )["session_token"]
    other_cat = _create_category(client, other_game_id, other_host, "Food")
    foreign_word = _submit_words(
        client,
        other_game_id,
        other_team["team_id"],
        other_cat,
        ["foreign"],
        other_session,
    )[0]
    response = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=[foreign_word]
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "WORD_NOT_IN_GAME"


def test_assign_word_from_other_round_rejected(client):
    s = _full_setup(client)
    # words_b[cats[1]] belong to Round 2 (the Round 1 picker drove them there).
    response = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=s.words_b[s.cats[1]][:1]
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "WORD_NOT_IN_ROUND"


def test_word_used_once_per_match(client):
    s = _full_setup(client)
    word_id = s.words_b[s.cats[0]][0]
    assert _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=[word_id]
    ).status_code == 201
    response = _assign_turn_words(
        client, s.host, s.match_a["match_id"], word_ids=[word_id]
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "WORD_ALREADY_ASSIGNED"


def test_random_word_assignment(client):
    s = _full_setup(client)
    response = _assign_turn_words(client, s.host, s.match_a["match_id"], count=2)
    assert response.status_code == 201
    turn = response.get_json()["data"]
    assert len(turn["words"]) == 2
    submitter = {w["word_text"].startswith("B") for w in turn["words"]}
    assert submitter == {True}


def test_random_word_assignment_insufficient(client):
    s = _full_setup(client)
    response = _assign_turn_words(client, s.host, s.match_a["match_id"], count=50)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "INSUFFICIENT_WORDS"


def test_assign_turn_requires_params(client):
    s = _full_setup(client)
    response = client.post(
        "/api/matches/{}/turns".format(s.match_a["match_id"]),
        json={},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "TURN_PARAMS_INVALID"


def test_assign_turn_requires_host(client):
    s = _full_setup(client)
    assert client.post(
        "/api/matches/{}/turns".format(s.match_a["match_id"]), json={"count": 1}
    ).status_code == 401


def test_list_turns(client):
    s = _full_setup(client)
    assert _assign_turn_words(
        client, s.host, s.match_a["match_id"], count=1
    ).status_code == 201
    response = client.get(
        "/api/matches/{}/turns".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    turns = response.get_json()["data"]["turns"]
    assert len(turns) == 2


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def test_readiness_ready_after_full_setup(client):
    s = _full_setup(client)
    response = client.get(
        "/api/games/{}/readiness".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["ready"] is True
    assert data["issues"] == []


def test_readiness_missing_roles(client):
    s = _basic_setup(client)
    s.member_a = _add_member(client, s.team_a["team_id"], "Maria")
    s.cat = _create_category(client, s.game_id, s.host, "Food")
    _submit_words(
        client, s.game_id, s.team_a["team_id"], s.cat, ["apple", "banana"], s.sess_a
    )
    _submit_words(
        client, s.game_id, s.team_b["team_id"], s.cat, ["dog", "cat"], s.sess_b
    )
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    _select_categories(client, s.game_id, s.host, 1, [s.cat])
    _create_matches(
        client,
        s.game_id,
        s.host,
        1,
        [{"team_id": s.team_a["team_id"], "opponent_team_id": s.team_b["team_id"]}],
    )
    response = client.get(
        "/api/games/{}/readiness".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    data = response.get_json()["data"]
    assert data["ready"] is False
    joined = " ".join(data["issues"])
    assert "Manghuhula" in joined
    assert "Tagasagot" in joined


def test_readiness_missing_round1_words(client):
    s = _basic_setup(client)
    s.team_c = _create_team(client, s.game_id, "Team C", "Cece")
    s.team_d = _create_team(client, s.game_id, "Team D", "Dina")
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    response = client.get(
        "/api/games/{}/readiness".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    data = response.get_json()["data"]
    assert data["ready"] is False
    assert any("no assigned words" in issue for issue in data["issues"])


def test_readiness_missing_matches(client):
    s = _basic_setup(client)
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    s.cat = _create_category(client, s.game_id, s.host, "Food")
    _submit_words(
        client, s.game_id, s.team_a["team_id"], s.cat, ["apple"], s.sess_a
    )
    response = client.get(
        "/api/games/{}/readiness".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    data = response.get_json()["data"]
    assert data["ready"] is False
    assert any("no matches" in issue for issue in data["issues"])


def test_readiness_no_words_anywhere(client):
    s = _basic_setup(client)
    s.cat = _create_category(client, s.game_id, s.host, "Food")
    assert _create_round(client, s.game_id, s.host, 1).status_code == 201
    _select_categories(client, s.game_id, s.host, 1, [s.cat])
    _create_matches(
        client,
        s.game_id,
        s.host,
        1,
        [{"team_id": s.team_a["team_id"], "opponent_team_id": s.team_b["team_id"]}],
    )
    response = client.get(
        "/api/games/{}/readiness".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    issues = response.get_json()["data"]["issues"]
    assert any("No configured categories" in issue for issue in issues)


def test_readiness_detects_own_team_word(app, client):
    s = _full_setup(client)
    with app.app_context():
        match = db.session.get(Match, s.match_a["match_id"])
        own_word_id = s.words_a[s.cats[0]][0]
        turn = Turn(
            match_id=match.id,
            team_id=match.team_id,
            round_id=match.round_id,
            turn_order=99,
            status=Turn.STATUS_WAITING,
        )
        db.session.add(turn)
        db.session.flush()
        db.session.add(
            TurnWord(turn_id=turn.id, word_id=own_word_id, sequence=1)
        )
        db.session.commit()
    response = client.get(
        "/api/games/{}/readiness".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    data = response.get_json()["data"]
    assert data["ready"] is False
    assert any("guessing team itself" in issue for issue in data["issues"])


def test_readiness_requires_host(client):
    s = _basic_setup(client)
    assert client.get("/api/games/{}/readiness".format(s.game_id)).status_code == 401


# ---------------------------------------------------------------------------
# Round timer update / advance / reset
# ---------------------------------------------------------------------------


def _create_round_setup(client):
    """A game with rounds 1 + 2, each with one head-to-head match, ready to play."""
    s = _full_setup(client)
    return s


def test_update_round_timer(client):
    s = _full_setup(client)
    response = client.post(
        "/api/games/{}/rounds/1/timer".format(s.game_id),
        json={"timer_seconds": 120, "timer_mode": "COUNTUP"},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["round_number"] == 1
    assert data["timer_seconds"] == 120
    assert data["timer_mode"] == "COUNTUP"


def test_update_round_timer_invalid_seconds(client):
    s = _full_setup(client)
    response = client.post(
        "/api/games/{}/rounds/1/timer".format(s.game_id),
        json={"timer_seconds": 0},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "TIMER_CONFIG_INVALID"


def test_update_round_timer_invalid_mode(client):
    s = _full_setup(client)
    response = client.post(
        "/api/games/{}/rounds/1/timer".format(s.game_id),
        json={"timer_mode": "SIDEWAYS"},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "TIMER_CONFIG_INVALID"


def test_update_round_timer_missing_args(client):
    s = _full_setup(client)
    response = client.post(
        "/api/games/{}/rounds/1/timer".format(s.game_id),
        json={},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "TIMER_CONFIG_INVALID"


def test_update_round_timer_round_missing(client):
    s = _basic_setup(client)
    response = client.post(
        "/api/games/{}/rounds/1/timer".format(s.game_id),
        json={"timer_seconds": 60},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "ROUND_NOT_FOUND"


def test_update_round_timer_locked_after_start(app, client):
    s = _full_setup(client)
    # Start round 1's turn so the round.started_at is set.
    resp = client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert resp.status_code == 200
    response = client.post(
        "/api/games/{}/rounds/1/timer".format(s.game_id),
        json={"timer_seconds": 90},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ROUND_TIMER_LOCKED"


def test_update_round_timer_locked_once_game_ready(app, client):
    """The timer freezes once the game moves past SETUP, even before any turn."""
    s = _full_setup(client)
    with app.app_context():
        game = db.session.get(Game, s.game_id)
        game.status = Game.STATUS_READY
        db.session.commit()
    response = client.post(
        "/api/games/{}/rounds/1/timer".format(s.game_id),
        json={"timer_seconds": 90},
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ROUND_TIMER_LOCKED"


def test_list_matches_during_setup_auto_creates_slots(app, client):
    """GET matches during SETUP runs the idempotent setup so the dashboard
    can pick the first team without manual match creation."""
    s = _basic_setup(client)
    with app.app_context():
        game = db.session.get(Game, s.game_id)
        game.status = Game.STATUS_SETUP
        db.session.commit()
        assert Round.query.filter_by(game_id=s.game_id).count() == 0

    response = client.get(
        "/api/games/{}/matches".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    body = response.get_json()["data"]["matches"]
    assert len(body) == 4  # Round 1 + Round 2, one slot per team

    with app.app_context():
        assert Round.query.filter_by(game_id=s.game_id).count() == 2
        assert Match.query.filter_by(game_id=s.game_id).count() == 4


def test_update_round_timer_requires_host(client):
    s = _full_setup(client)
    response = client.post(
        "/api/games/{}/rounds/1/timer".format(s.game_id),
        json={"timer_seconds": 60},
    )
    assert response.status_code == 401


def test_advance_round(app, client):
    s = _full_setup(client)
    # Round 2 is gated: every Round 1 match must be completed first.
    blocked = client.post(
        "/api/games/{}/rounds/1/advance".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert blocked.status_code == 409
    assert blocked.get_json()["error"]["code"] == "ROUND_ADVANCE_BLOCKED"
    with app.app_context():
        match = db.session.get(Match, s.match_a["match_id"])
        match.status = Match.STATUS_COMPLETED
        db.session.commit()
    response = client.post(
        "/api/games/{}/rounds/1/advance".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["round_number"] == 2


def test_advance_round_no_next(app, client):
    s = _full_setup(client)
    # Delete round 2 so there is no next round.
    with app.app_context():
        round2 = db.session.query(Round).filter_by(game_id=s.game_id, round_number=2).first()
        db.session.delete(round2)
        db.session.commit()
    response = client.post(
        "/api/games/{}/rounds/1/advance".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "NEXT_ROUND_MISSING"


def test_reset_round(app, client):
    s = _full_setup(client)
    # Start and end a turn so a score is written, then reset.
    client.post(
        "/api/matches/{}/turn/start".format(s.match_a["match_id"]),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    response = client.post(
        "/api/games/{}/rounds/1/reset".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["round_number"] == 1
    assert data["status"] == "PENDING"
    # Matches are reset to pending pending; turns/scores for the round cleared.
    with app.app_context():
        round_obj = db.session.query(Round).filter_by(game_id=s.game_id, round_number=1).first()
        assert all(m.status == "PENDING" for m in round_obj.matches)
        assert Turn.query.filter_by(round_id=round_obj.id).count() == 0
        assert Score.query.filter_by(round_id=round_obj.id).count() == 0


def test_round_controls_require_host(client):
    s = _basic_setup(client)
    url = "/api/games/{}/rounds/1".format(s.game_id)
    assert client.post(url + "/timer", json={"timer_seconds": 60}).status_code == 401
    assert client.post(url + "/advance").status_code == 401
    assert client.post(url + "/reset").status_code == 401


# ---------------------------------------------------------------------------
# Default categories (lazy seeding)
# ---------------------------------------------------------------------------


def test_default_categories_seeded_on_list(client):
    game_id, host = _create_game(client)
    response = client.get(
        "/api/games/{}/categories".format(game_id),
        headers={HOST_TOKEN_HEADER: host},
    )
    assert response.status_code == 200
    names = [c["name"] for c in response.get_json()["data"]["categories"]]
    assert "Tao / People" in names
    assert "Bagay / things / object" in names
    assert "Lugar / place" in names
    assert "Hayop / animal" in names
    assert "Pagkain / food" in names
    assert "Other" in names


def test_default_categories_idempotent(client):
    game_id, host = _create_game(client)
    client.get(
        "/api/games/{}/categories".format(game_id),
        headers={HOST_TOKEN_HEADER: host},
    )
    response = client.get(
        "/api/games/{}/categories".format(game_id),
        headers={HOST_TOKEN_HEADER: host},
    )
    names = [c["name"] for c in response.get_json()["data"]["categories"]]
    assert sum(1 for n in names if n == "Tao / People") == 1


def test_default_categories_not_seeded_for_existing(client):
    # A game that already has categories should never get defaults seeded.
    s = _basic_setup(client)
    _create_category(client, s.game_id, s.host, "Food")
    response = client.get(
        "/api/games/{}/categories".format(s.game_id),
        headers={HOST_TOKEN_HEADER: s.host},
    )
    names = [c["name"] for c in response.get_json()["data"]["categories"]]
    assert names == ["Food"]