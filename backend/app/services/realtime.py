import threading
from datetime import datetime

from ..extensions import socketio
from ..models import Match, Round, TeamMember, Turn, TurnWord
from ..services.turn_service import (
    count_results,
    public_turn_payload,
    turn_play_payload,
)
from ..utils.time import utcnow


SOCKET_PEERS = {}
_PEERS_LOCK = threading.Lock()


def game_room(game_id):
    return "game:{}".format(game_id)


def team_room(team_id):
    return "team:{}".format(team_id)


def turn_room(turn_id):
    return "turn:{}".format(turn_id)


def manghuhula_room(team_id):
    return "manghuhula:{}".format(team_id)


def member_room(member_id):
    return "member:{}".format(member_id)


def register_peer(sid, **data):
    with _PEERS_LOCK:
        SOCKET_PEERS[sid] = data


def pick_peer(sid):
    with _PEERS_LOCK:
        return SOCKET_PEERS.get(sid)


def drop_peer(sid):
    with _PEERS_LOCK:
        return SOCKET_PEERS.pop(sid, None)


def snapshot_peers():
    """Read-only snapshot of all registered peers (sid, data) pairs."""
    with _PEERS_LOCK:
        return list(SOCKET_PEERS.items())


def reset_peers():
    with _PEERS_LOCK:
        SOCKET_PEERS.clear()


