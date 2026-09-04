from ..extensions import db
from ..models import (
    DeviceSession,
    GameEvent,
    Match,
    Penalty,
    Round,
    Score,
    Team,
    TeamMember,
    Turn,
    TurnWord,
)
from ..utils.time import utcnow
from ..services.gameplay_service import MAX_TIMER_SECONDS, MAX_WORDS_PER_TURN

MIN_CORRECT_WORDS = 3
TIE_BREAKER_ROUND_NUMBER = 3
TIE_BREAKER_TIME_SECONDS = 60


class TurnServiceError(Exception):
    status = 400
    code = "TURN_SERVICE_ERROR"


class TurnNotFoundError(TurnServiceError):
    status = 404
    code = "TURN_NOT_FOUND"


class MatchNotFoundError(TurnServiceError):
    status = 404
    code = "MATCH_NOT_FOUND"


class MatchAlreadyPlayedError(TurnServiceError):
    status = 409
    code = "MATCH_ALREADY_PLAYED"


class DuplicateActiveTurnError(TurnServiceError):
    status = 409
    code = "DUPLICATE_ACTIVE_TURN"


class NoTurnAvailableError(TurnServiceError):
    status = 409
    code = "NO_TURN_AVAILABLE"


class NoWordsAssignedError(TurnServiceError):
    status = 409
    code = "NO_WORDS_ASSIGNED"


class RolesNotAssignedError(TurnServiceError):
    status = 409
    code = "ROLES_NOT_ASSIGNED"


class TurnLimitExceededError(TurnServiceError):
    status = 400
    code = "TURN_LIMIT_EXCEEDED"


class TurnNotActiveError(TurnServiceError):
    status = 409
    code = "TURN_NOT_ACTIVE"


class TurnTimedOutError(TurnServiceError):
    status = 409
    code = "TURN_TIMED_OUT"


class InvalidTimeDeltaError(TurnServiceError):
    status = 400
    code = "INVALID_TIME_DELTA"


class TimeBelowZeroError(TurnServiceError):
    status = 400
    code = "TIME_BELOW_ZERO"


class TimeAboveMaxError(TurnServiceError):
    status = 400
    code = "TIME_ABOVE_MAX"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def get_turn(turn_id):
    return db.session.get(Turn, turn_id) if turn_id is not None else None


def get_match(match_id):
    return db.session.get(Match, match_id) if match_id is not None else None


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


def ordered_words(turn):
    return sorted(turn.turn_words, key=lambda item: item.sequence)


def current_turn_word(turn):
    return next(
        (w for w in ordered_words(turn) if w.result == TurnWord.RESULT_PENDING),
        None,
    )


def count_results(turn, result):
    return sum(1 for w in turn.turn_words if w.result == result)


def timer_mode_of(turn):
    return (
        turn.round.timer_mode
        if turn.round is not None
        else Round.TIMER_MODE_COUNTDOWN
    )


def _elapsed_seconds(turn):
    if turn.started_at is None:
        return 0.0
    paused = turn.status == Turn.STATUS_PAUSED or turn.paused_at is not None
    if paused:
        return float(turn.pause_total_seconds or 0)
    return float(turn.pause_total_seconds or 0) + (
        utcnow() - turn.started_at
    ).total_seconds()


def _net_adjustment(turn):
    return int(turn.timer_adjustment_seconds or 0)


def _remaining_seconds(turn):
    if turn.status in (
        Turn.STATUS_TIMEOUT,
        Turn.STATUS_COMPLETED,
        Turn.STATUS_FAILED,
    ):
        return int(turn.remaining_seconds or 0)
    if turn.started_at is None:
        return int(turn.starting_seconds or 0)
    remaining = (
        (turn.starting_seconds or 0)
        - _elapsed_seconds(turn)
        + _net_adjustment(turn)
    )
    return max(0, int(remaining))


