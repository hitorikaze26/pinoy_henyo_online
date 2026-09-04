"""Penalty repository — raw SQL data access for the ``penalties`` table."""

from ..utils.db import query_one, query_all, execute, insert


def find_by_id(penalty_id):
    return query_one(
        "SELECT * FROM penalties WHERE id = :id",
        {"id": penalty_id},
    )


def find_all_by_turn(turn_id):
    return query_all(
        "SELECT * FROM penalties WHERE turn_id = :turn_id ORDER BY id",
        {"turn_id": turn_id},
    )


def find_all_by_team(game_id, team_id):
    return query_all(
        "SELECT p.* FROM penalties p "
        "JOIN turns t ON t.id = p.turn_id "
        "WHERE t.round_id IN ("
        "  SELECT r.id FROM rounds r WHERE r.game_id = :game_id"
        ") AND p.team_id = :team_id",
        {"game_id": game_id, "team_id": team_id},
    )


def create_penalty(turn_id, team_id, seconds, penalty_type, reason=None):
    return insert(
        "INSERT INTO penalties (turn_id, team_id, seconds, type, reason) "
        "VALUES (:turn_id, :team_id, :seconds, :type, :reason)",
        {
            "turn_id": turn_id,
            "team_id": team_id,
            "seconds": seconds,
            "type": penalty_type,
            "reason": reason,
        },
    )


def delete_penalty(penalty_id):
    return execute(
        "DELETE FROM penalties WHERE id = :id",
        {"id": penalty_id},
    )


def count_by_turn(turn_id):
    row = query_one(
        "SELECT COUNT(*) AS cnt FROM penalties WHERE turn_id = :turn_id",
        {"turn_id": turn_id},
    )
    return row["cnt"] if row else 0
