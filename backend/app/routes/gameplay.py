from flask import Blueprint, request

from ..extensions import db
from ..models import (
    DeviceSession,
    Game,
    GameEvent,
    Match,
    Penalty,
    Turn,
    TurnWord,
)
from ..services import display_service, gameplay_service, realtime, turn_service
from ..utils.auth import host_authorized, host_token_from_request, require_host
from ..utils.response import error_response, success_response
from ..utils.time import utcnow

gameplay_bp = Blueprint("gameplay", __name__, url_prefix="/api")

SESSION_TOKEN_HEADER = "X-Session-Token"


def _handle(exc):
    return error_response(str(exc), code=exc.code, status=exc.status)


def _record_event(
    game_id, event_type, data=None, team_id=None, member_id=None
):
    db.session.add(
        GameEvent(
            game_id=game_id,
            team_id=team_id,
            member_id=member_id,
            event_type=event_type,
            event_data=data,
        )
    )


def _ensure_mutable(game):
    from ..services.game_service import GameFrozenError, assert_game_mutable

    try:
        assert_game_mutable(game)
    except GameFrozenError as exc:
        return error_response(str(exc), code=exc.code, status=exc.status)
    return None


def _match_or_error(match_id):
    match = db.session.get(Match, match_id)
    if match is None:
        return None, error_response(
            "Match not found.", code="MATCH_NOT_FOUND", status=404
        )
    return match, None


def _host_denied_for(match):
    token = host_token_from_request()
    if token is None or not host_authorized(match.game):
        return error_response(
            "Invalid or missing host session token.",
            code="UNAUTHORIZED",
            status=401,
        )
    return None


def _turn_or_error(turn_id):
    turn = db.session.get(Turn, turn_id)
    if turn is None:
        return None, error_response(
            "Turn not found.", code="TURN_NOT_FOUND", status=404
        )
    return turn, None


def _host_auth_only(match):
    token = host_token_from_request()
    if token is not None and host_authorized(match.game):
        return None
    return error_response(
        "Invalid or missing host session token.",
        code="UNAUTHORIZED",
        status=401,
    )


def _host_or_team_session(match):
    token = host_token_from_request()
    if token is not None:
        if host_authorized(match.game):
            return None
        return error_response(
            "Invalid or missing host session token.",
            code="UNAUTHORIZED",
            status=401,
        )
    session_token = request.headers.get(SESSION_TOKEN_HEADER)
    if turn_service.active_gameplay_session_for_team(
        match.team_id, session_token
    ):
        return None
    return error_response(
        "Host token or an active team member session is required.",
        code="UNAUTHORIZED",
        status=401,
    )


# ---------------------------------------------------------------------------
# Realtime emission helpers
# ---------------------------------------------------------------------------


def _word_result_snapshot(turn):
    return {
        turn_word.word_id: turn_word.result
        for turn_word in turn_service.ordered_words(turn)
    }


def _emit_word_changes(turn, before):
    changed = False
    for turn_word in turn_service.ordered_words(turn):
        if before.get(turn_word.word_id) == turn_word.result:
            continue
        changed = True
        if turn_word.result == TurnWord.RESULT_CORRECT:
            realtime.emit_word_result(turn, turn_word, "word_correct")
        elif turn_word.result == TurnWord.RESULT_PASSED:
            realtime.emit_word_result(turn, turn_word, "word_passed")
    if changed:
        realtime.emit_leaderboard(turn.match.game)


