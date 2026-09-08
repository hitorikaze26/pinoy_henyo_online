"""Background maintenance for the Pinoy Henyo Online backend.

Handles host-disconnect reconciliation (Req: host disconnect should not
instantly delete a game; it stays active until the host fails to reconnect
within the configured timeout, after which the game is marked EXPIRED) plus
expiry of stale device sessions whose heartbeat lapsed.
"""

import logging
import threading
import time
from datetime import timedelta

from ..extensions import db
from ..models import Game
from ..services import game_service, realtime, team_service
from ..utils.time import utcnow

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = (
    Game.STATUS_GAME_COMPLETE,
    Game.STATUS_CANCELLED,
    Game.STATUS_EXPIRED,
)


def expire_stale_device_sessions(timeout_seconds):
    """Mark device sessions that missed their heartbeat as disconnected.

    Disconnects that were detected by the sweep (rather than a socket close)
    are fanned out over realtime so connected hosts learn about them live.
    """
    if timeout_seconds <= 0:
        return 0
    swept = team_service.expire_stale_sessions(timeout_seconds)
    if swept:
        db.session.commit()
        for game_id, team_id, member_id in swept:
            try:
                realtime.emit_team_disconnected(game_id, team_id, member_id)
            except Exception as exc:  # noqa: BLE001 - never kill the sweep
                logger.exception("emit_team_disconnected failed: %s", exc)
    return len(swept)


def reconcile_orphaned_games(host_timeout_seconds, now=None):
    """Mark games EXPIRED when the host has been absent beyond the timeout.

    A host is "absent" when:
      * host_last_seen_at is set and older than the cutoff, or
      * host_last_seen_at is never set (host never connected via socket/REST)
        and the game is older than the cutoff.

    The game is not hard-deleted — it is marked with the terminal EXPIRED
    status so history remains while new teams/members/gameplay are blocked.
    Returns the number of games that were newly expired.

    When host_timeout_seconds <= 0 the sweep is disabled (no games expire).
    """
    if host_timeout_seconds <= 0:
        return 0
    now = now or utcnow()
    cutoff = now - timedelta(seconds=max(host_timeout_seconds, 1))
    count = 0
    candidates = Game.query.filter(Game.status.notin_(TERMINAL_STATUSES)).all()
    for game in candidates:
        ref = game.host_last_seen_at or game.created_at
        if ref is None or ref >= cutoff:
            continue
        if game_service.mark_game_expired(game):
            count += 1
            logger.info("Game %s expired (host absent)", game.game_code)
    if count:
        db.session.commit()
    return count


def _sweep(app):
    host_timeout = app.config.get("HOST_INACTIVITY_TIMEOUT", 900)
    heartbeat_timeout = app.config.get("DEVICE_HEARTBEAT_TIMEOUT", 60)
    grace_multiplier = app.config.get("DEVICE_HEARTBEAT_GRACE_MULTIPLIER", 3)
    effective_heartbeat = heartbeat_timeout * max(int(grace_multiplier), 1)
    with app.app_context():
        try:
            reconcile_orphaned_games(host_timeout)
        except Exception as exc:  # noqa: BLE001 - never kill the loop
            logger.exception("reconcile_orphaned_games failed: %s", exc)
        try:
            expire_stale_device_sessions(effective_heartbeat)
        except Exception as exc:  # noqa: BLE001
            logger.exception("expire_stale_device_sessions failed: %s", exc)


_stop_event = None
_thread = None
_lock = threading.Lock()


def start_sweeper(app):
    """Start the background sweeper thread (idempotent, dev/prod only)."""
    global _stop_event, _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        interval = float(app.config.get("SWEEPER_INTERVAL", 30))
        _stop_event = threading.Event()
        target = app

        def _loop():
            while not _stop_event.is_set():
                _sweep(target)
                _stop_event.wait(interval)

        _thread = threading.Thread(
            target=_loop, name="pinoy-maintenance-sweeper", daemon=True
        )
        _thread.start()


def stop_sweeper():
    """Signal the sweeper thread to exit (used in tests/shutdown)."""
    global _stop_event
    if _stop_event is not None:
        _stop_event.set()