def _elapsed_display_seconds(turn):
    elapsed = int(_elapsed_seconds(turn))
    cap = int(turn.starting_seconds or 0)
    if timer_mode_of(turn) == Round.TIMER_MODE_COUNTUP:
        return min(elapsed, cap)
    return elapsed


def _expire_if_timed_out(turn):
    if turn.status != Turn.STATUS_ACTIVE:
        return False
    if _remaining_seconds(turn) > 0:
        return False
    turn.status = Turn.STATUS_TIMEOUT
    turn.remaining_seconds = 0
    turn.ended_at = utcnow()
    _record_event(
        turn.match.game_id,
        "TURN_COMPLETED",
        {"turn_id": turn.id, "won": False, "result": Turn.STATUS_TIMEOUT},
        team_id=turn.team_id,
    )
    _end_match_if_no_turns_left(turn.match)
    return True


def _end_match_if_no_turns_left(match):
    if match.status == Match.STATUS_COMPLETED:
        return
    waiting = Turn.query.filter_by(
        match_id=match.id, status=Turn.STATUS_WAITING
    ).count()
    if waiting == 0:
        match.status = Match.STATUS_COMPLETED
        match.ended_at = utcnow()


def _get_or_create_score(turn):
    match = turn.match
    score = Score.query.filter_by(
        game_id=match.game_id,
        team_id=turn.team_id,
        round_id=turn.round_id,
        match_id=match.id,
    ).first()
    if score is None:
        score = Score(
            game_id=match.game_id,
            team_id=turn.team_id,
            round_id=turn.round_id,
            match_id=match.id,
        )
        db.session.add(score)
        db.session.flush()
    return score


def _complete_turn_as_win(turn):
    turn.status = Turn.STATUS_COMPLETED
    turn.remaining_seconds = _remaining_seconds(turn)
    turn.ended_at = utcnow()
    match = turn.match
    match.status = Match.STATUS_COMPLETED
    match.winner_team_id = turn.team_id
    match.ended_at = utcnow()
    _record_event(
        match.game_id,
        "TURN_COMPLETED",
        {"turn_id": turn.id, "won": True, "result": Turn.STATUS_COMPLETED},
        team_id=turn.team_id,
    )


def _complete_turn_without_win(turn):
    turn.status = Turn.STATUS_COMPLETED
    turn.remaining_seconds = _remaining_seconds(turn)
    turn.ended_at = utcnow()
    _record_event(
        turn.match.game_id,
        "TURN_COMPLETED",
        {"turn_id": turn.id, "won": False, "result": Turn.STATUS_COMPLETED},
        team_id=turn.team_id,
    )
    _end_match_if_no_turns_left(turn.match)


def _advance_to_next_word(turn):
    turn_word = current_turn_word(turn)
    if turn_word is None:
        _complete_turn_without_win(turn)
        return
    turn.current_word_id = turn_word.word_id


def active_gameplay_session_for_team(team_id, session_token):
    if not session_token:
        return None
    session = DeviceSession.query.filter_by(
        session_token=session_token, disconnected_at=None
    ).first()
    if session is None or session.team_id != team_id or session.member_id is None:
        return None
    member = session.member
    if not member.is_connected or member.gameplay_role is None:
        return None
    return session


# ---------------------------------------------------------------------------
# Start turn
# ---------------------------------------------------------------------------