def _auto_advance_if_round_done(round_obj, game):
    """Open the next round when the current one just finished.

    Round 1 -> Round 2 runs the full setup path (round_updated + leaderboard);
    Round 2 -> auto game-over (game_completed). Anything out of order is left
    for the host to resolve manually.
    """
    from ..services.game_service import finalize_game

    if round_obj is None:
        return
    if round_obj.round_number == gameplay_service.ROUND_1:
        next_round = gameplay_service.get_round(
            game, gameplay_service.ROUND_2
        )
        if next_round is None:
            return
        try:
            gameplay_service.advance_round(
                game, gameplay_service.ROUND_1
            )
        except gameplay_service.GameplayServiceError:
            db.session.rollback()
            return
        db.session.commit()
        realtime.emit_round_updated(next_round)
        realtime.emit_leaderboard(game)
    elif round_obj.round_number == gameplay_service.ROUND_2:
        if finalize_game(game, auto=True):
            db.session.commit()
            realtime.emit_game_completed(game)


def _emit_turn_finished(turn, outcome=None):
    display_service.finish_display(turn.match.game)
    realtime.emit_turn_completed(turn, outcome=outcome)
    realtime.emit_leaderboard(turn.match.game)
    if realtime.mark_round_completed_if_done(turn.match):
        _record_event(
            turn.match.game_id,
            "ROUND_COMPLETED",
            {
                "round_id": turn.match.round_id,
                "round_number": turn.match.round.round_number
                if turn.match.round
                else None,
            },
        )
        db.session.commit()
        realtime.announce_round_completed(turn.match.round)
        _auto_advance_if_round_done(turn.match.round, turn.match.game)


def _after_time_adjustment(turn, delta):
    penalty = (
        Penalty.query.filter_by(turn_id=turn.id)
        .order_by(Penalty.id.desc())
        .first()
    )
    realtime.emit_time_adjusted(turn, penalty, delta)
    realtime.emit_leaderboard(turn.match.game)
    if turn.status in (
        Turn.STATUS_TIMEOUT,
        Turn.STATUS_COMPLETED,
        Turn.STATUS_FAILED,
    ):
        _emit_turn_finished(turn)


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------


@gameplay_bp.post("/games/<int:game_id>/rounds")
@require_host
def create_round(game):
    body = request.get_json(silent=True) or {}
    frozen = _ensure_mutable(game)
    if frozen is not None:
        return frozen
    try:
        round_obj = gameplay_service.create_round(
            game,
            body.get("round_number"),
            timer_seconds=body.get("timer_seconds"),
            timer_mode=body.get("timer_mode"),
        )
        db.session.commit()
    except gameplay_service.GameplayServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(
        data=gameplay_service.round_payload(round_obj), status=201
    )


@gameplay_bp.get("/games/<int:game_id>/rounds")
@require_host
def list_rounds(game):
    rounds = gameplay_service.list_game_rounds(game)
    return success_response(
        data={
            "rounds": [
                gameplay_service.round_payload(round_obj)
                for round_obj in rounds
            ]
        }
    )


@gameplay_bp.post("/games/<int:game_id>/rounds/<int:round_number>/categories")
@require_host
def select_round_categories(game, round_number):
    body = request.get_json(silent=True) or {}
    frozen = _ensure_mutable(game)
    if frozen is not None:
        return frozen
    try:
        round_obj = gameplay_service.select_round_categories(
            game, round_number, body.get("category_ids")
        )
        db.session.commit()
    except gameplay_service.GameplayServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(data=gameplay_service.round_payload(round_obj))


@gameplay_bp.get("/games/<int:game_id>/rounds/<int:round_number>/categories")
@require_host
def round_categories(game, round_number):
    try:
        data = gameplay_service.list_round_categories(game, round_number)
    except gameplay_service.GameplayServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(data=data)


@gameplay_bp.post("/games/<int:game_id>/rounds/<int:round_number>/timer")
@require_host
def update_round_timer(game, round_number):
    body = request.get_json(silent=True) or {}
    frozen = _ensure_mutable(game)
    if frozen is not None:
        return frozen
    try:
        round_obj = gameplay_service.update_round_timer(
            game,
            round_number,
            body.get("timer_seconds"),
            body.get("timer_mode"),
        )
        db.session.commit()
    except gameplay_service.GameplayServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    realtime.emit_round_updated(round_obj)
    return success_response(data=gameplay_service.round_payload(round_obj))


