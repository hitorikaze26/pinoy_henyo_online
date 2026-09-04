"""Turn repository — raw SQL data access for ``turns`` and ``turn_words``."""

from ..utils.db import query_one, query_all, execute, insert


# --- Turns ----------------------------------------------------------------

def find_turn_by_id(turn_id):
    return query_one(
        "SELECT * FROM turns WHERE id = :id",
        {"id": turn_id},
    )


def find_all_turns_by_match(match_id):
    return query_all(
        "SELECT * FROM turns WHERE match_id = :match_id ORDER BY turn_order",
        {"match_id": match_id},
    )


def count_waiting_by_match(match_id):
    row = query_one(
        "SELECT COUNT(*) AS cnt FROM turns "
        "WHERE match_id = :match_id AND status = 'WAITING'",
        {"match_id": match_id},
    )
    return row["cnt"] if row else 0


def create_turn(match_id, team_id, round_id, turn_order, starting_seconds=0):
    return insert(
        "INSERT INTO turns "
        "(match_id, team_id, round_id, turn_order, starting_seconds, "
        "remaining_seconds) "
        "VALUES (:match_id, :team_id, :round_id, :turn_order, :starting, :remaining)",
        {
            "match_id": match_id,
            "team_id": team_id,
            "round_id": round_id,
            "turn_order": turn_order,
            "starting": starting_seconds,
            "remaining": starting_seconds,
        },
    )


def update_turn_status(turn_id, status):
    return execute(
        "UPDATE turns SET status = :status WHERE id = :id",
        {"id": turn_id, "status": status},
    )


def start_turn(turn_id, starting_seconds):
    return execute(
        "UPDATE turns SET status = 'ACTIVE', starting_seconds = :starting, "
        "remaining_seconds = :starting, started_at = CURRENT_TIMESTAMP "
        "WHERE id = :id",
        {"id": turn_id, "starting": starting_seconds},
    )


def end_turn(turn_id, status, remaining_seconds):
    return execute(
        "UPDATE turns SET status = :status, remaining_seconds = :remaining, "
        "ended_at = CURRENT_TIMESTAMP WHERE id = :id",
        {"id": turn_id, "status": status, "remaining": remaining_seconds},
    )


def pause_turn(turn_id):
    return execute(
        "UPDATE turns SET status = 'PAUSED', paused_at = CURRENT_TIMESTAMP "
        "WHERE id = :id",
        {"id": turn_id},
    )


def resume_turn(turn_id, pause_total):
    return execute(
        "UPDATE turns SET status = 'ACTIVE', paused_at = NULL, "
        "pause_total_seconds = :pause_total WHERE id = :id",
        {"id": turn_id, "pause_total": pause_total},
    )


def adjust_time(turn_id, adjustment):
    return execute(
        "UPDATE turns SET timer_adjustment_seconds = timer_adjustment_seconds + :adj "
        "WHERE id = :id",
        {"id": turn_id, "adj": adjustment},
    )


# --- Turn Words -----------------------------------------------------------

def find_turn_word(turn_id, word_id):
    return query_one(
        "SELECT * FROM turn_words WHERE turn_id = :turn_id AND word_id = :word_id",
        {"turn_id": turn_id, "word_id": word_id},
    )


def find_turn_words(turn_id):
    return query_all(
        "SELECT * FROM turn_words WHERE turn_id = :turn_id ORDER BY sequence",
        {"turn_id": turn_id},
    )


def create_turn_word(turn_id, word_id, sequence):
    return insert(
        "INSERT INTO turn_words (turn_id, word_id, sequence) "
        "VALUES (:turn_id, :word_id, :sequence)",
        {"turn_id": turn_id, "word_id": word_id, "sequence": sequence},
    )


def update_turn_word_result(turn_word_id, result):
    return execute(
        "UPDATE turn_words SET result = :result, used_at = CURRENT_TIMESTAMP "
        "WHERE id = :id",
        {"id": turn_word_id, "result": result},
    )