def start_turn(match):
    if match.status == Match.STATUS_COMPLETED:
        raise MatchAlreadyPlayedError(
            "This match has already been completed."
        )
    active = Turn.query.filter_by(
        match_id=match.id, status=Turn.STATUS_ACTIVE
    ).first()
    if active is not None:
        raise DuplicateActiveTurnError(
            "A turn is already active for this match."
        )
    turn = (
        Turn.query.filter_by(match_id=match.id, status=Turn.STATUS_WAITING)
        .order_by(Turn.turn_order)
        .first()
    )
    if turn is None:
        raise NoTurnAvailableError(
            "No pending turn is available for this match."
        )
    members = turn.team.members if turn.team is not None else []
    has_manghuhula = any(
        member.gameplay_role == TeamMember.GAMEPLAY_ROLE_MANGHUHULA
        for member in members
    )
    has_tagasagot = any(
        member.gameplay_role == TeamMember.GAMEPLAY_ROLE_TAGASAGOT
        for member in members
    )
    if not (has_manghuhula and has_tagasagot):
        raise RolesNotAssignedError(
            "The team must have a Manghuhula and a Tagasagot assigned."
        )
    words = ordered_words(turn)
    if not words:
        raise NoWordsAssignedError(
            "The turn has no words assigned."
        )
    if len(words) > MAX_WORDS_PER_TURN:
        raise TurnLimitExceededError(
            "A turn can contain at most {} words.".format(MAX_WORDS_PER_TURN)
        )
    timer = turn.round.timer_seconds if turn.round is not None else 60
    turn.starting_seconds = timer
    turn.remaining_seconds = timer
    turn.pause_total_seconds = 0
    turn.paused_at = None
    turn.timer_adjustment_seconds = 0
    turn.started_at = utcnow()
    turn.status = Turn.STATUS_ACTIVE
    turn.current_word_id = words[0].word_id
    match.status = Match.STATUS_ACTIVE
    _record_event(
        match.game_id,
        "TURN_STARTED",
        {"turn_id": turn.id, "match_id": match.id},
        team_id=turn.team_id,
    )
    return turn


# ---------------------------------------------------------------------------
# Correct
# ---------------------------------------------------------------------------


def correct_word(turn):
    if turn.status != Turn.STATUS_ACTIVE:
        raise TurnNotActiveError(
            "Only an active turn can be marked correct."
        )
    if _expire_if_timed_out(turn):
        raise TurnTimedOutError("The turn reached its time limit.")
    turn_word = current_turn_word(turn)
    if turn_word is None:
        raise TurnNotActiveError(
            "The turn has no pending words to mark correct."
        )
    turn_word.result = TurnWord.RESULT_CORRECT
    turn_word.used_at = utcnow()
    score = _get_or_create_score(turn)
    score.points += 1
    score.correct_words += 1
    turn.remaining_seconds = _remaining_seconds(turn)
    _record_event(
        turn.match.game_id,
        "WORD_CORRECT",
        {"turn_id": turn.id, "word_id": turn_word.word_id},
        team_id=turn.team_id,
    )

    correct_total = count_results(turn, TurnWord.RESULT_CORRECT)
    if correct_total >= MIN_CORRECT_WORDS:
        _complete_turn_as_win(turn)
        pairing = maybe_resolve_pairing(turn.match)
        return turn, {
            "won": True,
            "correct_words": correct_total,
            "pairing": pairing,
        }
    _advance_to_next_word(turn)
    if turn.status == Turn.STATUS_COMPLETED:
        pairing = maybe_resolve_pairing(turn.match)
        return turn, {
            "won": False,
            "correct_words": correct_total,
            "pairing": pairing,
        }
    return turn, {
        "won": False,
        "correct_words": correct_total,
        "pairing": None,
    }


# ---------------------------------------------------------------------------
# Pass
# ---------------------------------------------------------------------------