@gameplay_bp.post("/games/<int:game_id>/rounds/<int:round_number>/advance")
@require_host
def advance_round(game, round_number):
    frozen = _ensure_mutable(game)
    if frozen is not None:
        return frozen
    try:
        completed_round = gameplay_service.get_round(game, round_number)
        next_round = gameplay_service.advance_round(game, round_number)
        db.session.commit()
    except gameplay_service.GameplayServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    if completed_round is not None:
        realtime.announce_round_completed(completed_round)
        realtime.emit_leaderboard(game)
    realtime.emit_round_updated(next_round)
    return success_response(data=gameplay_service.round_payload(next_round))


@gameplay_bp.post("/games/<int:game_id>/rounds/<int:round_number>/reset")
@require_host
def reset_round(game, round_number):
    frozen = _ensure_mutable(game)
    if frozen is not None:
        return frozen
    try:
        round_obj = gameplay_service.reset_round(game, round_number)
        db.session.commit()
    except gameplay_service.GameplayServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    realtime.emit_round_updated(round_obj)
    return success_response(data=gameplay_service.round_payload(round_obj))


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------


@gameplay_bp.post("/games/<int:game_id>/matches")
@require_host
def create_matches(game):
    body = request.get_json(silent=True) or {}
    frozen = _ensure_mutable(game)
    if frozen is not None:
        return frozen
    try:
        matches = gameplay_service.create_round_matches(
            game,
            body.get("round_number"),
            body.get("matches"),
        )
        db.session.commit()
    except gameplay_service.GameplayServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(
        data={
            "matches": [
                gameplay_service.match_payload(match) for match in matches
            ]
        },
        status=201,
    )


@gameplay_bp.get("/games/<int:game_id>/matches")
@require_host
def list_matches(game):
    from ..models import Team

    # During LOBBY/SETUP the dashboard's Current Turn dropdown needs a play
    # slot per team even before the host manually creates matches. Running the
    # setup (idempotently) here mirrors what starting the game does, so the
    # host can pick the first team the moment one joins. The LOBBY path only
    # prepares Round 1 (the dropdown's current round); Round 2 is created when
    # the game actually starts.
    if game.status in (Game.STATUS_LOBBY, Game.STATUS_SETUP):
        has_teams = (
            db.session.query(Team.id).filter_by(game_id=game.id).first()
            is not None
        )
        if has_teams:
            try:
                if game.status == Game.STATUS_LOBBY:
                    gameplay_service.ensure_game_setup(
                        game, round_numbers=(gameplay_service.ROUND_1,)
                    )
                else:
                    gameplay_service.ensure_game_setup(game)
                db.session.commit()
            except gameplay_service.GameplayServiceError:
                db.session.rollback()
    matches = gameplay_service.list_game_matches(game)
    return success_response(
        data={
            "matches": [
                gameplay_service.match_payload(match) for match in matches
            ]
        }
    )


