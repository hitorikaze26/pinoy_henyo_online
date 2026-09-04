"""Round repository — raw SQL data access for the ``rounds`` table."""

from ..utils.db import query_one, query_all, execute, insert


def find_by_id(round_id):
    return query_one(
        "SELECT * FROM rounds WHERE id = :id",
        {"id": round_id},
    )


def find_by_game_and_number(game_id, round_number):
    return query_one(
        "SELECT * FROM rounds WHERE game_id = :game_id AND round_number = :num",
        {"game_id": game_id, "num": round_number},
    )


def find_all_by_game(game_id):
    return query_all(
        "SELECT * FROM rounds "
        "WHERE game_id = :game_id ORDER BY round_number, id",
        {"game_id": game_id},
    )


def create_round(game_id, round_number, timer_seconds=60, timer_mode="COUNTDOWN"):
    return insert(
        "INSERT INTO rounds (game_id, round_number, timer_seconds, timer_mode) "
        "VALUES (:game_id, :round_number, :timer_seconds, :timer_mode)",
        {
            "game_id": game_id,
            "round_number": round_number,
            "timer_seconds": timer_seconds,
            "timer_mode": timer_mode,
        },
    )


def update_status(round_id, status):
    return execute(
        "UPDATE rounds SET status = :status WHERE id = :id",
        {"id": round_id, "status": status},
    )


def set_started(round_id):
    return execute(
        "UPDATE rounds SET status = 'ACTIVE', started_at = CURRENT_TIMESTAMP "
        "WHERE id = :id",
        {"id": round_id},
    )


def set_completed(round_id):
    return execute(
        "UPDATE rounds SET status = 'COMPLETED', ended_at = CURRENT_TIMESTAMP "
        "WHERE id = :id",
        {"id": round_id},
    )
