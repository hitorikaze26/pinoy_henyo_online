"""Word repository — raw SQL data access for the ``words`` table."""

from ..utils.db import query_one, query_all, execute, insert


def find_by_id(word_id):
    return query_one(
        "SELECT * FROM words WHERE id = :id",
        {"id": word_id},
    )


def find_by_game_and_normalized(game_id, category_id, normalized):
    return query_one(
        "SELECT * FROM words "
        "WHERE game_id = :game_id AND category_id = :category_id "
        "AND normalized_word = :normalized",
        {"game_id": game_id, "category_id": category_id, "normalized": normalized},
    )


def find_all_by_game(game_id):
    return query_all(
        "SELECT * FROM words WHERE game_id = :game_id ORDER BY id",
        {"game_id": game_id},
    )


def find_all_by_team(game_id, team_id):
    return query_all(
        "SELECT * FROM words "
        "WHERE game_id = :game_id AND submitted_by_team_id = :team_id "
        "ORDER BY id",
        {"game_id": game_id, "team_id": team_id},
    )


def find_all_by_category(game_id, category_id):
    return query_all(
        "SELECT * FROM words "
        "WHERE game_id = :game_id AND category_id = :category_id "
        "ORDER BY id",
        {"game_id": game_id, "category_id": category_id},
    )


def count_active_by_category(game_id, category_id, team_id=None):
    params = {"game_id": game_id, "category_id": category_id}
    extra = ""
    if team_id is not None:
        extra = " AND submitted_by_team_id = :team_id"
        params["team_id"] = team_id
    row = query_one(
        "SELECT COUNT(*) AS cnt FROM words "
        "WHERE game_id = :game_id AND category_id = :category_id "
        "AND status != 'DISABLED'" + extra,
        params,
    )
    return row["cnt"] if row else 0


def create_word(game_id, category_id, team_id, word_text, normalized_word):
    return insert(
        "INSERT INTO words "
        "(game_id, category_id, submitted_by_team_id, word_text, normalized_word) "
        "VALUES (:game_id, :category_id, :team_id, :word_text, :normalized)",
        {
            "game_id": game_id,
            "category_id": category_id,
            "team_id": team_id,
            "word_text": word_text,
            "normalized": normalized_word,
        },
    )


def update_text(word_id, word_text, normalized_word):
    return execute(
        "UPDATE words SET word_text = :word_text, normalized_word = :normalized, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = :id",
        {"id": word_id, "word_text": word_text, "normalized": normalized_word},
    )


def update_status(word_id, status):
    return execute(
        "UPDATE words SET status = :status, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = :id",
        {"id": word_id, "status": status},
    )


def delete_word(word_id):
    return execute(
        "DELETE FROM words WHERE id = :id",
        {"id": word_id},
    )


def count_in_game(game_id):
    row = query_one(
        "SELECT COUNT(*) AS cnt FROM words WHERE game_id = :game_id",
        {"game_id": game_id},
    )
    return row["cnt"] if row else 0
