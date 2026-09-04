"""Member repository — raw SQL data access for ``team_members``."""

from ..utils.db import query_one, query_all, execute, insert


def find_by_id(member_id):
    return query_one(
        "SELECT * FROM team_members WHERE id = :id",
        {"id": member_id},
    )


def find_by_connection_token(token):
    return query_one(
        "SELECT * FROM team_members WHERE connection_token = :token",
        {"token": token},
    )


def find_all_by_team(team_id):
    return query_all(
        "SELECT * FROM team_members WHERE team_id = :team_id ORDER BY id",
        {"team_id": team_id},
    )


def create_member(team_id, username, device_role, connection_token):
    return insert(
        "INSERT INTO team_members "
        "(team_id, username, device_role, connection_token) "
        "VALUES (:team_id, :username, :device_role, :token)",
        {
            "team_id": team_id,
            "username": username,
            "device_role": device_role,
            "token": connection_token,
        },
    )


def update_username(member_id, username):
    return execute(
        "UPDATE team_members SET username = :username, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = :id",
        {"id": member_id, "username": username},
    )


def update_gameplay_role(member_id, role):
    return execute(
        "UPDATE team_members SET gameplay_role = :role, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = :id",
        {"id": member_id, "role": role},
    )


def set_connected(member_id, is_connected):
    return execute(
        "UPDATE team_members SET is_connected = :connected, "
        "last_seen_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = :id",
        {"id": member_id, "connected": int(is_connected)},
    )


def delete_member(member_id):
    return execute(
        "DELETE FROM team_members WHERE id = :id",
        {"id": member_id},
    )


def count_members_in_team(team_id):
    row = query_one(
        "SELECT COUNT(*) AS cnt FROM team_members WHERE team_id = :team_id",
        {"team_id": team_id},
    )
    return row["cnt"] if row else 0
