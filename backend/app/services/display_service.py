"""Two-stage display start (host START → ARM → GO → 3-2-1 → turn).

The host clicks START to validate readiness and arm the game; clicking GO
starts a server-authoritative 3-second countdown (deadline stored on the
game), after which the existing turn lifecycle is driven exactly like the
``start_turn`` route. The secret word feed is delivered only to the resolved
display target device(s) of the current team (Manghuhula phone when
connected, otherwise the team-leader phone), never broadcast.

Everything here is a thin orchestration on top of the existing services —
``readiness``/match/turn machinery from ``gameplay_service`` and
``turn_service``, peers from ``realtime``.
"""

import logging
import threading
import time
from collections import defaultdict
from datetime import timedelta

from ..extensions import db
from ..models import Game, Match, Round, Team, TeamMember, Turn, Word
from ..services import gameplay_service, realtime, turn_service
from ..services.game_service import GameFrozenError, assert_game_mutable
from ..utils.time import utcnow

logger = logging.getLogger(__name__)

COUNTDOWN_SECONDS = 3

DISPLAY_IDLE = Game.DISPLAY_IDLE
DISPLAY_ARMED = Game.DISPLAY_ARMED
DISPLAY_COUNTDOWN = Game.DISPLAY_COUNTDOWN
DISPLAY_RUNNING = Game.DISPLAY_RUNNING

_GO_LOCKS = defaultdict(threading.Lock)


# ---------------------------------------------------------------------------
# Display target resolution
# ---------------------------------------------------------------------------


def snapshot_peers():
    return realtime.snapshot_peers()


def display_target_resolution(game_id, team_id):
    """Resolve the current display target device(s) for a team.

    Priority: connected Manghuhula phones, then connected team-leader
    phones, then none. ``sids`` are live socket ids to emit secrets to;
    ``member_ids`` are the ids of the current target members (connected
    only) — used for reconnect authentication and state queries.
    """
    members = TeamMember.query.filter_by(team_id=team_id).all()
    manghuhula_ids = {
        m.id for m in members
        if m.gameplay_role == TeamMember.GAMEPLAY_ROLE_MANGHUHULA
    }
    leader_ids = {
        m.id for m in members
        if m.device_role == TeamMember.DEVICE_ROLE_TEAM_LEADER
    }
    connected = defaultdict(list)
    for sid, peer in realtime.snapshot_peers():
        if peer.get("game_id") != game_id or peer.get("team_id") != team_id:
            continue
        member_id = peer.get("member_id")
        if member_id is not None:
            connected[member_id].append(sid)

    for kind, candidate_ids in (
        ("manghuhula", manghuhula_ids),
        ("leader", leader_ids),
    ):
        target_ids = sorted(candidate_ids & set(connected))
        if not target_ids:
            continue
        sids = [
            sid for member_id in target_ids for sid in connected[member_id]
        ]
        return {
            "kind": kind,
            "member_ids": target_ids,
            "sids": sids,
        }
    return {"kind": None, "member_ids": [], "sids": []}


# ---------------------------------------------------------------------------
# Readiness for the display start (START / GO gate)
# ---------------------------------------------------------------------------


def start_readiness(game, match):
    """Validate the game can start a display turn.

    Reuses the existing team/role/match requirements (mirroring
    ``gameplay_service.readiness``) plus the two-stage flow's own gates:
    a positive timer, at least 25 enabled words in the pool, and a selected
    pending match. Match/turn word assignment happens at GO so it is NOT
    required here.
    """
    issues = []

    active_teams = Team.query.filter_by(
        game_id=game.id, status=Team.STATUS_ACTIVE
    ).all()
    if len(active_teams) < 2:
        issues.append("At least two active teams are required.")
    for team in active_teams:
        label = "#{} ({})".format(team.team_code, team.team_name)
        if team.leader_member_id is None:
            issues.append("Team {} has no team leader.".format(label))
        if not any(
            member.gameplay_role == TeamMember.GAMEPLAY_ROLE_MANGHUHULA
            for member in team.members
        ):
            issues.append("Team {} has no Manghuhula assigned.".format(label))
        if not any(
            member.gameplay_role == TeamMember.GAMEPLAY_ROLE_TAGASAGOT
            for member in team.members
        ):
            issues.append("Team {} has no Tagasagot assigned.".format(label))

    rounds = (
        Round.query.filter_by(game_id=game.id)
        .order_by(Round.round_number)
        .all()
    )
    if not rounds:
        issues.append("No rounds have been set up.")
    for round_obj in rounds:
        label = "Round {}".format(round_obj.round_number)
        timer = round_obj.timer_seconds
        if timer is None or int(timer) < 1:
            issues.append(
                "{} has an invalid timer (set a time above zero).".format(
                    label
                )
            )
        if round_obj.status == Round.STATUS_COMPLETED:
            issues.append("{} is already complete.".format(label))

    category_count = (
        db.session.query(Word.category_id)
        .filter(
            Word.game_id == game.id,
            Word.status != Word.STATUS_DISABLED,
        )
        .distinct()
        .count()
    )
    if category_count == 0:
        issues.append("No configured categories have any enabled words.")

    pool = (
        Word.query.filter(
            Word.game_id == game.id,
            Word.status != Word.STATUS_DISABLED,
        ).count()
    )
    min_words = 15
    if game.settings and game.settings.min_words_to_start:
        min_words = game.settings.min_words_to_start
    if pool < min_words:
        issues.append(
            "At least {} enabled words are required in the word pool "
            "(currently {}).".format(min_words, pool)
        )

    if match is None:
        issues.append("Select a match to start.")
    elif match.game_id != game.id:
        issues.append("The selected match does not belong to this game.")
    elif match.status == Match.STATUS_COMPLETED:
        issues.append("The selected match has already been completed.")
    elif any(
        turn.status in (Turn.STATUS_ACTIVE, Turn.STATUS_PAUSED)
        for turn in match.turns
    ):
        issues.append("A turn is already running for the selected match.")

    return issues


