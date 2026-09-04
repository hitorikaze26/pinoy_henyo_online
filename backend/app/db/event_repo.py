"""Game event repository — raw SQL for ``game_events``."""

from ..utils.db import query_one, query_all, insert


def find_by_id(event_id):
    return query_one(
        "SELECT * FROM game_events WHERE id = :id",
        {"id": event_id},
    )


def find_all_by_game(game_id):
    return query_all(
        "SELECT * FROM game_events WHERE game_id = :game_id ORDER BY id",
        {"game_id": game_id},
    )


def record_event(game_id, event_type, event_data=None, team_id=None,
                 member_id=None):
    """Insert an audit-log event."""
    import json as _json

    data_json = _json.dumps(event_data) if event_data is not None else None
    return insert(
        "INSERT INTO game_events (game_id, team_id, member_id, event_type, "
        "event_data) "
        "VALUES (:game_id, :team_id, :member_id, :event_type, :event_data)",
        {
            "game_id": game_id,
            "team_id": team_id,
            "member_id": member_id,
            "event_type": event_type,
            "event_data": data_json,
        },
    )