@gameplay_bp.patch("/matches/<int:match_id>")
def update_match(match_id):
    match, error = _match_or_error(match_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(match.game)
    if frozen is not None:
        return frozen
    denied = _host_denied_for(match)
    if denied is not None:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        match = gameplay_service.reorder_match(match, body.get("match_order"))
        db.session.commit()
    except gameplay_service.GameplayServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(data=gameplay_service.match_payload(match))


@gameplay_bp.post("/matches/<int:match_id>/category")
def select_match_category(match_id):
    """Team (or host) picks one category for this Round 1 match."""
    match, error = _match_or_error(match_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(match.game)
    if frozen is not None:
        return frozen
    denied = _host_or_team_session(match)
    if denied is not None:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        match = gameplay_service.select_match_category(
            match, body.get("category_id")
        )
        db.session.commit()
    except gameplay_service.GameplayServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    realtime.emit_category_selected(match.game, match)
    return success_response(data=gameplay_service.match_payload(match))


# ---------------------------------------------------------------------------
# Turns & word assignment
# ---------------------------------------------------------------------------


@gameplay_bp.post("/matches/<int:match_id>/turns")
def create_turn(match_id):
    match, error = _match_or_error(match_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(match.game)
    if frozen is not None:
        return frozen
    denied = _host_denied_for(match)
    if denied is not None:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        turn = gameplay_service.assign_turn_words(
            match,
            word_ids=body.get("word_ids"),
            count=body.get("count"),
        )
        db.session.commit()
    except gameplay_service.GameplayServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(
        data=gameplay_service.turn_payload(turn), status=201
    )


@gameplay_bp.get("/matches/<int:match_id>/turns")
def list_turns(match_id):
    match, error = _match_or_error(match_id)
    if error is not None:
        return error
    denied = _host_denied_for(match)
    if denied is not None:
        return denied
    turns = (
        Turn.query.filter_by(match_id=match.id)
        .order_by(Turn.turn_order)
        .all()
    )
    return success_response(
        data={"turns": [gameplay_service.turn_payload(t) for t in turns]}
    )


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


@gameplay_bp.get("/games/<int:game_id>/readiness")
@require_host
def game_readiness(game):
    return success_response(data=gameplay_service.readiness(game))


# ---------------------------------------------------------------------------
# Two-stage display start (host START -> ARM -> GO -> countdown -> turn)
# ---------------------------------------------------------------------------


def _display_not_ready(issues):
    return error_response(
        "The game is not ready to start this turn.",
        code="DISPLAY_NOT_READY",
        status=400,
        issues=issues,
    )


def _display_match_for(game, body):
    match_id = body.get("match_id")
    if not match_id:
        return None
    match = db.session.get(Match, match_id)
    if match is None or match.game_id != game.id:
        return None
    return match


@gameplay_bp.post("/games/<int:game_id>/display/ready")
@require_host
def display_ready(game):
    body = request.get_json(silent=True) or {}
    frozen = _ensure_mutable(game)
    if frozen is not None:
        return frozen
    match = _display_match_for(game, body)
    issues = display_service.start_readiness(game, match)
    if issues:
        # Invalid START keeps the game un-armed; the host gets the checklist.
        game.display_status = display_service.DISPLAY_IDLE
        db.session.commit()
        return _display_not_ready(issues)
    payload = display_service.arm(game, match)
    realtime.emit_display_armed(game, match)
    return success_response(data=payload)


@gameplay_bp.post("/games/<int:game_id>/display/go")
@require_host
def display_go(game):
    body = request.get_json(silent=True) or {}
    if game.display_status != display_service.DISPLAY_ARMED:
        return error_response(
            "Nothing is armed — click START first.",
            code="DISPLAY_NOT_ARMED",
            status=409,
        )
    match = _display_match_for(game, body)
    if match is None or match.id != game.display_go_match_id:
        return error_response(
            "The armed match is no longer valid.",
            code="DISPLAY_NOT_READY",
            status=409,
        )
    frozen = _ensure_mutable(game)
    if frozen is not None:
        display_service.reset_display(game)
        realtime.emit_display_cancelled(game, match)
        return frozen
    # GO re-validates: if the game became un-startable, revert to IDLE.
    issues = display_service.start_readiness(game, match)
    if issues:
        display_service.reset_display(game)
        realtime.emit_display_cancelled(game, match)
        return _display_not_ready(issues)
    payload = display_service.set_countdown(game, match)
    realtime.emit_display_go(game, match)
    return success_response(data=payload)


@gameplay_bp.get("/games/<int:game_id>/display/state")
def display_state(game_id):
    game = db.session.get(Game, game_id)
    if game is None:
        return error_response(
            "Game not found.", code="GAME_NOT_FOUND", status=404
        )
    token = host_token_from_request()
    member_id = None
    if token is None or not host_authorized(game):
        session_token = request.headers.get(SESSION_TOKEN_HEADER)
        session = (
            DeviceSession.query.filter_by(
                session_token=session_token, disconnected_at=None
            ).first()
            if session_token
            else None
        )
        if (
            session is None
            or session.game_id != game.id
            or session.member_id is None
        ):
            return error_response(
                "Host token or an active device session is required.",
                code="UNAUTHORIZED",
                status=401,
            )
        member_id = session.member_id
    # A delayed read recovers a countdown whose deferred task was lost
    # (process restart) — server-authoritative, idempotent.
    display_service.start_pending_go_if_ready(game)
    return success_response(
        data=display_service.state_payload(game, member_id=member_id)
    )


# ---------------------------------------------------------------------------
# Turn gameplay
# ---------------------------------------------------------------------------


@gameplay_bp.post("/matches/<int:match_id>/turn/start")
def start_turn(match_id):
    match, error = _match_or_error(match_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(match.game)
    if frozen is not None:
        return frozen
    denied = _host_or_team_session(match)
    if denied is not None:
        return denied
    round_obj = match.round
    round_starts_now = round_obj is not None and round_obj.started_at is None
    match_was_active = match.status == Match.STATUS_ACTIVE
    try:
        turn = turn_service.start_turn(match)
        if round_starts_now:
            round_obj.started_at = utcnow()
            match.game.current_round = round_obj.round_number
            match.game.current_match_id = match.id
        if round_starts_now:
            _record_event(
                round_obj.game_id,
                "ROUND_STARTED",
                {
                    "round_id": round_obj.id,
                    "round_number": round_obj.round_number,
                },
            )
        if not match_was_active:
            _record_event(
                match.game_id,
                "MATCH_STARTED",
                {"match_id": match.id, "round_id": match.round_id},
                team_id=match.team_id,
            )
        db.session.commit()
    except turn_service.TurnServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    if round_starts_now:
        realtime.emit_round_started(round_obj)
    if not match_was_active:
        realtime.emit_match_started(match)
    realtime.emit_turn_started(turn)
    return success_response(data=turn_service.turn_play_payload(turn))


@gameplay_bp.post("/turns/<int:turn_id>/correct")
def correct_turn(turn_id):
    turn, error = _turn_or_error(turn_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(turn.match.game)
    if frozen is not None:
        return frozen
    denied = _host_auth_only(turn.match)
    if denied is not None:
        return denied
    before = _word_result_snapshot(turn)
    try:
        turn, outcome = turn_service.correct_word(turn)
        db.session.commit()
    except turn_service.TurnTimedOutError as exc:
        db.session.commit()
        _emit_turn_finished(turn)
        return _handle(exc)
    except turn_service.TurnServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    _emit_word_changes(turn, before)
    if turn.status in (
        Turn.STATUS_TIMEOUT,
        Turn.STATUS_COMPLETED,
        Turn.STATUS_FAILED,
    ):
        _emit_turn_finished(turn, outcome=outcome)
    payload = turn_service.turn_play_payload(turn, outcome=outcome)
    return success_response(data=payload)


@gameplay_bp.post("/turns/<int:turn_id>/pass")
def pass_turn(turn_id):
    turn, error = _turn_or_error(turn_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(turn.match.game)
    if frozen is not None:
        return frozen
    denied = _host_or_team_session(turn.match)
    if denied is not None:
        return denied
    before = _word_result_snapshot(turn)
    try:
        turn, outcome = turn_service.pass_word(turn)
        db.session.commit()
    except turn_service.TurnTimedOutError as exc:
        db.session.commit()
        _emit_turn_finished(turn)
        return _handle(exc)
    except turn_service.TurnServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    _emit_word_changes(turn, before)
    if turn.status in (
        Turn.STATUS_TIMEOUT,
        Turn.STATUS_COMPLETED,
        Turn.STATUS_FAILED,
    ):
        _emit_turn_finished(turn, outcome=outcome)
    return success_response(
        data=turn_service.turn_play_payload(turn, outcome=outcome)
    )


@gameplay_bp.post("/turns/<int:turn_id>/timeout")
def timeout_turn(turn_id):
    turn, error = _turn_or_error(turn_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(turn.match.game)
    if frozen is not None:
        return frozen
    denied = _host_auth_only(turn.match)
    if denied is not None:
        return denied
    try:
        turn = turn_service.force_timeout(turn)
        db.session.commit()
    except turn_service.TurnServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    _emit_turn_finished(turn)
    return success_response(data=turn_service.turn_play_payload(turn))


@gameplay_bp.get("/turns/<int:turn_id>")
def get_turn(turn_id):
    turn, error = _turn_or_error(turn_id)
    if error is not None:
        return error
    denied = _host_or_team_session(turn.match)
    if denied is not None:
        return denied
    token = host_token_from_request()
    if token is not None and host_authorized(turn.match.game):
        return success_response(data=turn_service.turn_play_payload(turn))
    session_token = request.headers.get(SESSION_TOKEN_HEADER)
    if _session_can_see_secret(turn.match, session_token):
        return success_response(data=turn_service.turn_play_payload(turn))
    return success_response(data=turn_service.public_turn_payload(turn))


def _session_can_see_secret(match, session_token):
    from ..models import TeamMember

    if not session_token:
        return False
    session = turn_service.active_gameplay_session_for_team(
        match.team_id, session_token
    )
    if session is None or session.member_id is None:
        return False
    member = db.session.get(TeamMember, session.member_id)
    if (
        member is not None
        and member.gameplay_role == TeamMember.GAMEPLAY_ROLE_MANGHUHULA
    ):
        return True
    # A team-leader phone acting as the fallback display target may also
    # recover the full (secret) turn on reconnect. Resolution is dynamic:
    # only used while that device is the current resolved target.
    resolution = display_service.display_target_resolution(
        match.game_id, match.team_id
    )
    return member is not None and member.id in resolution["member_ids"]


@gameplay_bp.get("/games/<int:game_id>/scores")
@require_host
def game_scores(game):
    return success_response(data={"scores": turn_service.game_scores(game)})


# ---------------------------------------------------------------------------
# Timer controls (host only, server authoritative)
# ---------------------------------------------------------------------------


def _apply_turn_run(turn, action, *args, after=None, **kwargs):
    try:
        result = action(turn, *args, **kwargs)
        db.session.commit()
    except turn_service.TurnTimedOutError as exc:
        db.session.commit()
        _emit_turn_finished(turn)
        return _handle(exc)
    except turn_service.TurnServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    if after is not None:
        after(result)
    return success_response(data=turn_service.turn_play_payload(result))


@gameplay_bp.post("/turns/<int:turn_id>/pause")
def pause_turn(turn_id):
    turn, error = _turn_or_error(turn_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(turn.match.game)
    if frozen is not None:
        return frozen
    denied = _host_auth_only(turn.match)
    if denied is not None:
        return denied
    return _apply_turn_run(
        turn, turn_service.pause_turn, after=realtime.emit_timer_paused
    )


@gameplay_bp.post("/turns/<int:turn_id>/resume")
def resume_turn(turn_id):
    turn, error = _turn_or_error(turn_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(turn.match.game)
    if frozen is not None:
        return frozen
    denied = _host_auth_only(turn.match)
    if denied is not None:
        return denied
    return _apply_turn_run(
        turn, turn_service.resume_turn, after=realtime.emit_timer_resumed
    )


def _seconds_from_body(body):
    return body.get("seconds")


@gameplay_bp.post("/turns/<int:turn_id>/time/add")
def add_turn_time(turn_id):
    turn, error = _turn_or_error(turn_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(turn.match.game)
    if frozen is not None:
        return frozen
    denied = _host_auth_only(turn.match)
    if denied is not None:
        return denied
    body = request.get_json(silent=True) or {}
    seconds = _seconds_from_body(body)
    return _apply_turn_run(
        turn,
        turn_service.adjust_time,
        seconds,
        reason=body.get("reason"),
        mode="add",
        after=lambda t: _after_time_adjustment(t, int(seconds)),
    )


@gameplay_bp.post("/turns/<int:turn_id>/time/remove")
def remove_turn_time(turn_id):
    turn, error = _turn_or_error(turn_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(turn.match.game)
    if frozen is not None:
        return frozen
    denied = _host_auth_only(turn.match)
    if denied is not None:
        return denied
    body = request.get_json(silent=True) or {}
    seconds = _seconds_from_body(body)
    return _apply_turn_run(
        turn,
        turn_service.adjust_time,
        seconds,
        reason=body.get("reason"),
        mode="remove",
        after=lambda t: _after_time_adjustment(t, -int(seconds)),
    )


@gameplay_bp.post("/turns/<int:turn_id>/end")
def end_turn(turn_id):
    turn, error = _turn_or_error(turn_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(turn.match.game)
    if frozen is not None:
        return frozen
    denied = _host_auth_only(turn.match)
    if denied is not None:
        return denied
    return _apply_turn_run(
        turn, turn_service.end_turn, after=_emit_turn_finished
    )


@gameplay_bp.post("/turns/<int:turn_id>/reset")
def reset_turn(turn_id):
    """Replay a finished turn: re-open the board, wipe words/scores/penalties."""
    turn, error = _turn_or_error(turn_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(turn.match.game)
    if frozen is not None:
        return frozen
    denied = _host_auth_only(turn.match)
    if denied is not None:
        return denied
    result = turn_service.turn_result_payload(turn)
    try:
        turn = turn_service.reset_turn(turn)
        db.session.commit()
    except turn_service.TurnServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    realtime.emit_turn_reset(turn, result)
    realtime.emit_leaderboard(turn.match.game)
    if turn.match.round and turn.match.round.status != turn.match.round.STATUS_PENDING:
        realtime.emit_round_updated(turn.match.round)
    return success_response(data=turn_service.turn_play_payload(turn))


@gameplay_bp.get("/turns/<int:turn_id>/result")
def get_turn_result(turn_id):
    """Persistent result view of a finished turn (host or team member)."""
    turn, error = _turn_or_error(turn_id)
    if error is not None:
        return error
    denied = _host_or_team_session(turn.match)
    if denied is not None:
        return denied
    payload = turn_service.turn_result_payload(turn)
    token = host_token_from_request()
    can_see_secret = token is not None and host_authorized(turn.match.game)
    if not can_see_secret:
        session_token = request.headers.get(SESSION_TOKEN_HEADER)
        can_see_secret = _session_can_see_secret(turn.match, session_token)
    if not can_see_secret:
        for item in payload["words"]:
            item["word_text"] = None
    return success_response(data=payload)


@gameplay_bp.get("/turns/<int:turn_id>/penalties")
def get_penalties(turn_id):
    turn, error = _turn_or_error(turn_id)
    if error is not None:
        return error
    return success_response(
        data={"penalties": turn_service.get_penalties_for_turn(turn_id)}
    )


@gameplay_bp.post("/penalties/<int:penalty_id>/revert")
def revert_penalty(penalty_id):
    body = request.get_json(silent=True) or {}
    token = host_token_from_request()
    if not token:
        return error_response(
            "Host token required.", code="UNAUTHORIZED", status=401,
        )
    try:
        reversal = turn_service.revert_penalty(
            penalty_id, reason=body.get("reason")
        )
        db.session.commit()
    except turn_service.TurnServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(data={
        "penalty_id": reversal.id,
        "original_penalty_id": penalty_id,
        "type": reversal.type,
        "seconds": reversal.seconds,
    })