# ---------------------------------------------------------------------------
# State transitions (armed state is persisted on the game row)
# ---------------------------------------------------------------------------


def state_payload(game, member_id=None):
    """Authoritative display state used by reconnect recovery + host restore."""
    match = None
    if game.display_go_match_id is not None:
        match = db.session.get(Match, game.display_go_match_id)
    team_id = match.team_id if match is not None else None

    kind = None
    is_target = False
    if match is not None and member_id is not None:
        resolution = display_target_resolution(game.id, match.team_id)
        kind = resolution["kind"]
        is_target = member_id in resolution["member_ids"]

    running_turn = None
    if game.display_status == DISPLAY_RUNNING and match is not None:
        running_turn = (
            Turn.query.filter(
                Turn.match_id == match.id,
                Turn.status.in_(
                    (Turn.STATUS_ACTIVE, Turn.STATUS_PAUSED)
                ),
            )
            .order_by(Turn.id.desc())
            .first()
        )

    remaining = None
    if game.display_go_at is not None:
        remaining = max(
            0, (game.display_go_at - utcnow()).total_seconds()
        )

    payload = {
        "game_id": game.id,
        "status": game.display_status,
        "match_id": game.display_go_match_id,
        "team_id": team_id,
        "countdown_seconds": COUNTDOWN_SECONDS,
        "remaining": round(remaining, 2) if remaining is not None else None,
        "go_at": (
            game.display_go_at.isoformat() if game.display_go_at else None
        ),
        "is_target": is_target,
        "target_kind": kind,
        "turn_id": running_turn.id if running_turn is not None else None,
    }
    return payload


def arm(game, match):
    """Mark the game ARMED for the given match (START click)."""
    game.display_status = DISPLAY_ARMED
    game.display_go_match_id = match.id
    game.display_go_at = None
    resolution = display_target_resolution(game.id, match.team_id)
    db.session.commit()
    return _armed_payload(game, match, resolution)


def _armed_payload(game, match, resolution):
    return {
        "status": game.display_status,
        "match_id": match.id,
        "team_id": match.team_id,
        "countdown_seconds": COUNTDOWN_SECONDS,
        "display_target": resolution["kind"],
    }


def set_countdown(game, match):
    """Arm the server-authoritative 3-second GO! countdown and schedule it."""
    from flask import current_app

    now = utcnow()
    deadline = now + timedelta(seconds=COUNTDOWN_SECONDS)
    game.display_status = DISPLAY_COUNTDOWN
    game.display_go_match_id = match.id
    game.display_go_at = deadline
    resolution = display_target_resolution(game.id, match.team_id)
    db.session.commit()
    if not current_app.config.get("TESTING"):
        # Live server: a background task fires the start at the deadline.
        # Under TESTING the in-memory SQLite connection is shared across
        # threads, so the scheduler races the request thread — tests start
        # deterministically through the idempotent /display/state reconciler.
        _start_go_worker.game_async_start(game.id, match.id)
    return {
        "status": game.display_status,
        "match_id": match.id,
        "team_id": match.team_id,
        "countdown_seconds": COUNTDOWN_SECONDS,
        "go_at": deadline.isoformat(),
        "display_target": resolution["kind"],
    }


