from flask import Blueprint, request

from ..extensions import db
from ..models import Team, Word, WordChangeRequest
from ..services import realtime, word_change_request_service as wcr
from ..services import word_service
from ..services.game_service import GameFrozenError, assert_game_mutable, get_game
from ..utils.auth import host_authorized, host_token_from_request
from ..utils.response import error_response, success_response

word_requests_bp = Blueprint("word_requests", __name__, url_prefix="/api")

SESSION_TOKEN_HEADER = "X-Session-Token"


def _load_game(game_id):
    game = get_game(game_id)
    if game is None:
        return None, error_response(
            "Game not found.", code="GAME_NOT_FOUND", status=404
        )
    return game, None


def _unauthorized():
    return error_response(
        "Invalid or missing authentication.",
        code="UNAUTHORIZED",
        status=401,
    )


def _ensure_mutable(game):
    try:
        assert_game_mutable(game)
    except GameFrozenError as exc:
        return error_response(str(exc), code=exc.code, status=exc.status)
    return None


def _handle(exc):
    return error_response(str(exc), code=exc.code, status=exc.status)


def _request_or_404(request_id):
    req = wcr.get_request(request_id)
    if req is None:
        return None, error_response(
            "Word change request not found.",
            code="REQUEST_NOT_FOUND",
            status=404,
        )
    return req, None


def _host_for_game(request_or_game):
    token = host_token_from_request()
    if token is None or not host_authorized(request_or_game):
        return None
    return token


def _resolve_player_team(game):
    try:
        team = word_service.resolve_submitting_team(
            game,
            session_token=request.headers.get(SESSION_TOKEN_HEADER),
            team_id=None,
        )
    except word_service.WordServiceError as exc:
        return None, _handle(exc)
    return team, None


@word_requests_bp.get("/games/<int:game_id>/word-change-requests")
def list_word_change_requests(game_id):
    game, error = _load_game(game_id)
    if error is not None:
        return error
    if _host_for_game(game) is not None:
        team_id = (request.args.get("team_id") or None)
        if team_id is not None:
            try:
                team_id = int(team_id)
            except (TypeError, ValueError):
                return error_response(
                    "Invalid team_id.", code="INVALID_TEAM_ID", status=400
                )
        requests = wcr.list_game_requests(game, team_id=team_id)
        return success_response(
            data={"requests": [wcr.request_payload(r) for r in requests]}
        )
    team, resolve_error = _resolve_player_team(game)
    if resolve_error is not None:
        return resolve_error
    requests = wcr.list_team_pending(game, team)
    return success_response(
        data={
            "team_id": team.id,
            "requests": [wcr.request_payload(r) for r in requests],
        }
    )


@word_requests_bp.post("/games/<int:game_id>/word-change-requests")
def create_word_change_request(game_id):
    body = request.get_json(silent=True) or {}
    game, error = _load_game(game_id)
    if error is not None:
        return error
    if _host_for_game(game) is None:
        return _unauthorized()
    frozen = _ensure_mutable(game)
    if frozen is not None:
        return frozen
    team = db.session.get(Team, body.get("team_id"))
    word = db.session.get(Word, body.get("word_id"))
    if body.get("team_id") is None or team is None:
        return error_response(
            "A valid team is required.",
            code="TEAM_NOT_IN_GAME",
            status=400,
        )
    if body.get("word_id") is None or word is None:
        return error_response(
            "A valid word is required.",
            code="WORD_NOT_IN_GAME",
            status=400,
        )
    try:
        req = wcr.create_request(
            game, team, word, body.get("comment")
        )
        db.session.commit()
    except wcr.WordChangeRequestError as exc:
        db.session.rollback()
        return _handle(exc)
    realtime.emit_word_change_request(req)
    realtime.emit_word_pool_updated(game, team)
    return success_response(
        data=wcr.request_payload(req), status=201
    )


@word_requests_bp.post("/word-change-requests/<int:request_id>/resolve")
def resolve_word_change_request(request_id):
    body = request.get_json(silent=True) or {}
    req, error = _request_or_404(request_id)
    if error is not None:
        return error
    team, resolve_error = _resolve_player_team(req.game)
    if resolve_error is not None:
        return resolve_error
    try:
        req = wcr.resolve_request(req, team, body.get("word_text"))
        db.session.commit()
    except (
        wcr.WordChangeRequestError,
        word_service.WordServiceError,
    ) as exc:
        db.session.rollback()
        return _handle(exc)
    realtime.emit_word_change_resolved(req)
    realtime.emit_word_pool_updated(req.game, req.requesting_team)
    return success_response(data=wcr.request_payload(req))


@word_requests_bp.post("/word-change-requests/<int:request_id>/cancel")
def cancel_word_change_request(request_id):
    req, error = _request_or_404(request_id)
    if error is not None:
        return error
    if _host_for_game(req.game) is None:
        return _unauthorized()
    frozen = _ensure_mutable(req.game)
    if frozen is not None:
        return frozen
    try:
        req = wcr.cancel_request(req)
        db.session.commit()
    except wcr.WordChangeRequestError as exc:
        db.session.rollback()
        return _handle(exc)
    realtime.emit_word_change_cancelled(req)
    realtime.emit_word_pool_updated(req.game, req.requesting_team)
    return success_response(data=wcr.request_payload(req))