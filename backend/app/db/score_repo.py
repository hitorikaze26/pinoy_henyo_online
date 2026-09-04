"""Score repository — raw SQL data access for the ``scores`` table."""

from ..utils.db import query_one, query_all, execute, insert


def find_by_id(score_id):
    return query_one(
        "SELECT * FROM scores WHERE id = :id",
        {"id": score_id},
    )


def find_by_team_round_match(game_id, team_id, round_id, match_id):
    return query_one(
        "SELECT * FROM scores "
        "WHERE game_id = :game_id AND team_id = :team_id "
        "AND round_id = :round_id AND match_id = :match_id",
        {
            "game_id": game_id,
            "team_id": team_id,
            "round_id": round_id,
            "match_id": match_id,
        },
    )


def find_all_by_game(game_id):
    return query_all(
        "SELECT * FROM scores WHERE game_id = :game_id ORDER BY team_id, round_id",
        {"game_id": game_id},
    )


def find_all_by_team(game_id, team_id):
    return query_all(
        "SELECT * FROM scores WHERE game_id = :game_id AND team_id = :team_id",
        {"game_id": game_id, "team_id": team_id},
    )


def create_score(game_id, team_id, round_id=None, match_id=None):
    return insert(
        "INSERT INTO scores (game_id, team_id, round_id, match_id) "
        "VALUES (:game_id, :team_id, :round_id, :match_id)",
        {
            "game_id": game_id,
            "team_id": team_id,
            "round_id": round_id,
            "match_id": match_id,
        },
    )


def increment_counter(score_id, column, amount=1):
    """Increment a counter column (correct_words, passed_words, etc.)."""
    return execute(
        "UPDATE scores SET {col} = {col} + :amount, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = :id".format(col=column),
        {"id": score_id, "amount": amount},
    )


def add_points(score_id, points):
    return increment_counter(score_id, "points", points)


def increment_correct(score_id, count=1):
    return increment_counter(score_id, "correct_words", count)


def increment_passed(score_id, count=1):
    return increment_counter(score_id, "passed_words", count)


def increment_failed(score_id, count=1):
    return increment_counter(score_id, "failed_words", count)


def update_penalty_seconds(score_id, seconds):
    return execute(
        "UPDATE scores SET penalty_seconds = :seconds, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = :id",
        {"id": score_id, "seconds": seconds},
    )


def leaderboard(game_id):
    return query_all(
        "SELECT s.team_id, t.team_code, t.team_name, "
        "SUM(s.points) AS points, "
        "SUM(s.correct_words) AS correct_words, "
        "SUM(s.passed_words) AS passed_words, "
        "SUM(s.failed_words) AS failed_words, "
        "SUM(s.penalty_seconds) AS penalty_seconds, "
        "SUM(s.time_bonus_seconds) AS time_bonus_seconds "
        "FROM scores s "
        "JOIN teams t ON t.id = s.team_id "
        "WHERE s.game_id = :game_id "
        "GROUP BY s.team_id, t.team_code, t.team_name "
        "ORDER BY points DESC, correct_words DESC, "
        "penalty_seconds ASC, t.team_code ASC",
        {"game_id": game_id},
    )