def pass_word(turn):
    if turn.status != Turn.STATUS_ACTIVE:
        raise TurnNotActiveError(
            "Only an active turn can pass a word."
        )
    if _expire_if_timed_out(turn):
        raise TurnTimedOutError("The turn reached its time limit.")
    turn_word = current_turn_word(turn)
    if turn_word is None:
        raise TurnNotActiveError(
            "The turn has no pending words to pass."
        )
    turn_word.result = TurnWord.RESULT_PASSED
    turn_word.used_at = utcnow()
    score = _get_or_create_score(turn)
    score.passed_words += 1
    turn.remaining_seconds = _remaining_seconds(turn)
    _record_event(
        turn.match.game_id,
        "WORD_PASSED",
        {"turn_id": turn.id, "word_id": turn_word.word_id},
        team_id=turn.team_id,
    )
    _advance_to_next_word(turn)
    if turn.status == Turn.STATUS_COMPLETED:
        pairing = maybe_resolve_pairing(turn.match)
        return turn, {"won": False, "pairing": pairing}
    return turn, {"won": False, "pairing": None}


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def force_timeout(turn):
    if turn.status != Turn.STATUS_ACTIVE:
        raise TurnNotActiveError(
            "Only an active turn can time out."
        )
    turn.status = Turn.STATUS_TIMEOUT
    turn.remaining_seconds = 0
    turn.ended_at = utcnow()
    _record_event(
        turn.match.game_id,
        "TURN_COMPLETED",
        {"turn_id": turn.id, "won": False, "result": Turn.STATUS_TIMEOUT},
        team_id=turn.team_id,
    )
    _end_match_if_no_turns_left(turn.match)
    return turn


# ---------------------------------------------------------------------------
# Timer controls (pause, resume, adjust, end)
# ---------------------------------------------------------------------------


def pause_turn(turn):
    if turn.status != Turn.STATUS_ACTIVE:
        raise TurnNotActiveError(
            "Only an active turn can be paused."
        )
    if _expire_if_timed_out(turn):
        raise TurnTimedOutError(
            "The turn reached its time limit before it could be paused."
        )
    turn.pause_total_seconds = _elapsed_seconds(turn)
    turn.paused_at = utcnow()
    turn.remaining_seconds = _remaining_seconds(turn)
    turn.status = Turn.STATUS_PAUSED
    return turn


def resume_turn(turn):
    if turn.status != Turn.STATUS_PAUSED:
        raise TurnNotActiveError(
            "Only a paused turn can be resumed."
        )
    turn.started_at = utcnow()
    turn.paused_at = None
    turn.status = Turn.STATUS_ACTIVE
    return turn


def end_turn(turn):
    if _expire_if_timed_out(turn):
        raise TurnTimedOutError(
            "The turn already reached its time limit."
        )
    if turn.status not in (Turn.STATUS_ACTIVE, Turn.STATUS_PAUSED):
        raise TurnNotActiveError(
            "Only an active or paused turn can be ended."
        )
    turn.remaining_seconds = _remaining_seconds(turn)
    for turn_word in ordered_words(turn):
        if turn_word.result == TurnWord.RESULT_PENDING:
            turn_word.result = TurnWord.RESULT_FAILED
            turn_word.used_at = utcnow()
            score = _get_or_create_score(turn)
            score.failed_words += 1
    turn.status = Turn.STATUS_TIMEOUT
    turn.paused_at = None
    turn.ended_at = utcnow()
    _record_event(
        turn.match.game_id,
        "TURN_COMPLETED",
        {"turn_id": turn.id, "won": False, "result": Turn.STATUS_TIMEOUT},
        team_id=turn.team_id,
    )
    _end_match_if_no_turns_left(turn.match)
    return turn


def _record_penalty(turn, delta, reason=None):
    delta = int(delta)
    if delta < 0:
        penalty_type = Penalty.TYPE_REMOVE_TIME
        default_reason = "Oo/Hindi/Pwede misuse."
    else:
        penalty_type = Penalty.TYPE_ADD_TIME
        default_reason = "Judge correction."
    penalty = Penalty(
        turn_id=turn.id,
        team_id=turn.team_id,
        seconds=abs(delta),
        type=penalty_type,
        reason=reason or default_reason,
    )
    db.session.add(penalty)
    return penalty


def _record_score_adjustment(turn, delta):
    score = _get_or_create_score(turn)
    if delta < 0:
        score.penalty_seconds += abs(delta)
    else:
        score.time_bonus_seconds += delta


