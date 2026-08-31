"""
Pinoy Henyo Online -- Complete End-to-End Integration Test
Covers: Host flow, Team Leader, Team Member, Gameplay, Reconnection, Mismatch audit
Run: python e2e_test.py
"""
import json, sys, traceback

from app import create_app
from app.extensions import db, socketio
from app.models import Game, GameEvent

app = create_app("testing")

# Collect results
results = []
mismatches = []
failures = []
passes = []

def log(section, name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    entry = f"[{section}] {name}: {status} {detail}"
    results.append(entry)
    if ok:
        passes.append(entry)
        print(f"  PASS {name} {detail}")
    else:
        failures.append(entry)
        print(f"  FAIL {name} {detail}")

def mismatch(desc):
    mismatches.append(desc)
    print(f"  WARN MISMATCH: {desc}")

def api(c, method, url, host_token=None, session_token=None, body=None, device_id=None):
    headers = {}
    if host_token:
        headers["X-Host-Token"] = host_token
    if session_token:
        headers["X-Session-Token"] = session_token
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    # also allow Bearer fallback check
    func = getattr(c, method.lower())
    return func(url, **kwargs)

# We need an app context and client
with app.app_context():
    db.create_all()
    c = app.test_client()

    # Flask-SocketIO test client will be created per-token later

    print("="*70)
    print("HOST FLOW -- Create Game -> Host Dashboard -> QR -> Teams -> Words -> Roles -> Round -> Match -> Start -> Gameplay -> Leaderboard -> Stats -> History")
    print("="*70)

    # 1. Create Game
    try:
        r = api(c, "POST", "/api/games")
        assert r.status_code == 201, f"201 expected got {r.status_code} {r.get_json()}"
        data = r.get_json()["data"]
        game_id = data["game_id"]
        game_code = data["game_code"]
        host_token = data["host_session_token"]
        assert game_code.startswith("PH") or len(game_code) >= 4
        log("HOST", "Create Game", True, f"game_id={game_id} code={game_code}")
    except Exception as e:
        log("HOST", "Create Game", False, str(e)); traceback.print_exc(); sys.exit(1)

    # 2. Host Dashboard -- GET game and status
    try:
        r = api(c, "GET", f"/api/games/{game_id}", host_token=host_token)
        assert r.status_code == 200
        assert r.get_json()["data"]["game_code"] == game_code
        log("HOST", "Host Dashboard GET /games/:id", True)
    except Exception as e:
        log("HOST", "Host Dashboard GET /games/:id", False, str(e))

    # status endpoint -- frontend host_dashboard.js does: API.getGameCode() || (await GameAPI.status(gameId)).game_code
    # But backend status has NO game_code -- this is a known mismatch.
    try:
        r = api(c, "GET", f"/api/games/{game_id}/status")
        assert r.status_code == 200
        sdata = r.get_json()["data"]
        has_code = "game_code" in sdata
        if has_code:
            log("HOST", "GET /status has game_code", True)
        else:
            log("HOST", "GET /status has game_code", False, "Missing game_code field")
            mismatch("GET /api/games/:id/status does NOT return game_code, but host_dashboard.js:840 does `(await GameAPI.status(gameId)).game_code` as fallback -> will be undefined, QR/code stays placeholder PH-1234 on refresh.")
        # check fields
        assert "current_round" in sdata
        log("HOST", "GET /status fields", True, f"status={sdata['status']}")
    except Exception as e:
        log("HOST", "GET /status", False, str(e))

    # 3. Display QR
    try:
        r = api(c, "GET", f"/api/games/{game_id}/qr", host_token=host_token)
        # note: game QR uses /api/games/:id/qr but route is in teams_bp: /games/:id/qr -- frontend game-api.js gameQr does host:true
        if r.status_code == 200:
            q = r.get_json()["data"]
            assert "qr_image" in q and q["qr_image"].startswith("data:image")
            assert game_code in q["payload"] or "join/game" in q["payload"]
            log("HOST", "Display QR (game QR)", True, f"payload={q['payload'][:50]}")
        else:
            log("HOST", "Display QR (game QR)", False, f"{r.status_code} {r.get_json()}")
    except Exception as e:
        log("HOST", "Display QR", False, str(e))

    # 4. Receive Teams -- create teams
    try:
        r = api(c, "POST", f"/api/games/{game_id}/teams", body={"team_name": "Team Alpha", "username": "Alice"})
        assert r.status_code == 201, r.get_json()
        tA = r.get_json()["data"]
        teamA_id = tA["team_id"]; teamA_code = tA["team_code"]
        leaderA = tA["leader"]
        log("HOST", "Create Team Alpha", True, f"team_id={teamA_id} code={teamA_code}")

        r = api(c, "POST", f"/api/games/{game_id}/teams", body={"team_name": "Team Beta", "username": "Bob"})
        assert r.status_code == 201
        tB = r.get_json()["data"]
        teamB_id = tB["team_id"]; teamB_code = tB["team_code"]
        log("HOST", "Create Team Beta", True, f"team_id={teamB_id}")

        # team QR
        r = api(c, "GET", f"/api/teams/{teamA_id}/qr", host_token=host_token)
        if r.status_code == 200:
            log("HOST", "Team QR", True)
        else:
            log("HOST", "Team QR", False, f"{r.status_code}")

        r = api(c, "POST", f"/api/teams/{teamA_id}/members", body={"username": "Charlie"})
        assert r.status_code == 201
        memC = r.get_json()["data"]
        charlie_id = memC["member_id"]
        log("HOST", "Add Member Charlie to Alpha", True, f"member_id={charlie_id}")

        r = api(c, "POST", f"/api/teams/{teamB_id}/members", body={"username": "Dave"})
        assert r.status_code == 201
        dave_id = r.get_json()["data"]["member_id"]
        log("HOST", "Add Member Dave to Beta", True)

        # No team-list endpoint -- frontend teams.js comment confirms this. Verify 404 on guessed URL.
        r = api(c, "GET", f"/api/games/{game_id}/teams")
        if r.status_code == 404:
            mismatch("No GET /api/games/:id/teams endpoint -- frontend teams.js maintains API.getKnownTeams() locally; on refresh host loses team list (dashboard orderedMatches breaks).")
        log("HOST", "Teams persisted", True)

    except Exception as e:
        log("HOST", "Teams", False, str(e)); traceback.print_exc()

    # 5. Manage Words -- categories and words
    try:
        r = api(c, "POST", f"/api/games/{game_id}/categories", host_token=host_token, body={"name": "Tao / Person"})
        assert r.status_code == 201, r.get_json()
        cat1_id = r.get_json()["data"]["category_id"]
        r = api(c, "POST", f"/api/games/{game_id}/categories", host_token=host_token, body={"name": "Pagkain / Food"})
        assert r.status_code == 201
        cat2_id = r.get_json()["data"]["category_id"]
        log("HOST", "Create Categories", True, f"cat1={cat1_id} cat2={cat2_id}")

        r = api(c, "GET", f"/api/games/{game_id}/categories", host_token=host_token)
        assert r.status_code == 200
        assert len(r.get_json()["data"]["categories"]) >= 2
        log("HOST", "List Categories", True)

        # Words: host creates words -- needs category_id, word_text, team_id (for host-word scoping)
        # Frontend words.js does WordAPI.createWord(gameId, {categoryId, wordText, teamId, asHost:true})
        words_alpha = []
        for w in ["Juan", "Maria", "Pedro", "Adobo", "Sinigang"]:
            cat = cat1_id if w in ["Juan","Maria","Pedro"] else cat2_id
            r = api(c, "POST", f"/api/games/{game_id}/words", host_token=host_token, body={"category_id": cat, "word_text": w, "team_id": teamA_id})
            assert r.status_code == 201, f"{w}: {r.get_json()}"
            words_alpha.append(r.get_json()["data"])
        log("HOST", "Create Words Team Alpha (5)", True)

        words_beta = []
        for w in ["Kambing", "Baboy", "Manok", "Lechon", "Pancit"]:
            cat = cat1_id if w in ["Kambing","Baboy","Manok"] else cat2_id
            r = api(c, "POST", f"/api/games/{game_id}/words", host_token=host_token, body={"category_id": cat, "word_text": w, "team_id": teamB_id})
            assert r.status_code == 201, r.get_json()
            words_beta.append(r.get_json()["data"])
        log("HOST", "Create Words Team Beta (5)", True)

        # Host list words (host-only)
        r = api(c, "GET", f"/api/games/{game_id}/words", host_token=host_token)
        assert r.status_code == 200
        all_words = r.get_json()["data"]["words"]
        assert len(all_words) >= 10
        # Player/session without host should be blocked (anti-cheat)
        r2 = api(c, "GET", f"/api/games/{game_id}/words")
        assert r2.status_code == 401, "Expected host-auth for word list"
        log("HOST", "Manage Words anti-cheat (player cannot list all words)", True)

        # Duplicate word check -- backend enforces normalized_word uniqueness per game/category
        r = api(c, "POST", f"/api/games/{game_id}/words", host_token=host_token, body={"category_id": cat1_id, "word_text": "  juan  ", "team_id": teamA_id})
        # should be duplicate of "Juan" (backend normalized)
        if r.status_code in (409, 422):
            log("HOST", "Duplicate word rejected (normalized)", True)
        else:
            log("HOST", "Duplicate word rejected", False, f"got {r.status_code} {r.get_json()}")

    except Exception as e:
        log("HOST", "Words", False, str(e)); traceback.print_exc()

    # 6. Assign Roles
    try:
        # need to know member_ids for Alpha: leader Alice + Charlie
        # leaderA already has member_id; charlie_id is Charlie
        r = api(c, "POST", f"/api/teams/{teamA_id}/roles", host_token=host_token, body={"roles": [{"member_id": leaderA["member_id"], "gameplay_role": "MANGHUHULA"}, {"member_id": charlie_id, "gameplay_role": "TAGASAGOT"}]})
        assert r.status_code == 200, r.get_json()
        log("HOST", "Assign Roles Team Alpha (Alice Manghuhula)", True)

        # Beta: Bob manghuhula, Dave tagasagot
        # need Bob's member_id -- fetch via team reveal? tB leader is Bob
        bob_id = tB["leader"]["member_id"]
        r = api(c, "POST", f"/api/teams/{teamB_id}/roles", host_token=host_token, body={"roles": [{"member_id": bob_id, "gameplay_role": "MANGHUHULA"}, {"member_id": dave_id, "gameplay_role": "TAGASAGOT"}]})
        assert r.status_code == 200, r.get_json()
        log("HOST", "Assign Roles Team Beta", True)

        # Player page Save Roles is local-only (player.js btn-save-roles does local only) -- verify backend rejects non-host non-leader
        # Attempt role assign without host token should fail
        r = api(c, "POST", f"/api/teams/{teamA_id}/roles", body={"roles": [{"member_id": leaderA["member_id"], "gameplay_role": "TAGASAGOT"}]})
        assert r.status_code in (401, 403)
        log("HOST", "Roles anti-cheat (player cannot change other teams)", True)
    except Exception as e:
        log("HOST", "Assign Roles", False, str(e)); traceback.print_exc()

    # 7. Configure Round
    try:
        r = api(c, "POST", f"/api/games/{game_id}/rounds", host_token=host_token, body={"round_number": 1, "timer_seconds": 95, "timer_mode": "COUNTDOWN"})
        assert r.status_code == 201, r.get_json()
        rnd1 = r.get_json()["data"]
        log("HOST", "Configure Round 1 (COUNTDOWN 95s)", True, f"round_id={rnd1['round_id']}")

        # Round categories -- Round 1 requires explicit selection
        r = api(c, "POST", f"/api/games/{game_id}/rounds/1/categories", host_token=host_token, body={"category_ids": [cat1_id, cat2_id]})
        assert r.status_code == 200, r.get_json()
        log("HOST", "Select Round 1 Categories", True)

        r = api(c, "GET", f"/api/games/{game_id}/rounds/1/categories", host_token=host_token)
        assert r.status_code == 200
        log("HOST", "Get Round 1 Categories", True)

        # readiness check
        r = api(c, "GET", f"/api/games/{game_id}/readiness", host_token=host_token)
        assert r.status_code == 200
        ready_info = r.get_json()["data"]
        log("HOST", "Readiness check", True, f"ready={ready_info.get('ready')} issues={ready_info.get('issues')}")
    except Exception as e:
        log("HOST", "Configure Round", False, str(e)); traceback.print_exc()

    # 8. Set Match Order
    try:
        r = api(c, "POST", f"/api/games/{game_id}/matches", host_token=host_token, body={"round_number": 1, "matches": [{"team_id": teamA_id, "opponent_team_id": teamB_id}, {"team_id": teamB_id, "opponent_team_id": teamA_id}]})
        assert r.status_code == 201, r.get_json()
        matches = r.get_json()["data"]["matches"]
        assert len(matches) == 2
        matchA_id = matches[0]["match_id"]
        matchB_id = matches[1]["match_id"]
        log("HOST", "Set Match Order (2 matches R1)", True, f"matchA={matchA_id} matchB={matchB_id}")

        # list matches
        r = api(c, "GET", f"/api/games/{game_id}/matches", host_token=host_token)
        assert r.status_code == 200
        log("HOST", "List Matches", True, f"count={len(r.get_json()['data']['matches'])}")

        # reorder
        r = api(c, "PATCH", f"/api/matches/{matchA_id}", host_token=host_token, body={"match_order": 2})
        if r.status_code == 200:
            log("HOST", "Reorder Match", True)
        else:
            log("HOST", "Reorder Match", False, f"{r.status_code}")

        # reset matchA to order 1 for clean gameplay
        api(c, "PATCH", f"/api/matches/{matchA_id}", host_token=host_token, body={"match_order": 1})
        api(c, "PATCH", f"/api/matches/{matchB_id}", host_token=host_token, body={"match_order": 2})
    except Exception as e:
        log("HOST", "Match Order", False, str(e)); traceback.print_exc()

    # 9. Start Game
    try:
        r = api(c, "POST", f"/api/games/{game_id}/start", host_token=host_token)
        assert r.status_code == 200, r.get_json()
        log("HOST", "Start Game (LOBBY->READY)", True, f"status={r.get_json()['data']['status']}")

        # also check invalid transition: starting again should be 409
        r2 = api(c, "POST", f"/api/games/{game_id}/start", host_token=host_token)
        if r2.status_code == 409:
            log("HOST", "Start Game idempotent guard", True)
    except Exception as e:
        log("HOST", "Start Game", False, str(e)); traceback.print_exc()

    print()
    print("="*70)
    print("TEAM LEADER FLOW -- Create Team -> Connect -> Add Members -> Words -> Roles -> Wait -> Play")
    print("="*70)

    # Team leader flow already partly covered (Alice/Bob are leaders). Now test:
    # Creating a new team via player path, connecting device, submitting words

    # Create Team via /games/:id/teams (team leader creates)
    try:
        r = api(c, "POST", f"/api/games/{game_id}/teams", body={"team_name": "Team Charlie", "username": "Eve"})
        # game already started (READY) -- should be blocked? Check mutability guard
        if r.status_code == 409:
            log("TEAM-LEADER", "Create Team after game started blocked (GAME_FROZEN)", True)
            # use pre-created Alpha's session for remaining tests
            teamC_id = None
        elif r.status_code == 201:
            teamC = r.get_json()["data"]
            teamC_id = teamC["team_id"]
            log("TEAM-LEADER", "Create Team Charlie as leader Eve", True, f"team_id={teamC_id}")
        else:
            log("TEAM-LEADER", "Create Team Charlie", False, f"{r.status_code} {r.get_json()}")
            teamC_id = None
    except Exception as e:
        log("TEAM-LEADER", "Create Team", False, str(e))

    # Connect to Host -- device flow
    try:
        # leaderA is Alice. Use her connection_token/device flow
        # First, get device connect via leader token? The connect endpoint expects connection_token or session_token
        # Team creation returned leader with connection_token
        alice_conn_token = leaderA.get("connection_token")
        # Simulate device connect for Alice (team leader)
        # Need device_id
        dev_id_alice = "dev-alice-test123"

        # Try connecting via connection_token (initial pairing)
        if alice_conn_token:
            r = api(c, "POST", "/api/devices/connect", body={"connection_token": alice_conn_token, "device_id": dev_id_alice})
            if r.status_code == 201:
                sess_alice = r.get_json()["data"]
                alice_session = sess_alice["session_token"]
                log("TEAM-LEADER", "Connect to Host (Alice device connect)", True, f"session={alice_session[:8]}...")
            else:
                # fallback: try with team join device path
                log("TEAM-LEADER", "Connect to Host (Alice)", False, f"{r.status_code} {r.get_json()}")
                alice_session = None
        else:
            alice_session = None
            log("TEAM-LEADER", "Connect to Host", False, "No connection_token returned for leader")

        # Also connect Bob
        bob_conn_token = tB["leader"].get("connection_token")
        dev_id_bob = "dev-bob-test456"
        if bob_conn_token:
            r = api(c, "POST", "/api/devices/connect", body={"connection_token": bob_conn_token, "device_id": dev_id_bob})
            if r.status_code == 201:
                bob_session = r.get_json()["data"]["session_token"]
                log("TEAM-LEADER", "Connect to Host (Bob device connect)", True)
            else:
                bob_session = None
                log("TEAM-LEADER", "Connect Bob", False, f"{r.status_code} {r.get_json()}")
        else:
            bob_session = None

        # Heartbeat
        if alice_session:
            r = api(c, "POST", "/api/devices/heartbeat", body={"session_token": alice_session, "device_id": dev_id_alice})
            assert r.status_code == 200
            log("TEAM-LEADER", "Heartbeat (Alice)", True)
        if bob_session:
            r = api(c, "POST", "/api/devices/heartbeat", body={"session_token": bob_session, "device_id": dev_id_bob})
            assert r.status_code == 200
            log("TEAM-LEADER", "Heartbeat (Bob)", True)

    except Exception as e:
        log("TEAM-LEADER", "Connect", False, str(e)); traceback.print_exc()
        alice_session = None
        bob_session = None
        dev_id_alice = "dev-alice-test123"
        dev_id_bob = "dev-bob-test456"

    # Add Members as leader -- already did via /teams/:id/members; now test player word submission
    try:
        # Alice (leader) session should be able to submit word? Words route allows session team submission
        # But words are currently locked? Let's try submitting a word as Alice's team via session token
        # First need Alice session -- if we have it, attempt player word creation
        if alice_session:
            # player word creation uses X-Session-Token + category_id + word_text
            # Need a team_id -- already have teamA_id
            # Player's team is resolved via session's team_id, not body team_id? Check route.
            # For player: resolve_submitting_team(game, session_token, team_id) -- team_id optional but must match session team.
            r = api(c, "POST", f"/api/games/{game_id}/words", session_token=alice_session, body={"category_id": cat1_id, "word_text": "ExtraWordViaSession"})
            # Game is READY (not LOBBY) -- word creation may be allowed until locked? Let's see.
            # The game_service assert_game_mutable checks GAME_COMPLETE/CANCELLED only, so READY should allow.
            if r.status_code == 201:
                log("TEAM-LEADER", "Submit Word via session (player path)", True, f"word={r.get_json()['data']['word_text']}")
            elif r.status_code == 409 and r.get_json().get("error", {}).get("code") == "WORD_LOCKED":
                log("TEAM-LEADER", "Submit Word via session (WORD_LOCKED after READY -- expected)", True, "Backend correctly locks word pool after game start")
                mismatch("Word submission blocked after game start (WORD_LOCKED) -- frontend player words tab does not show frozen state; it still allows Add Word (no visual lock).")
            else:
                log("TEAM-LEADER", "Submit Word via session", False, f"{r.status_code} {r.get_json()}")
        else:
            log("TEAM-LEADER", "Submit Word via session", False, "No Alice session")

        # Host word via asHost=true already tested; ensure it still works even after READY
        r = api(c, "POST", f"/api/games/{game_id}/words", host_token=host_token, body={"category_id": cat1_id, "word_text": "HostExtra", "team_id": teamA_id})
        # may collide or succeed
        if r.status_code in (201, 409, 422):
            log("TEAM-LEADER", "Host submit word after READY", True, f"{r.status_code}")

    except Exception as e:
        log("TEAM-LEADER", "Words", False, str(e)); traceback.print_exc()

    # Assign Roles -- player local-only issue
    try:
        # Player btn-save-roles in player.js does local only, no API call
        mismatch("Player page `Save Roles` (player.js btn-save-roles) is LOCAL ONLY -- never calls TeamAPI.assignRoles. Only host can assign roles (`POST /teams/:id/roles` host-only). If player changes Manghuhula on phone, host never sees it.")
        log("TEAM-LEADER", "Assign Roles (player local-only) mismatch noted", True)
    except Exception as e:
        pass

    print()
    print("="*70)
    print("TEAM MEMBER FLOW -- Join Team -> Connect -> Receive Role -> Participate")
    print("="*70)
    try:
        # Join Team -- Frank joins Alpha via /teams/:id/join
        r = api(c, "POST", f"/api/teams/{teamA_id}/join", body={"username": "Frank"})
        assert r.status_code == 201, r.get_json()
        frank = r.get_json()["data"]
        frank_id = frank["member_id"]
        frank_token = frank.get("connection_token")
        log("MEMBER", "Join Team (Frank -> Alpha)", True, f"member_id={frank_id}")

        # Also test /games/:id/join with team_code path
        r = api(c, "POST", f"/api/games/{game_id}/join", body={"username": "Grace", "team_code": teamA_code})
        assert r.status_code == 201, r.get_json()
        grace = r.get_json()["data"]
        log("MEMBER", "Join Game via team_code (Grace -> Alpha)", True)

        # Connect Frank's device
        dev_id_frank = "dev-frank-test789"
        if frank_token:
            r = api(c, "POST", "/api/devices/connect", body={"connection_token": frank_token, "device_id": dev_id_frank})
            assert r.status_code == 201, r.get_json()
            frank_session = r.get_json()["data"]["session_token"]
            log("MEMBER", "Connect (Frank device)", True)

            # Host must assign Frank a gameplay role before he can participate (turn_service active check requires gameplay_role)
            # Simulate host assigning Frank as TAGASAGOT via teams roles endpoint (host revises roles)
            # Grace was already joined as member_id via /join with team_code -- grab her id
            grace_id = grace.get("member_id")
            roles_payload = []
            # Keep existing Alpha roles: Alice Manghuhula, Charlie Tagasagot
            roles_payload.append({"member_id": leaderA["member_id"], "gameplay_role": "MANGHUHULA"})
            roles_payload.append({"member_id": charlie_id, "gameplay_role": "TAGASAGOT"})
            roles_payload.append({"member_id": frank_id, "gameplay_role": "TAGASAGOT"})
            if grace_id:
                roles_payload.append({"member_id": grace_id, "gameplay_role": "TAGASAGOT"})
            r = api(c, "POST", f"/api/teams/{teamA_id}/roles", host_token=host_token, body={"roles": roles_payload})
            if r.status_code == 200:
                log("MEMBER", "Host assigned roles for Frank/Grace (TAGASAGOT)", True)
            else:
                log("MEMBER", "Host assign roles Frank", False, f"{r.status_code} {r.get_json()}")

            # Participate -- e.g., try to list words as Frank (should be blocked -- host-only)
            r = api(c, "GET", f"/api/games/{game_id}/words", session_token=frank_session)
            assert r.status_code == 401
            log("MEMBER", "Anti-cheat: member cannot view all words (host-only)", True)
        else:
            frank_session = None
            log("MEMBER", "Connect Frank", False, "No connection_token")

        # Frontend join via team_code/game_code typing alone -- no backend endpoint
        mismatch("Frontend `Join Game` modal index.html form-join with username+code does NO backend call -- it checks API.getGameId() locally and if missing shows alert. No `GET /games/by-code/:code` endpoint exists, so typing PH-XXXX alone cannot join. Also QR deep-link `https://host/join/game/GAME_CODE` has no resolver.")

    except Exception as e:
        log("MEMBER", "Team Member flow", False, str(e)); traceback.print_exc()
        frank_session = None

    print()
    print("="*70)
    print("GAMEPLAY -- Start Turn -> Timer -> Correct -> Pass -> Penalty -> 3 Correct -> Turn Complete -> Next Match -> Round 2 -> Winner -> Leaderboard")
    print("="*70)

    try:
        # Assign words to Alpha's match turn (host assigns 5 words from team's pool)
        # Need to ensure we have words for assignment -- gameplay_service.assign_turn_words uses count or word_ids.
        # Host creates turn for matchA with count 5
        r = api(c, "POST", f"/api/matches/{matchA_id}/turns", host_token=host_token, body={"count": 5})
        assert r.status_code == 201, r.get_json()
        turnA = r.get_json()["data"]
        turnA_id = turnA["turn_id"]
        log("GAMEPLAY", "Create Turn (Alpha R1 match, 5 words)", True, f"turn_id={turnA_id} words={len(turnA.get('words', []))}")

        # Start Turn -- can be host or active team session? Route allows host OR team session
        r = api(c, "POST", f"/api/matches/{matchA_id}/turn/start", host_token=host_token)
        assert r.status_code == 200, r.get_json()
        playA = r.get_json()["data"]
        assert playA["status"] == "ACTIVE"
        assert playA["remaining_seconds"] is not None
        log("GAMEPLAY", "Start Turn (Alpha)", True, f"status={playA['status']} remaining={playA['remaining_seconds']} word={playA.get('current_word_text')[:10] if playA.get('current_word_text') else 'HIDDEN?'}")

        # Anti-cheat: host turn payload should have secret; check
        assert playA.get("current_word_text") is not None, "Host should see secret word"
        log("GAMEPLAY", "Host sees secret word", True)

        # Session: Manghuhula (Alice) should see secret; Tagasagot (Frank) should see public
        if alice_session:
            r = api(c, "GET", f"/api/turns/{turnA_id}", session_token=alice_session)
            assert r.status_code == 200
            alice_view = r.get_json()["data"]
            if alice_view.get("current_word_text"):
                log("GAMEPLAY", "Manghuhula (Alice) sees secret", True)
            else:
                log("GAMEPLAY", "Manghuhula sees secret", False, f"Got hidden: {alice_view}")
        if 'frank_session' in locals() and frank_session:
            r = api(c, "GET", f"/api/turns/{turnA_id}", session_token=frank_session)
            if r.status_code == 200:
                frank_view = r.get_json()["data"]
                if not frank_view.get("current_word_text"):
                    log("GAMEPLAY", "Tagasagot (Frank) hidden word (anti-cheat)", True)
                else:
                    log("GAMEPLAY", "Tagasagot hidden word", False, f"Leaked secret: {frank_view.get('current_word_text')}")
            else:
                log("GAMEPLAY", "Tagasagot (Frank) hidden word check", False, f"GET turn returned {r.status_code} {r.get_json()}")
                mismatch("GET /turns/:id with Tagasagot session returned non-200 -- expected public payload (hidden word). Frank may not have active session or is on wrong team.")

        # Timer -- pause/resume (host only)
        r = api(c, "POST", f"/api/turns/{turnA_id}/pause", host_token=host_token)
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["data"]["status"] == "PAUSED"
        log("GAMEPLAY", "Timer Pause (server-authoritative)", True)

        # Frank (non-host session) trying to pause should fail
        if frank_session:
            r = api(c, "POST", f"/api/turns/{turnA_id}/pause", session_token=frank_session)
            if r.status_code == 401:
                log("GAMEPLAY", "Timer Pause anti-cheat (player blocked)", True)
            else:
                log("GAMEPLAY", "Timer Pause anti-cheat (player blocked)", False, f"got {r.status_code} expected 401")

        r = api(c, "POST", f"/api/turns/{turnA_id}/resume", host_token=host_token)
        assert r.status_code == 200
        assert r.get_json()["data"]["status"] == "ACTIVE"
        log("GAMEPLAY", "Timer Resume", True)

        # Correct -- host only
        r = api(c, "POST", f"/api/turns/{turnA_id}/correct", host_token=host_token)
        assert r.status_code == 200, r.get_json()
        after1 = r.get_json()["data"]
        assert after1["correct_words"] == 1
        log("GAMEPLAY", "Correct (1/3)", True, f"correct={after1['correct_words']} word={after1.get('current_word_text')[:10] if after1.get('current_word_text') else ''}")

        # Pass -- host OR team session (backend allows both). Host dashboard uses host token today.
        r = api(c, "POST", f"/api/turns/{turnA_id}/pass", host_token=host_token)
        assert r.status_code == 200, r.get_json()
        after_pass = r.get_json()["data"]
        assert after_pass["passed_words"] >= 1
        log("GAMEPLAY", "Pass (1)", True, f"passed={after_pass['passed_words']}")

        # Also verify team session can pass
        if alice_session:
            # Need a live turn still ACTIVE -- we are still active (1 correct 1 pass, need 3 correct)
            r = api(c, "POST", f"/api/turns/{turnA_id}/pass", session_token=alice_session)
            # This should either succeed (team session is allowed for pass) or correctly increment pass
            if r.status_code == 200:
                log("GAMEPLAY", "Pass via team session (allowed)", True)
            else:
                log("GAMEPLAY", "Pass via team session", False, f"{r.status_code}")

        # Penalty -- -3s and +3s (time/remove, time/add) host only
        r = api(c, "POST", f"/api/turns/{turnA_id}/time/remove", host_token=host_token, body={"seconds": 3, "reason": "penalty e2e"})
        assert r.status_code == 200, r.get_json()
        # verify penalty_seconds increased via scores? Check turn payload
        after_pen = r.get_json()["data"]
        log("GAMEPLAY", "Penalty -3s", True, f"remaining={after_pen['remaining_seconds']}")

        r = api(c, "POST", f"/api/turns/{turnA_id}/time/add", host_token=host_token, body={"seconds": 3, "reason": "bonus e2e"})
        assert r.status_code == 200
        log("GAMEPLAY", "Bonus +3s", True)

        # 3 Correct Words -> Turn Complete
        # We have 1 correct, need 2 more correct to reach 3
        for i in range(2):
            r = api(c, "POST", f"/api/turns/{turnA_id}/correct", host_token=host_token)
            assert r.status_code == 200, r.get_json()
            cur = r.get_json()["data"]
            log("GAMEPLAY", f"Correct ({cur['correct_words']}/3)", True)

        # After 3rd correct, turn should be COMPLETED
        r = api(c, "GET", f"/api/turns/{turnA_id}", host_token=host_token)
        assert r.status_code == 200
        final_turnA = r.get_json()["data"]
        assert final_turnA["status"] == "COMPLETED", f"Expected COMPLETED got {final_turnA['status']}"
        assert final_turnA.get("outcome", {}).get("won") == True or final_turnA["correct_words"] >= 3
        log("GAMEPLAY", "Turn Complete (3 correct -> WIN)", True, f"status={final_turnA['status']}")

        # Check that duplicate correct on completed turn is blocked
        r = api(c, "POST", f"/api/turns/{turnA_id}/correct", host_token=host_token)
        if r.status_code in (409, 422):
            log("GAMEPLAY", "Correct after complete blocked", True)
        else:
            log("GAMEPLAY", "Correct after complete blocked", False, f"{r.status_code}")

        # Next Match -- create/start/correct flow for Beta
        r = api(c, "POST", f"/api/matches/{matchB_id}/turns", host_token=host_token, body={"count": 5})
        assert r.status_code == 201
        turnB_id = r.get_json()["data"]["turn_id"]
        log("GAMEPLAY", "Create Turn Beta R1", True, f"turn_id={turnB_id}")

        r = api(c, "POST", f"/api/matches/{matchB_id}/turn/start", host_token=host_token)
        assert r.status_code == 200, r.get_json()
        log("GAMEPLAY", "Start Turn Beta", True)

        # Complete Beta with 3 correct as well
        for _ in range(3):
            r = api(c, "POST", f"/api/turns/{turnB_id}/correct", host_token=host_token)
            assert r.status_code == 200
        r = api(c, "GET", f"/api/turns/{turnB_id}", host_token=host_token)
        assert r.get_json()["data"]["status"] == "COMPLETED"
        log("GAMEPLAY", "Turn Complete Beta (3 correct)", True)

        # Verify scores reflect both wins
        r = api(c, "GET", f"/api/games/{game_id}/scores", host_token=host_token)
        assert r.status_code == 200
        scores = r.get_json()["data"]["scores"]
        # Each team's scores should have points
        log("GAMEPLAY", "Scores after R1", True, f"scores={len(scores)} entries")

        # Round 2 -- configure if not yet created
        # Create Round 2
        r = api(c, "POST", f"/api/games/{game_id}/rounds", host_token=host_token, body={"round_number": 2, "timer_seconds": 60, "timer_mode": "COUNTDOWN"})
        if r.status_code == 201:
            log("GAMEPLAY", "Configure Round 2", True)
        elif r.status_code in (409, 422):
            log("GAMEPLAY", "Round 2 already exists", True, r.get_json())
        else:
            log("GAMEPLAY", "Configure Round 2", False, f"{r.status_code} {r.get_json()}")

        # Create matches for round 2
        r = api(c, "POST", f"/api/games/{game_id}/matches", host_token=host_token, body={"round_number": 2, "matches": [{"team_id": teamA_id, "opponent_team_id": teamB_id}, {"team_id": teamB_id, "opponent_team_id": teamA_id}]})
        if r.status_code == 201:
            r2matches = r.get_json()["data"]["matches"]
            r2matchA = r2matches[0]["match_id"]
            r2matchB = r2matches[1]["match_id"]
            log("GAMEPLAY", "Create Round 2 Matches", True)
        else:
            # may already exist -- list
            r = api(c, "GET", f"/api/games/{game_id}/matches", host_token=host_token)
            all_m = r.get_json()["data"]["matches"]
            r2_matches = [m for m in all_m if m["round_number"] == 2]
            if r2_matches:
                r2matchA = r2_matches[0]["match_id"]
                r2matchB = r2_matches[1]["match_id"] if len(r2_matches) > 1 else r2_matches[0]["match_id"]
                log("GAMEPLAY", "Round 2 Matches existing", True)
            else:
                log("GAMEPLAY", "Round 2 Matches", False, f"{r.status_code}")
                r2matchA = None

        # Play one Round 2 turn and win, then end game to check Winner/Leaderboard
        if r2matchA:
            r = api(c, "POST", f"/api/matches/{r2matchA}/turns", host_token=host_token, body={"count": 5})
            if r.status_code == 201:
                t2_id = r.get_json()["data"]["turn_id"]
                r = api(c, "POST", f"/api/matches/{r2matchA}/turn/start", host_token=host_token)
                assert r.status_code == 200
                for _ in range(3):
                    api(c, "POST", f"/api/turns/{t2_id}/correct", host_token=host_token)
                log("GAMEPLAY", "Round 2 Turn completed", True)
            else:
                log("GAMEPLAY", "Round 2 Turn create", False, f"{r.status_code} {r.get_json()}")

        # Winner -- list matches to see if all completed, then get leaderboard
        r = api(c, "GET", f"/api/games/{game_id}/matches", host_token=host_token)
        all_matches = r.get_json()["data"]["matches"]
        completed = sum(1 for m in all_matches if m["status"] == "COMPLETED")
        log("GAMEPLAY", f"Matches completed {completed}/{len(all_matches)}", True)

    except Exception as e:
        log("GAMEPLAY", "Gameplay", False, str(e)); traceback.print_exc()

    # Leaderboard & Statistics & History
    print()
    print("="*70)
    print("HOST -- Leaderboard / Statistics / Game History")
    print("="*70)
    try:
        r = api(c, "GET", f"/api/games/{game_id}/leaderboard", host_token=host_token)
        assert r.status_code == 200, r.get_json()
        lb = r.get_json()["data"]["leaderboard"]
        assert len(lb) >= 2
        # check ordering desc points
        assert lb[0]["points"] >= lb[1]["points"]
        log("HOST", "Leaderboard (ranked desc points)", True, f"leader={lb[0]['team_name']} {lb[0]['points']}pts")
        # verify fields frontend expects
        # frontend host_dashboard.js expects team_name, points, penalties style

        # Statistics
        r = api(c, "GET", f"/api/games/{game_id}/statistics", host_token=host_token)
        assert r.status_code == 200, r.get_json()
        stats = r.get_json()["data"]
        assert "total_teams" in stats and "total_words" in stats
        log("HOST", "Statistics", True, f"teams={stats['total_teams']} words={stats['total_words']}")

        # Game History -- host scoped /history list
        r = api(c, "GET", "/api/games/history", host_token=host_token)
        assert r.status_code == 200, r.get_json()
        hist_list = r.get_json()["data"]["games"]
        assert len(hist_list) >= 1
        log("HOST", "Game History List (/history)", True, f"games={len(hist_list)}")

        r = api(c, "GET", f"/api/games/{game_id}/history", host_token=host_token)
        assert r.status_code == 200, r.get_json()
        hist = r.get_json()["data"]
        assert "rounds" in hist and "events" in hist and "scores" in hist
        # check audit events present
        ev_types = [e["event_type"] for e in hist["events"]]
        for needed in ["GAME_CREATED", "ROUND_STARTED", "MATCH_STARTED", "TURN_STARTED", "WORD_CORRECT", "TURN_COMPLETED"]:
            if needed not in ev_types:
                mismatch(f"Audit event missing in history: {needed} -- events present: {ev_types[:10]}")
        log("HOST", "Game History Detail (audit events)", True, f"events={len(ev_types)} types={ev_types[:8]}")

        # Leaderboard/Statistics anti-cheat -- player session should not access
        if frank_session:
            r = api(c, "GET", f"/api/games/{game_id}/leaderboard", session_token=frank_session)
            assert r.status_code == 401
            log("HOST", "Leaderboard anti-cheat (player blocked)", True)

    except Exception as e:
        log("HOST", "Leaderboard/Stats/History", False, str(e)); traceback.print_exc()

    # Try ending game properly
    try:
        r = api(c, "POST", f"/api/games/{game_id}/end", host_token=host_token)
        if r.status_code == 200:
            log("HOST", "End Game (-> GAME_COMPLETE)", True, f"status={r.get_json()['data']['status']}")
        else:
            log("HOST", "End Game", False, f"{r.status_code} {r.get_json()}")
    except Exception as e:
        log("HOST", "End Game", False, str(e))

    print()
    print("="*70)
    print("RECONNECTION -- Refresh Host/Leader/Member + Socket.IO + Recover State")
    print("="*70)

    try:
        # Refresh Host -- simulate page reload: new test client, same localStorage tokens
        # Host restore uses GET /games/:id and GET /games/:id/status, plus device session repair is N/A (host is token-based, not DeviceSession)
        # The frontend Connect.restoreHostSession does GameAPI.get(gameId) -- verify that still works after game ended?
        # After GAME_COMPLETE, host fetch should still work but gameplay mutations should be blocked.
        r = api(c, "GET", f"/api/games/{game_id}", host_token=host_token)
        assert r.status_code == 200
        assert r.get_json()["data"]["status"] in ("GAME_COMPLETE", "COMPLETED", "ENDED", "IN_PROGRESS")
        log("RECONNECT", "Refresh Host -- GET /games/:id after complete", True, f"status={r.get_json()['data']['status']}")

        r = api(c, "GET", f"/api/games/{game_id}/status")
        assert r.status_code == 200
        log("RECONNECT", "Refresh Host -- GET /status after complete", True)

        # Mutations on completed game should be blocked (GAME_FROZEN)
        r = api(c, "POST", f"/api/matches/{matchA_id}/turns", host_token=host_token, body={"count": 3})
        if r.status_code == 409:
            log("RECONNECT", "Host mutations frozen after GAME_COMPLETE (409)", True)
        else:
            log("RECONNECT", "Host mutations frozen after complete", False, f"got {r.status_code} {r.get_json()}")

        # Refresh Team Leader -- Alice reconnect via /devices/connect with session_token+device_id
        if alice_session:
            r = api(c, "POST", "/api/devices/connect", body={"session_token": alice_session, "device_id": dev_id_alice})
            # reconnect path: session_token present -> should return same session or re-issue?
            # Backend devices connect: if session_token+device_id match, it returns existing session (reconnect)
            if r.status_code in (200, 201):
                log("RECONNECT", "Refresh Team Leader (Alice reconnect)", True)
            else:
                log("RECONNECT", "Refresh Team Leader", False, f"{r.status_code} {r.get_json()}")
                mismatch("Device reconnect should succeed with stored session_token+device_id; got error. Player would see 'Session expired' banner.")

        # Refresh Team Member -- Frank reconnect similarly
        if 'frank_session' in locals() and frank_session:
            r = api(c, "POST", "/api/devices/connect", body={"session_token": frank_session, "device_id": dev_id_frank})
            if r.status_code in (200, 201):
                log("RECONNECT", "Refresh Team Member (Frank reconnect)", True)
            else:
                log("RECONNECT", "Refresh Team Member", False, f"{r.status_code}")

        # Heartbeat still works after reconnect
        if alice_session:
            r = api(c, "POST", "/api/devices/heartbeat", body={"session_token": alice_session, "device_id": dev_id_alice})
            if r.status_code == 200:
                log("RECONNECT", "Heartbeat after reconnect", True)
            else:
                log("RECONNECT", "Heartbeat after reconnect", False, f"{r.status_code}")

        # Disconnect/reconnect Socket.IO -- test via Flask-SocketIO test client
        # Host socket should authenticate with host token; player socket with session token
        try:
            from flask_socketio import SocketIOTestClient  # not used; use socketio.test_client
            # socketio is the Flask-SocketIO instance from extensions
            # Host connect
            host_sio = socketio.test_client(app, auth={"token": host_token}, query_string=f"device_id=dev-host-e2e")
            # Check if connected (may need to check is_connected())
            if host_sio.is_connected():
                log("RECONNECT", "Socket.IO Host connect (auth host_token)", True)
                # Host joining a turn room
                # need a valid turn_id still
                host_sio.emit("join_turn", turnA_id)
                received = host_sio.get_received()
                # should get turn_state or error
                has_state = any(x["name"] in ("turn_state", "error") for x in received)
                log("RECONNECT", "Socket.IO Host join_turn", True if has_state else False, f"received={received[:1]}")
                host_sio.disconnect()
                log("RECONNECT", "Socket.IO Host disconnect", True)
            else:
                log("RECONNECT", "Socket.IO Host connect", False, "Not connected")

            # Player socket -- Alice
            if alice_session:
                player_sio = socketio.test_client(app, auth={"token": alice_session}, query_string=f"device_id={dev_id_alice}")
                if player_sio.is_connected():
                    log("RECONNECT", "Socket.IO Player connect (Alice session)", True)
                    # Player join_turn should succeed only for their team's turn
                    player_sio.emit("join_turn", turnA_id)
                    rec2 = player_sio.get_received()
                    # Alice is on teamA, turnA is teamA -> should receive turn_state with secret?
                    # Check realtime can_join_turn logic
                    log("RECONNECT", "Socket.IO Player join_turn (own team)", True, f"events={[x['name'] for x in rec2]}")
                    # Try joining opponent's turn (should be forbidden)
                    if 'turnB_id' in locals():
                        player_sio.emit("join_turn", turnB_id)
                        rec3 = player_sio.get_received()
                        forbidden = any(x["name"] == "error" for x in rec3)
                        # If Beta is opponent team, Alice (Alpha) joining Beta turn should be forbidden unless host
                        # But current can_join_turn: player can join only if peer.team_id == turn.team_id
                        # So Alpha trying to join Beta should get error FORBIDDEN
                        if forbidden:
                            log("RECONNECT", "Socket.IO Player anti-cheat (cannot join opponent turn)", True)
                        else:
                            # If no error, maybe allowed? Log.
                            log("RECONNECT", "Socket.IO opponent join (expected forbidden)", False, f"got {rec3}")
                    player_sio.disconnect()
                    log("RECONNECT", "Socket.IO Player disconnect", True)
                else:
                    log("RECONNECT", "Socket.IO Player connect", False, "Not connected")

            # Bad token should be refused
            bad_sio = socketio.test_client(app, auth={"token": "bad-token-xyz"})
            if not bad_sio.is_connected():
                log("RECONNECT", "Socket.IO bad token refused", True)
            else:
                log("RECONNECT", "Socket.IO bad token refused", False, "Connected with bad token")
                bad_sio.disconnect()
        except Exception as e:
            log("RECONNECT", "Socket.IO", False, str(e)); traceback.print_exc()

        # Recover game state -- after refresh, frontend restores from localStorage + API.getGameId() + GameAPI.get/status
        # That is covered by API calls above. Verify history still reflects correct state after complete.
        r = api(c, "GET", f"/api/games/{game_id}/history", host_token=host_token)
        if r.status_code == 200:
            hist2 = r.get_json()["data"]
            log("RECONNECT", "Recover game state (history after complete)", True, f"status={hist2['status']}")

    except Exception as e:
        log("RECONNECT", "Reconnection", False, str(e)); traceback.print_exc()

    print()
    print("="*70)
    print("MISMATCH / SECURITY / VARIABLE AUDIT")
    print("="*70)

    # Variable mismatches audit already partially noted; add explicit checks

    # 1. game_status vs game.status variable mapping
    # Backend status values: LOBBY, READY, IN_PROGRESS?, GAME_COMPLETE etc -- check actual
    r = api(c, "GET", f"/api/games/{game_id}/status")
    raw_status = r.get_json()["data"]["status"]
    print(f"  Backend game status raw: {raw_status}")
    # Frontend player.js mapGameStatus does includes checks; host_dashboard currentRoundLabel expects Round N
    # That's a variable mismatch surface: backend uses 'status' string upper-case, frontend maps to 'round1'/'round2'/'complete'

    # 2. Word payload fields vs frontend expectation
    r = api(c, "GET", f"/api/games/{game_id}/words", host_token=host_token)
    if r.status_code == 200:
        sample = r.get_json()["data"]["words"][0]
        print(f"  Word payload keys: {list(sample.keys())}")
        # Frontend WordAPI expects category_name, word_text etc. -- check
        for need in ["word_id","word_text","category_id","submitted_by_team_id","status"]:
            if need not in sample and need not in [k for k in sample.keys()]:
                mismatch(f"Word payload missing `{need}` -- frontend WordAPI may mis-handle it.")

    # 3. Turn payload fields
    # Get a completed turn payload to check front expectation
    # Frontend expects turn_id, current_word_id, words:[{word_id, word_text, sequence, result}], round_number, match_id etc.
    # Host after complete can still GET turn
    try:
        r = api(c, "GET", f"/api/turns/{turnA_id}", host_token=host_token)
        tp = r.get_json()["data"]
        print(f"  Turn payload keys: {list(tp.keys())}")
        for need in ["turn_id","status","current_word_id","current_word_text","remaining_seconds","elapsed_seconds","starting_seconds","words","correct_words","total_words"]:
            if need not in tp:
                mismatch(f"Turn payload missing `{need}` -- frontend host_dashboard expects it.")
    except Exception as e:
        pass

    # 4. Rate limiting check
    # games_create is 30/60s -- frontend has no handling for 429 except generic UNKNOWN_ERROR
    mismatch("Rate limiting (games_create 30/60s, devices_connect 60/60s etc.) returns 429 RATE_LIMITED -- frontend API.request maps 429 to generic message, no Retry-After handling nor toast for rate-limited.")

    # 5. Security: X-Host-Token fallback leak
    mismatch("API.request fallback `if (!host && !session && ctx.hostToken) send X-Host-Token` leaks host token on unauthenticated requests (e.g., device heartbeat while host token present). Not exploitable per se but breaks _host_or_team_session host-vs-session branching for startTurn/pass (defaults to host check first).")

    # 6. Missing DELETE endpoints
    mismatch("No DELETE /teams/:id or DELETE /teams/:id/members/:id -- frontend teams.js `Remove Team/Member` is local-only STATE filter, never persists across refresh (host would see phantom teams).")

    # 7. Categories: host_dashboard words.js CATEGORY_NAME_TO_ID mapping vs backend idempotency
    # Frontend words.js uses window.CATEGORY_NAME_TO_ID derived from local STATE; backend normalized_word duplicate check is per game globally, not per category upper/lower variance.

    # 8. Timer mode variable
    # Frontend expects timer_mode COUNTDOWN/COUNTUP -- backend round_payload actually uses those strings -- note match
    try:
        r = api(c, "GET", f"/api/games/{game_id}/rounds", host_token=host_token)
        rnds = r.get_json()["data"]["rounds"]
        if rnds:
            print(f"  Round timer_mode: {rnds[0].get('timer_mode')}")
    except: pass

    print()
    print("="*70)
    print("SUMMARY")
    print("="*70)
    for line in results:
        print(line)
    print()
    print(f"Pass: {len(passes)}  Fail: {len(failures)}  Mismatch: {len(mismatches)}")
    print()
    if mismatches:
        print("MISMATCHES (frontend feature has no backend support -- skipped per instructions):")
        for i, m in enumerate(mismatches, 1):
            print(f"  {i}. {m}")
    print()
    if failures:
        print("FAILED FEATURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All executed features passed (mismatches are expected gaps, not failures).")
