from flask import Blueprint

from ..extensions import db
from ..services import game_service, realtime, report_service
from ..utils.auth import host_authorized, host_token_from_request, require_host
from ..utils.rate_limit import rate_limit
from ..utils.response import error_response, success_response

games_bp = Blueprint("games", __name__, url_prefix="/api/games")


@games_bp.post("")
@rate_limit("games_create", limit=30, window_seconds=60)
def create_game():
    game = game_service.create_game()
    return success_response(
        data={
            "game_id": game.id,
            "game_code": game.game_code,
            "host_session_token": game.host_session_token,
            "status": game.status,
        },
        status=201,
    )


@games_bp.get("/by-code/<string:game_code>")
def get_game_by_code(game_code):
    game = game_service.get_game_by_code(game_code.upper())
    if game is None:
        return error_response(
            "Game not found.", code="GAME_NOT_FOUND", status=404
        )
    return success_response(data=_game_summary(game))


@games_bp.get("/<int:game_id>")
def get_game(game_id):
    game = game_service.get_game(game_id)
    if game is None:
        return error_response(
            "Game not found.", code="GAME_NOT_FOUND", status=404
        )
    return success_response(data=_game_summary(game))


@games_bp.get("/<int:game_id>/status")
def get_game_status(game_id):
    game = game_service.get_game(game_id)
    if game is None:
        return error_response(
            "Game not found.", code="GAME_NOT_FOUND", status=404
        )
    return success_response(
        data={
            "game_id": game.id,
            "game_code": game.game_code,
            "status": game.status,
            "word_pool_locked": game.status not in (game_service.Game.STATUS_LOBBY, game_service.Game.STATUS_SETUP),
            "current_round": game.current_round,
            "current_match_id": game.current_match_id,
            "created_at": game.created_at,
            "started_at": game.started_at,
            "ended_at": game.ended_at,
        }
    )


def _execute(action, game, emitter=None):
    try:
        data = action(game)
    except game_service.GameStateError as exc:
        return error_response(
            str(exc), code="INVALID_TRANSITION", status=409
        )
    db.session.commit()
    if emitter is not None:
        emitter(game)
    return success_response(data=data)


@games_bp.post("/<int:game_id>/start")
@require_host
def start_game(game):
    return _execute(game_service.start_game, game, realtime.emit_game_started)


@games_bp.post("/<int:game_id>/pause")
@require_host
def pause_game(game):
    return _execute(game_service.pause_game, game, realtime.emit_game_paused)


@games_bp.post("/<int:game_id>/resume")
@require_host
def resume_game(game):
    return _execute(game_service.resume_game, game, realtime.emit_game_resumed)


@games_bp.post("/<int:game_id>/end")
@require_host
def end_game(game):
    return _execute(game_service.end_game, game, realtime.emit_game_completed)


def _game_summary(game):
    return {
        "game_id": game.id,
        "game_code": game.game_code,
        "status": game.status,
        "created_at": game.created_at,
        "started_at": game.started_at,
        "ended_at": game.ended_at,
    }


def _history_or_error(game):
    return success_response(data=report_service.game_history(game))


@games_bp.get("/history")
def game_history_list():
    token = host_token_from_request()
    if not token:
        return error_response(
            "A host session token is required.",
            code="UNAUTHORIZED",
            status=401,
        )
    games = report_service.games_history_for_host(token)
    if not games:
        return error_response(
            "No game found for the provided host token.",
            code="GAME_NOT_FOUND",
            status=404,
        )
    return success_response(data={"games": games})


@games_bp.get("/<int:game_id>/history")
def game_history(game_id):
    game = game_service.get_game(game_id)
    if game is None:
        return error_response(
            "Game not found.", code="GAME_NOT_FOUND", status=404
        )
    token = host_token_from_request()
    if not token or not host_authorized(game):
        return error_response(
            "Invalid or missing host session token.",
            code="UNAUTHORIZED",
            status=401,
        )
    return _history_or_error(game)


@games_bp.get("/<int:game_id>/leaderboard")
def game_leaderboard(game_id):
    game = game_service.get_game(game_id)
    if game is None:
        return error_response(
            "Game not found.", code="GAME_NOT_FOUND", status=404
        )
    token = host_token_from_request()
    if not token or not host_authorized(game):
        return error_response(
            "Invalid or missing host session token.",
            code="UNAUTHORIZED",
            status=401,
        )
    return success_response(
        data={"leaderboard": report_service.leaderboard(game)}
    )


@games_bp.get("/<int:game_id>/statistics")
def game_statistics(game_id):
    game = game_service.get_game(game_id)
    if game is None:
        return error_response(
            "Game not found.", code="GAME_NOT_FOUND", status=404
        )
    token = host_token_from_request()
    if not token or not host_authorized(game):
        return error_response(
            "Invalid or missing host session token.",
            code="UNAUTHORIZED",
            status=401,
        )
    return success_response(data=report_service.statistics(game))