def adjust_time(turn, seconds, reason=None, mode=None):
    if turn.status not in (Turn.STATUS_ACTIVE, Turn.STATUS_PAUSED):
        raise TurnNotActiveError(
            "Only an active or paused turn can have its time adjusted."
        )
    if _expire_if_timed_out(turn):
        raise TurnTimedOutError(
            "The turn reached its time limit."
        )
    if (
        not isinstance(seconds, int)
        or isinstance(seconds, bool)
        or seconds <= 0
    ):
        raise InvalidTimeDeltaError(
            "The adjustment must be a positive number of seconds."
        )
    delta = -seconds if mode == "remove" else seconds
    current = _remaining_seconds(turn)
    proposed = current + delta
    if proposed < 0:
        raise TimeBelowZeroError(
            "The remaining time cannot go below zero seconds."
        )
    if proposed > MAX_TIMER_SECONDS:
        raise TimeAboveMaxError(
            "The total time cannot exceed {} seconds.".format(MAX_TIMER_SECONDS)
        )
    turn.timer_adjustment_seconds = _net_adjustment(turn) + delta
    turn.remaining_seconds = proposed
    penalty = _record_penalty(turn, delta, reason)
    _record_score_adjustment(turn, delta)
    _record_event(
        turn.match.game_id,
        "PENALTY_APPLIED",
        {
            "turn_id": turn.id,
            "penalty_id": penalty.id,
            "type": penalty.type,
            "seconds": penalty.seconds,
            "reason": penalty.reason,
        },
        team_id=turn.team_id,
    )
    _record_event(
        turn.match.game_id,
        "TIME_ADDED" if delta > 0 else "TIME_REMOVED",
        {
            "turn_id": turn.id,
            "seconds": abs(delta),
            "remaining_seconds": proposed,
        },
        team_id=turn.team_id,
    )
    if proposed == 0 and delta < 0:
        turn.status = Turn.STATUS_TIMEOUT
        turn.remaining_seconds = 0
        turn.ended_at = utcnow()
        _record_event(
            turn.match.game_id,
            "TURN_COMPLETED",
            {"turn_id": turn.id, "won": False, "result": Turn.STATUS_TIMEOUT},
            team_id=turn.team_id,
        )
        _end_match_if_no_turns_left(turn.match)
    return turn


def get_penalties_for_turn(turn_id):
    """Return all penalties for a turn as a list of dicts."""
    penalties = Penalty.query.filter_by(turn_id=turn_id).order_by(Penalty.id).all()
    return [
        {
            "penalty_id": p.id,
            "turn_id": p.turn_id,
            "team_id": p.team_id,
            "seconds": p.seconds,
            "type": p.type,
            "reason": p.reason,
            "created_at": p.created_at,
        }
        for p in penalties
    ]


def revert_penalty(penalty_id, reason=None):
    """Revert a previously applied penalty.

    Adds a REVERSAL entry that offsets the original penalty, and adjusts
    the turn's timer and score accordingly.
    """
    penalty = db.session.get(Penalty, penalty_id)
    if penalty is None:
        raise TurnServiceError("Penalty not found.")
    turn = db.session.get(Turn, penalty.turn_id)
    if turn is None:
        raise TurnServiceError("Turn not found.")
    if turn.status not in (Turn.STATUS_ACTIVE, Turn.STATUS_PAUSED):
        raise TurnNotActiveError("Turn is not active or paused.")

    # Determine reversal delta: ADD_TIME penalties are reversed by removing time
    # and vice-versa.
    if penalty.type == Penalty.TYPE_ADD_TIME:
        reversal_delta = -penalty.seconds
    elif penalty.type == Penalty.TYPE_REMOVE_TIME:
        reversal_delta = penalty.seconds
    else:
        raise TurnServiceError("This penalty type cannot be reverted.")

    reversal = Penalty(
        turn_id=turn.id,
        team_id=turn.team_id,
        seconds=penalty.seconds,
        type=Penalty.TYPE_REVERSAL,
        reason=reason or "Reverted: {}".format(penalty.reason or penalty.type),
    )
    db.session.add(reversal)
    turn.timer_adjustment_seconds = _net_adjustment(turn) + reversal_delta
    current = _remaining_seconds(turn)
    turn.remaining_seconds = max(0, current + reversal_delta)

    score = _get_or_create_score(turn)
    if reversal_delta < 0:
        score.time_bonus_seconds += abs(reversal_delta)
    else:
        score.penalty_seconds += reversal_delta

    _record_event(
        turn.match.game_id,
        "PENALTY_REVERTED",
        {
            "turn_id": turn.id,
            "original_penalty_id": penalty.id,
            "reversal_id": reversal.id,
            "seconds": penalty.seconds,
            "type": penalty.type,
        },
        team_id=turn.team_id,
    )
    return reversal


