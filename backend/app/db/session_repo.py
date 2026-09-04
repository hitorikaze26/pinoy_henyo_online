"""Device session repository — raw SQL for ``device_sessions``."""

from ..utils.db import query_one, query_all, execute, insert


def find_by_session_token(token):
    return query_one(
        "SELECT * FROM device_sessions WHERE session_token = :token",
        {"token": token},
    )


def find_by_id(session_id):
    return query_one(
        "SELECT * FROM device_sessions WHERE id = :id",
        {"id": session_id},
    )


def find_active_by_member(member_id):
    return query_all(
        "SELECT * FROM device_sessions "
        "WHERE member_id = :member_id AND disconnected_at IS NULL",
        {"member_id": member_id},
    )


def find_active_by_game(game_id):
    return query_all(
        "SELECT * FROM device_sessions "
        "WHERE game_id = :game_id AND disconnected_at IS NULL",
        {"game_id": game_id},
    )


def create_session(game_id, team_id, member_id, device_id, session_token,
                   device_type):
    return insert(
        "INSERT INTO device_sessions "
        "(game_id, team_id, member_id, device_id, session_token, device_type, "
        "connected_at, last_heartbeat) "
        "VALUES (:game_id, :team_id, :member_id, :device_id, :session_token, "
        ":device_type, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        {
            "game_id": game_id,
            "team_id": team_id,
            "member_id": member_id,
            "device_id": device_id,
            "session_token": session_token,
            "device_type": device_type,
        },
    )


def reactivate(session_id):
    """Set ``disconnected_at = NULL`` (reconnect)."""
    return execute(
        "UPDATE device_sessions SET disconnected_at = NULL, "
        "last_heartbeat = CURRENT_TIMESTAMP WHERE id = :id",
        {"id": session_id},
    )


def heartbeat(session_id):
    return execute(
        "UPDATE device_sessions SET last_heartbeat = CURRENT_TIMESTAMP "
        "WHERE id = :id",
        {"id": session_id},
    )


def disconnect(session_id):
    return execute(
        "UPDATE device_sessions SET disconnected_at = CURRENT_TIMESTAMP "
        "WHERE id = :id AND disconnected_at IS NULL",
        {"id": session_id},
    )


def expire_stale(timeout_seconds):
    """Mark sessions missing their heartbeat as disconnected."""
    return execute(
        "UPDATE device_sessions SET disconnected_at = CURRENT_TIMESTAMP "
        "WHERE disconnected_at IS NULL "
        "AND last_heartbeat < DATE_SUB(NOW(), INTERVAL :timeout SECOND)",
        {"timeout": timeout_seconds},
    )


def has_active_session(member_id):
    row = query_one(
        "SELECT COUNT(*) AS cnt FROM device_sessions "
        "WHERE member_id = :member_id AND disconnected_at IS NULL",
        {"member_id": member_id},
    )
    return (row["cnt"] or 0) > 0
