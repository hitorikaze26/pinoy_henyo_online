"""Match repository — raw SQL data access for the ``matches`` table."""

from ..utils.db import query_one, query_all, execute, insert


def find_by_id(match_id):
    return query_one(
        "SELECT * FROM matches WHERE id = :id",
        {"id": match_id},
    )


def find_all_by_round(round_id):
    return query_all(
        "SELECT * FROM matches WHERE round_id = :round_id ORDER BY match_order",
        {"round_id": round_id},
    )


def find_all_by_game(game_id):
    return query_all(
        "SELECT * FROM matches WHERE game_id = :game_id ORDER BY id",
        {"game_id": game_id},
    )


def create_match(game_id, round_id, match_order, team_id, opponent_team_id=None):
    return insert(
        "INSERT INTO matches "
        "(game_id, round_id, match_order, team_id, opponent_team_id) "
        "VALUES (:game_id, :round_id, :match_order, :team_id, :opponent_team_id)",
        {
            "game_id": game_id,
            "round_id": round_id,
            "match_order": match_order,
            "team_id": team_id,
            "opponent_team_id": opponent_team_id,
        },
    )


def update_status(match_id, status):
    return execute(
        "UPDATE matches SET status = :status WHERE id = :id",
        {"id": match_id, "status": status},
    )


def complete_match(match_id, winner_team_id):
    return execute(
        "UPDATE matches SET status = 'COMPLETED', winner_team_id = :winner, "
        "ended_at = CURRENT_TIMESTAMP WHERE id = :id",
        {"id": match_id, "winner": winner_team_id},
    )