def increment_score(turn, points, correct=0, passed=0, failed=0):
    """Manually adjust a team's score for a turn.

    Validates the totals do not exceed turn limits.
    """
    if turn.status not in (Turn.STATUS_ACTIVE, Turn.STATUS_PAUSED,
                           Turn.STATUS_COMPLETED, Turn.STATUS_TIMEOUT):
        raise TurnNotActiveError("Turn is not in a scoreable state.")

    score = _get_or_create_score(turn)
    score.points += points
    score.correct_words += correct
    score.passed_words += passed
    score.failed_words += failed

    _record_event(
        turn.match.game_id,
        "SCORE_UPDATED",
        {
            "turn_id": turn.id,
            "score_id": score.id,
            "team_id": turn.team_id,
            "points_added": points,
            "correct_added": correct,
            "passed_added": passed,
            "failed_added": failed,
        },
        team_id=turn.team_id,
    )
    return score


# ---------------------------------------------------------------------------
# Tie detection & tie-breaker
# ---------------------------------------------------------------------------


def _tie_breaker_round(
    game, timer_seconds=None, timer_mode=Round.TIMER_MODE_COUNTDOWN
):
    round_obj = Round.query.filter_by(
        game_id=game.id, round_number=TIE_BREAKER_ROUND_NUMBER
    ).first()
    if round_obj is None:
        round_obj = Round(
            game_id=game.id,
            round_number=TIE_BREAKER_ROUND_NUMBER,
            timer_seconds=timer_seconds or TIE_BREAKER_TIME_SECONDS,
            timer_mode=timer_mode or Round.TIMER_MODE_COUNTDOWN,
        )
        db.session.add(round_obj)
        db.session.flush()
    return round_obj


def _existing_tie_breaker_match(round_obj, team_a_id, team_b_id):
    expected = {team_a_id, team_b_id}
    for match in round_obj.matches:
        if match.opponent_team_id is None:
            continue
        if {match.team_id, match.opponent_team_id} == expected:
            return match
    return None


def maybe_resolve_pairing(match):
    if match.status != Match.STATUS_COMPLETED:
        return None
    round_obj = match.round
    team_a_id = match.team_id
    team_b_id = match.opponent_team_id
    if team_b_id is None:
        return None
    peer = Match.query.filter_by(
        round_id=round_obj.id,
        team_id=team_b_id,
        opponent_team_id=team_a_id,
    ).first()
    if peer is None or peer.status != Match.STATUS_COMPLETED:
        return None

    a_won = match.winner_team_id == team_a_id
    b_won = peer.winner_team_id == team_b_id
    if a_won != b_won:
        return {
            "tie": False,
            "winner_team_id": team_a_id if a_won else team_b_id,
            "team_a_won": a_won,
            "team_b_won": b_won,
        }

    game = round_obj.game
    tie_round = _tie_breaker_round(
        game, round_obj.timer_seconds, round_obj.timer_mode
    )
    existing = _existing_tie_breaker_match(tie_round, team_a_id, team_b_id)
    if existing is not None:
        return {
            "tie": True,
            "tie_breaker_match_id": existing.id,
            "created": False,
        }
    first_id = min(team_a_id, team_b_id)
    second_id = max(team_a_id, team_b_id)
    order = max((m.match_order for m in tie_round.matches), default=0) + 1
    tie_match = Match(
        game_id=game.id,
        round_id=tie_round.id,
        match_order=order,
        team_id=first_id,
        opponent_team_id=second_id,
    )
    db.session.add(tie_match)
    db.session.flush()
    return {
        "tie": True,
        "tie_breaker_match_id": tie_match.id,
        "created": True,
    }


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------


