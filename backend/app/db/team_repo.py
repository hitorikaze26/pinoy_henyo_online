"""Team repository — raw SQL data access for the ``teams`` table."""

from ..utils.db import query_one, query_all, execute, insert


def find_by_id(team_id):
    return query_one(
        "SELECT * FROM teams WHERE id = :id",
        {"id": team_id},
    )


def find_by_game_and_code(game_id, team_code):
    return query_one(
        "SELECT * FROM teams WHERE game_id = :game_id AND team_code = :code",
        {"game_id": game_id, "code": team_code},
    )


def find_all_by_game(game_id):
    return query_all(
        "SELECT * FROM teams WHERE game_id = :game_id ORDER BY id",
        {"game_id": game_id},
    )


def create_team(game_id, team_code, team_name, connection_status="NOT_CONNECTED"):
    return insert(
        "INSERT INTO teams (game_id, team_code, team_name, connection_status) "
        "VALUES (:game_id, :team_code, :team_name, :connection_status)",
        {
            "game_id": game_id,
            "team_code": team_code,
            "team_name": team_name,
            "connection_status": connection_status,
        },
    )


def update_name(team_id, team_name):
    return execute(
        "UPDATE teams SET team_name = :name, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = :id",
        {"id": team_id, "name": team_name},
    )


def update_connection_status(team_id, status):
    return execute(
        "UPDATE teams SET connection_status = :status, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = :id",
        {"id": team_id, "status": status},
    )


def update_leader(team_id, leader_member_id):
    return execute(
        "UPDATE teams SET leader_member_id = :leader_id, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = :id",
        {"id": team_id, "leader_id": leader_member_id},
    )


def delete_team(team_id):
    return execute(
        "DELETE FROM teams WHERE id = :id",
        {"id": team_id},
    )


def count_teams_in_game(game_id):
    row = query_one(
        "SELECT COUNT(*) AS cnt FROM teams WHERE game_id = :game_id",
        {"game_id": game_id},
    )
    return row["cnt"] if row else 0
