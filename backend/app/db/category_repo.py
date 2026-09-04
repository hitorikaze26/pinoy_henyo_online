"""Category repository — raw SQL data access for the ``categories`` table."""

from ..utils.db import query_one, query_all, execute, insert


def find_by_id(category_id):
    return query_one(
        "SELECT * FROM categories WHERE id = :id",
        {"id": category_id},
    )


def find_by_game_and_name(game_id, name):
    return query_one(
        "SELECT * FROM categories WHERE game_id = :game_id AND name = :name",
        {"game_id": game_id, "name": name},
    )


def find_all_by_game(game_id):
    return query_all(
        "SELECT * FROM categories WHERE game_id = :game_id ORDER BY name",
        {"game_id": game_id},
    )


def create_category(game_id, name):
    return insert(
        "INSERT INTO categories (game_id, name) VALUES (:game_id, :name)",
        {"game_id": game_id, "name": name},
    )


def update_name(category_id, name):
    return execute(
        "UPDATE categories SET name = :name WHERE id = :id",
        {"id": category_id, "name": name},
    )


def delete_category(category_id):
    return execute(
        "DELETE FROM categories WHERE id = :id",
        {"id": category_id},
    )