def _serializable(value):
    if isinstance(value, dict):
        return {key: _serializable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(val) for val in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _emit(room, event, data, skip_sid=None):
    payload = _serializable(data)
    if skip_sid is not None:
        socketio.emit(event, payload, room=room, skip_sid=skip_sid)
    else:
        socketio.emit(event, payload, room=room)


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def public_member(member):
    return {
        "member_id": member.id,
        "team_id": member.team_id,
        "username": member.username,
        "device_role": member.device_role,
        "gameplay_role": member.gameplay_role,
        "is_connected": member.is_connected,
    }


def public_turn_payload(turn):
    """Turn snapshot WITHOUT any secret word text."""
    payload = turn_play_payload(turn)
    payload.pop("words", None)
    payload.pop("current_word_text", None)
    payload["secret_word_count"] = count_results(turn, TurnWord.RESULT_PENDING)
    return payload


def secret_turn_payload(turn):
    """Full turn snapshot including secret word text (Manghuhula only)."""
    return turn_play_payload(turn)


# ---------------------------------------------------------------------------
# Game / round / match events
# ---------------------------------------------------------------------------


def emit_game_started(game):
    _emit(game_room(game.id), "game_started", {"game_id": game.id, "status": game.status})


def emit_game_paused(game):
    _emit(game_room(game.id), "game_paused", {"game_id": game.id, "status": game.status})


def emit_game_resumed(game):
    _emit(game_room(game.id), "game_resumed", {"game_id": game.id, "status": game.status})


def emit_game_completed(game):
    _emit(
        game_room(game.id),
        "game_completed",
        {"game_id": game.id, "status": game.status},
    )


def emit_leaderboard(game):
    """Broadcast the aggregated standings to everyone in the game room.

    Sent after any score-affecting event (word result, penalty/time
    adjustment, turn or round completion) so player devices can keep a live,
    public leaderboard in sync.
    """
    from ..services.report_service import leaderboard

    _emit(
        game_room(game.id),
        "leaderboard_updated",
        {"game_id": game.id, "leaderboard": leaderboard(game)},
    )


def emit_round_started(round_obj):
    _emit(
        game_room(round_obj.game_id),
        "round_started",
        {
            "game_id": round_obj.game_id,
            "round_id": round_obj.id,
            "round_number": round_obj.round_number,
            "status": round_obj.status,
            "timer_seconds": round_obj.timer_seconds,
            "timer_mode": round_obj.timer_mode,
            "started_at": round_obj.started_at,
        },
    )


def emit_round_updated(round_obj):
    _emit(
        game_room(round_obj.game_id),
        "round_updated",
        {
            "game_id": round_obj.game_id,
            "round_id": round_obj.id,
            "round_number": round_obj.round_number,
            "status": round_obj.status,
            "timer_seconds": round_obj.timer_seconds,
            "timer_mode": round_obj.timer_mode,
            "started_at": round_obj.started_at,
            "ended_at": round_obj.ended_at,
        },
    )


def emit_match_started(match):
    data = {
        "game_id": match.game_id,
        "match_id": match.id,
        "round_id": match.round_id,
        "round_number": match.round.round_number if match.round else None,
        "match_order": match.match_order,
        "team_id": match.team_id,
        "opponent_team_id": match.opponent_team_id,
        "status": match.status,
    }
    _emit(game_room(match.game_id), "match_started", data)
    if match.opponent_team_id is not None:
        _emit(team_room(match.opponent_team_id), "match_started", data)
    _emit(team_room(match.team_id), "match_started", data)


# ---------------------------------------------------------------------------
# Turn events
# ---------------------------------------------------------------------------


def _emit_secret_to_targets(event, turn):
    """Deliver the secret turn payload to the resolved display target only.

    The secret lives only on the current display device (Manghuhula phone
    when connected, otherwise the team-leader phone). Resolved dynamically
    so a mid-turn disconnect/reconnect re-targets correctly.
    """
    from ..services.display_service import display_target_resolution

    payload = _serializable(secret_turn_payload(turn))
    try:
        resolution = display_target_resolution(
            turn.match.game_id, turn.team_id
        )
    except Exception:  # noqa: BLE001 - never break the turn feed
        resolution = {"sids": []}
    sids = resolution.get("sids") or []
    if sids:
        socketio.emit(event, payload, room=sids)


def emit_turn_started(turn):
    public = public_turn_payload(turn)
    _emit(game_room(turn.match.game_id), "turn_started", public)
    _emit(turn_room(turn.id), "turn_started", public)
    _emit_secret_to_targets("turn_started", turn)
    _emit(game_room(turn.match.game_id), "timer_updated", timer_payload(turn))
    _emit(turn_room(turn.id), "timer_updated", timer_payload(turn))


def emit_turn_state_to(sid, turn):
    socketio.emit(
        "turn_state", _serializable(public_turn_payload(turn)), room=sid
    )


def emit_word_result(turn, turn_word, event):
    data = {
        "game_id": turn.match.game_id,
        "match_id": turn.match_id,
        "turn_id": turn.id,
        "word_id": turn_word.word_id,
        "sequence": turn_word.sequence,
        "result": turn_word.result,
        "correct_words": count_results(turn, TurnWord.RESULT_CORRECT),
        "passed_words": count_results(turn, TurnWord.RESULT_PASSED),
        "failed_words": count_results(turn, TurnWord.RESULT_FAILED),
        "current_word_id": turn.current_word_id,
    }
    _emit(game_room(turn.match.game_id), event, data)
    _emit(turn_room(turn.id), event, data)
    _emit(game_room(turn.match.game_id), "timer_updated", timer_payload(turn))
    _emit(turn_room(turn.id), "timer_updated", timer_payload(turn))


def timer_payload(turn):
    from ..services.turn_service import (
        _elapsed_display_seconds,
        _net_adjustment,
        _remaining_seconds,
        timer_mode_of,
    )

    return {
        "turn_id": turn.id,
        "status": turn.status,
        "timer_mode": timer_mode_of(turn),
        "remaining_seconds": _remaining_seconds(turn),
        "elapsed_seconds": _elapsed_display_seconds(turn),
        "adjustment_seconds": _net_adjustment(turn),
        "paused_at": turn.paused_at,
        "starting_seconds": turn.starting_seconds,
    }


def emit_timer_paused(turn):
    data = timer_payload(turn)
    data["paused_at"] = turn.paused_at
    _emit(game_room(turn.match.game_id), "timer_paused", data)
    _emit(turn_room(turn.id), "timer_paused", data)


def emit_timer_resumed(turn):
    data = timer_payload(turn)
    data["paused_at"] = None
    _emit(game_room(turn.match.game_id), "timer_resumed", data)
    _emit(turn_room(turn.id), "timer_resumed", data)


def emit_time_adjusted(turn, penalty, delta):
    event = "time_added" if delta > 0 else "time_removed"
    data = {
        "turn_id": turn.id,
        "team_id": turn.team_id,
        "seconds": int(delta),
        "adjustment_seconds": turn.timer_adjustment_seconds or 0,
        "remaining_seconds": timer_payload(turn)["remaining_seconds"],
        "penalty_id": penalty.id if penalty is not None else None,
        "penalty_type": penalty.type if penalty is not None else None,
        "reason": penalty.reason if penalty is not None else None,
    }
    _emit(game_room(turn.match.game_id), event, data)
    _emit(turn_room(turn.id), event, data)
    _emit(game_room(turn.match.game_id), "penalty_applied", data)
    _emit(turn_room(turn.id), "penalty_applied", data)
    _emit(game_room(turn.match.game_id), "timer_updated", timer_payload(turn))
    _emit(turn_room(turn.id), "timer_updated", timer_payload(turn))


def emit_turn_completed(turn, outcome=None):
    public = public_turn_payload(turn)
    if outcome is not None:
        public["outcome"] = outcome
    _emit(game_room(turn.match.game_id), "turn_completed", public)
    _emit(turn_room(turn.id), "turn_completed", public)
    _emit_secret_to_targets("turn_completed", turn)


def emit_turn_reset(turn, result):
    """Tell every client a finished turn was re-opened on the board.

    ``turn_play_payload`` reflects the restored WAITING state; ``result`` is
    the persistent pre-reset snapshot so the host result modal can stay open.
    """
    public = public_turn_payload(turn)
    data = {
        "game_id": turn.match.game_id,
        "match_id": turn.match_id,
        "team_id": turn.team_id,
        "turn": public,
        "result": result,
    }
    _emit(game_room(turn.match.game_id), "turn_reset", data)
    _emit(turn_room(turn.id), "turn_reset", data)
    _emit_secret_to_targets("turn_reset", turn)


def emit_category_selected(game, match):
    data = {
        "game_id": game.id,
        "match_id": match.id,
        "team_id": match.team_id,
        "round_id": match.round_id,
        "round_number": match.round.round_number if match.round else None,
        "category_id": match.category_id,
    }
    _emit(game_room(game.id), "category_selected", data)
    _emit(team_room(match.team_id), "category_selected", data)


# ---------------------------------------------------------------------------
# Two-stage display start events (host START/GO + countdown)
# ---------------------------------------------------------------------------


def _display_target_sids(game_id, team_id):
    from ..services.display_service import display_target_resolution

    try:
        resolution = display_target_resolution(game_id, team_id)
    except Exception:  # noqa: BLE001
        resolution = {"sids": []}
    return resolution


def emit_display_armed(game, match):
    data = {
        "game_id": game.id,
        "match_id": match.id,
        "team_id": match.team_id,
        "status": game.display_status,
    }
    _emit(game_room(game.id), "display_armed", data)
    resolution = _display_target_sids(game.id, match.team_id)
    if resolution.get("sids"):
        socketio.emit(
            "display_armed", _serializable(data), room=resolution["sids"]
        )


def emit_display_go(game, match):
    from ..services.display_service import COUNTDOWN_SECONDS

    data = {
        "game_id": game.id,
        "match_id": match.id,
        "team_id": match.team_id,
        "status": game.display_status,
        "countdown_seconds": COUNTDOWN_SECONDS,
        "go_at": (
            game.display_go_at.isoformat() if game.display_go_at else None
        ),
    }
    _emit(game_room(game.id), "display_go", data)
    resolution = _display_target_sids(game.id, match.team_id)
    if resolution.get("sids"):
        socketio.emit(
            "display_go", _serializable(data), room=resolution["sids"]
        )


def emit_display_cancelled(game, match, reason=None):
    data = {
        "game_id": game.id,
        "match_id": match.id,
        "team_id": match.team_id,
        "status": "IDLE",
    }
    if reason:
        data["reason"] = str(reason)
    _emit(game_room(game.id), "display_cancelled", data)
    resolution = _display_target_sids(game.id, match.team_id)
    if resolution.get("sids"):
        socketio.emit(
            "display_cancelled", _serializable(data), room=resolution["sids"]
        )


def mark_round_completed_if_done(match):
    round_obj = match.round
    if round_obj is None or round_obj.ended_at is not None:
        return False
    if all(item.status == Match.STATUS_COMPLETED for item in round_obj.matches):
        round_obj.ended_at = utcnow()
        if round_obj.status == Round.STATUS_PENDING:
            round_obj.status = Round.STATUS_COMPLETED
        return True
    return False


def announce_round_completed(round_obj):
    _emit(
        game_room(round_obj.game_id),
        "round_completed",
        {
            "game_id": round_obj.game_id,
            "round_id": round_obj.id,
            "round_number": round_obj.round_number,
            "status": round_obj.status,
            "ended_at": round_obj.ended_at,
        },
    )


# ---------------------------------------------------------------------------
# Team events
# ---------------------------------------------------------------------------


def emit_team_connected(team, member, device_type, skip_sid=None):
    data = {
        "team_id": team.id,
        "game_id": team.game_id,
        "member": public_member(member),
        "device_type": device_type,
    }
    _emit(team_room(team.id), "team_connected", data, skip_sid=skip_sid)
    _emit(game_room(team.game_id), "team_connected", data, skip_sid=skip_sid)


def emit_team_disconnected(game_id, team_id, member_id):
    data = {"game_id": game_id, "team_id": team_id, "member_id": member_id}
    _emit(team_room(team_id), "team_disconnected", data)
    _emit(game_room(game_id), "team_disconnected", data)


def emit_member_joined(team, member):
    _emit(
        team_room(team.id),
        "member_joined",
        {"team_id": team.id, "member": public_member(member)},
    )
    _emit(
        game_room(team.game_id),
        "member_joined",
        {"team_id": team.id, "member": public_member(member)},
    )


def emit_member_left(game_id, team_id, member_id):
    data = {"game_id": game_id, "team_id": team_id, "member_id": member_id}
    _emit(team_room(team_id), "member_left", data)
    _emit(game_room(game_id), "member_left", data)


def emit_role_updated(team, member):
    _emit(
        team_room(team.id),
        "role_updated",
        {
            "team_id": team.id,
            "member_id": member.id,
            "gameplay_role": member.gameplay_role,
        },
    )
    _emit(
        game_room(team.game_id),
        "role_updated",
        {
            "team_id": team.id,
            "member_id": member.id,
            "gameplay_role": member.gameplay_role,
        },
    )


def emit_member_updated(team, member):
    _emit(
        team_room(team.id),
        "member_updated",
        {
            "team_id": team.id,
            "member_id": member.id,
            "username": member.username,
        },
    )
    _emit(
        game_room(team.game_id),
        "member_updated",
        {
            "team_id": team.id,
            "member_id": member.id,
            "username": member.username,
        },
    )


def emit_team_updated(team):
    _emit(
        team_room(team.id),
        "team_updated",
        {"team_id": team.id, "team_name": team.team_name},
    )
    _emit(
        game_room(team.game_id),
        "team_updated",
        {"team_id": team.id, "team_name": team.team_name},
    )


def emit_word_pool_updated(game, team=None):
    """Signal that a team's word pool changed; clients refetch via REST."""
    data = {"game_id": game.id, "team_id": team.id if team is not None else None}
    if team is not None:
        _emit(team_room(team.id), "word_pool_updated", data)
    _emit(game_room(game.id), "word_pool_updated", data)


def _word_change_request_payload(req):
    from ..services.word_change_request_service import request_payload

    return request_payload(req)


def emit_word_change_request(req):
    """A host asked a team to change one of its words (modal opens on team)."""
    data = _word_change_request_payload(req)
    _emit(team_room(req.team_id), "word_change_request", data)
    _emit(game_room(req.game_id), "word_change_request", data)


def emit_word_change_resolved(req):
    """The team corrected the word; the modal closes and the pool refreshes."""
    data = _word_change_request_payload(req)
    _emit(team_room(req.team_id), "word_change_resolved", data)
    _emit(game_room(req.game_id), "word_change_resolved", data)


def emit_word_change_cancelled(req):
    """The host cancelled a change request; the modal closes."""
    data = _word_change_request_payload(req)
    _emit(team_room(req.team_id), "word_change_cancelled", data)
    _emit(game_room(req.game_id), "word_change_cancelled", data)


def _connection_event_data(team):
    from ..services import team_service

    payload = team_service.team_payload(team)
    payload["game_id"] = team.game_id
    return payload


def emit_connection_requested(team, member=None):
    data = _connection_event_data(team)
    data["leader"] = (
        public_member(team.leader) if team.leader is not None else None
    )
    data["member_count"] = len(team.members)
    if member is not None:
        data["requester"] = public_member(member)
    _emit(team_room(team.id), "connection_requested", data)
    _emit(game_room(team.game_id), "connection_requested", data)


def emit_settings_updated(game):
    from ..services.game_settings_service import get_payload

    data = get_payload(game)
    _emit(game_room(game.id), "settings_updated", data)


def emit_connection_approved(team):
    data = _connection_event_data(team)
    _emit(team_room(team.id), "connection_approved", data)
    _emit(game_room(team.game_id), "connection_approved", data)


def emit_connection_declined(team):
    data = _connection_event_data(team)
    _emit(team_room(team.id), "connection_declined", data)
    _emit(game_room(team.game_id), "connection_declined", data)


def emit_connection_disconnected(team):
    data = _connection_event_data(team)
    _emit(team_room(team.id), "connection_disconnected", data)
    _emit(game_room(team.game_id), "connection_disconnected", data)


# ---------------------------------------------------------------------------
# Turn room membership rules
# ---------------------------------------------------------------------------


def can_join_turn(peer, turn):
    if peer is None:
        return False
    if peer.get("role") == "HOST":
        return peer.get("game_id") == turn.match.game_id
    if peer.get("team_id") is None:
        return False
    return peer.get("game_id") == turn.match.game_id and peer.get("team_id") == turn.team_id