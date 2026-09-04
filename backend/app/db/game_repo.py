"""Game repository — raw SQL data access for the ``games`` table."""

from ..utils.db import query_one, query_all, execute, insert


def find_by_id(game_id):
    return query_one(
        "SELECT * FROM games WHERE id = :id",
        {"id": game_id},
    )


def find_by_code(game_code):
    return query_one(
        "SELECT * FROM games WHERE game_code = :code",
        {"code": game_code},
    )


def find_by_host_token(host_token):
    return query_one(
        "SELECT * FROM games WHERE host_session_token = :token",
        {"token": host_token},
    )


def find_all_by_host_token(host_token):
    return query_all(
        "SELECT * FROM games WHERE host_session_token = :token "
        "ORDER BY created_at DESC",
        {"token": host_token},
    )


def create_game(game_code, host_token, status="LOBBY"):
    return insert(
        "INSERT INTO games (game_code, host_session_token, status) "
        "VALUES (:game_code, :host_token, :status)",
        {"game_code": game_code, "host_token": host_token, "status": status},
    )


def update_status(game_id, status):
    return execute(
        "UPDATE games SET status = :status, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = :id",
        {"id": game_id, "status": status},
    )


def update_fields(game_id, **fields):
    """Generic field updater.  Only touches the keys present in *fields*."""
    if not fields:
        return 0
    set_parts = []
    params = {"id": game_id}
    for key, value in fields.items():
        set_parts.append("{col} = :{col}".format(col=key))
        params[key] = value
    set_parts.append("updated_at = CURRENT_TIMESTAMP")
    sql = "UPDATE games SET {sets} WHERE id = :id".format(
        sets=", ".join(set_parts)
    )
    return execute(sql, params)


def delete_game(game_id):
    return execute(
        "DELETE FROM games WHERE id = :id",
        {"id": game_id},
    )


def count_games():
    row = query_one("SELECT COUNT(*) AS cnt FROM games")
    return row["cnt"] if row else 0