def game_scores(game):
    rows = (
        Score.query.filter_by(game_id=game.id)
        .order_by(Score.team_id, Score.round_id, Score.match_id)
        .all()
    )
    scores = []
    for score in rows:
        team = db.session.get(Team, score.team_id)
        scores.append(
            {
                "game_id": score.game_id,
                "team_id": score.team_id,
                "team_code": team.team_code if team else None,
                "team_name": team.team_name if team else None,
                "round_id": score.round_id,
                "match_id": score.match_id,
                "points": score.points,
                "correct_words": score.correct_words,
                "passed_words": score.passed_words,
                "failed_words": score.failed_words,
                "penalty_seconds": score.penalty_seconds,
                "time_bonus_seconds": score.time_bonus_seconds,
            }
        )
    return scores


def team_round_score(game, team_id, round_id):
    score = Score.query.filter_by(
        game_id=game.id, team_id=team_id, round_id=round_id
    ).first()
    return score


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


def turn_play_payload(turn, outcome=None):
    words = [
        {
            "word_id": turn_word.word_id,
            "word_text": turn_word.word.word_text if turn_word.word else None,
            "sequence": turn_word.sequence,
            "result": turn_word.result,
        }
        for turn_word in ordered_words(turn)
    ]
    current = next(
        (w for w in words if w["word_id"] == turn.current_word_id), None
    )
    match = turn.match
    payload = {
        "turn_id": turn.id,
        "match_id": turn.match_id,
        "team_id": turn.team_id,
        "round_id": turn.round_id,
        "round_number": match.round.round_number if match.round else None,
        "turn_order": turn.turn_order,
        "status": turn.status,
        "started_at": turn.started_at,
        "ended_at": turn.ended_at,
        "starting_seconds": turn.starting_seconds,
        "remaining_seconds": _remaining_seconds(turn),
        "elapsed_seconds": _elapsed_display_seconds(turn),
        "timer_mode": timer_mode_of(turn),
        "adjustment_seconds": _net_adjustment(turn),
        "paused_at": turn.paused_at,
        "correct_words": count_results(turn, TurnWord.RESULT_CORRECT),
        "passed_words": count_results(turn, TurnWord.RESULT_PASSED),
        "failed_words": count_results(turn, TurnWord.RESULT_FAILED),
        "total_words": len(words),
        "current_word_id": turn.current_word_id,
        "current_word_text": current["word_text"] if current else None,
        "words": words,
        "match_status": match.status,
        "match_winner_team_id": match.winner_team_id,
    }
    if outcome is not None:
        payload["outcome"] = outcome
    return payload


def public_turn_payload(turn):
    """Payload for non-manghuhula viewers; word text is secret until shown."""
    secret = turn_play_payload(turn)
    secret["words"] = [
        {
            "word_id": item["word_id"],
            "sequence": item["sequence"],
            "result": item["result"],
        }
        for item in secret["words"]
    ]
    secret["current_word_text"] = None
    return secret


def team_score_payload(team, rounds):
    data = []
    for round_obj in rounds:
        score = Score.query.filter_by(
            game_id=round_obj.game_id,
            team_id=team.id,
            round_id=round_obj.id,
        ).first()
        if score is None:
            continue
        data.append(
            {
                "round_number": round_obj.round_number,
                "points": score.points,
                "correct_words": score.correct_words,
                "passed_words": score.passed_words,
                "failed_words": score.failed_words,
            }
        )
    return data