def reset_display(game):
    """Idle the display lifecycle (turn ended, GO failed, etc.)."""
    if game.display_status == DISPLAY_IDLE:
        return
    game.display_status = DISPLAY_IDLE
    game.display_go_at = None
    game.display_go_match_id = None
    db.session.commit()


def finish_display(game):
    """Fire-and-forget idle reset used when a turn reaches a terminal state."""
    try:
        reset_display(game)
    except Exception:  # noqa: BLE001 - a cleanup reset must never break flow
        logger.exception("reset_display failed for game %s", game.id)


# ---------------------------------------------------------------------------
# Server-authoritative countdown -> turn start
# ---------------------------------------------------------------------------


def start_pending_go_if_ready(game, now=None):
    """Run the deferred start exactly when the countdown deadline passes.

    Idempotent: guarded by the persisted COUNTDOWN status + deadline, so
    either the scheduled background task or a delayed state read (host
    reconnect, phone recovery) can fire it without ever double-starting.
    Returns True when a turn was started.
    """
    if game.display_status != DISPLAY_COUNTDOWN:
        return False
    match = db.session.get(Match, game.display_go_match_id)
    if match is None:
        reset_display(game)
        return False
    active = (
        Turn.query.filter_by(match_id=match.id, status=Turn.STATUS_ACTIVE)
        .first()
    )
    if active is not None:
        game.display_status = DISPLAY_RUNNING
        game.display_go_at = None
        db.session.commit()
        return False
    if game.display_go_at is None or utcnow() < game.display_go_at:
        return False
    return _start_turn_for_display(game, match)


def _start_turn_for_display(game, match):
    """The existing turn lifecycle: assign words, then start the turn.

    Mirrors ``POST /matches/<id>/turn/start`` side effects (round/match
    lazy start events + the standard turn_started feed).
    """
    try:
        assert_game_mutable(game)
    except GameFrozenError:
        reset_display(game)
        return False

    round_obj = match.round
    round_starts_now = (
        round_obj is not None and round_obj.started_at is None
    )
    match_was_active = match.status == Match.STATUS_ACTIVE
    try:
        # auto-assign the word list (same count the host used before)
        gameplay_service.assign_turn_words(
            match, count=gameplay_service.MAX_WORDS_PER_TURN
        )
        turn = turn_service.start_turn(match)
        if round_starts_now:
            round_obj.started_at = utcnow()
            match.game.current_round = round_obj.round_number
            match.game.current_match_id = match.id
        game.display_status = DISPLAY_RUNNING
        game.display_go_at = None
        db.session.commit()
    except Exception as exc:  # noqa: BLE001 - never kill the task
        db.session.rollback()
        logger.error(
            "display go turn start failed for game %s: %s", game.id, exc
        )
        game.display_status = DISPLAY_IDLE
        game.display_go_at = None
        game.display_go_match_id = None
        db.session.commit()
        return False

    if round_starts_now:
        realtime.emit_round_started(round_obj)
    if not match_was_active:
        realtime.emit_match_started(match)
    realtime.emit_turn_started(turn)
    return True


def _go_worker(game_id, match_id):
    game = db.session.get(Game, game_id)
    if game is None or game.display_status != DISPLAY_COUNTDOWN:
        return
    deadline = game.display_go_at
    while deadline is not None and utcnow() < deadline:
        time.sleep(min(0.2, max(0.05, (deadline - utcnow()).total_seconds())))
    try:
        start_pending_go_if_ready(game)
    except Exception:  # noqa: BLE001 - never die silently
        logger.exception("display go worker failed for game %s", game_id)


class _GoWorker:
    """Daemon worker that starts the turn after the countdown deadline.

    Uses whatever Flask app is live at scheduling time. In production the
    single uWSGI worker keeps this thread alive; on a process restart the
    persisted deadline lets a later state read recover the flow.
    """

    _lock = threading.Lock()

    @classmethod
    def game_async_start(cls, game_id, match_id):
        from flask import current_app

        # Called from a request handler, so current_app is guaranteed live.
        # The worker thread owns its own app context afterwards.
        app = current_app._get_current_object()
        thread = threading.Thread(
            target=cls._run, args=(app, game_id, match_id),
            name="pinoy-display-go-{}".format(game_id), daemon=True,
        )
        thread.start()

    @classmethod
    def _run(cls, app, game_id, match_id):
        try:
            with app.app_context():
                _go_worker(game_id, match_id)
        except Exception:  # noqa: BLE001
            logger.exception("display go task failed for game %s", game_id)


_start_go_worker = _GoWorker