from flask import Blueprint, request

from ..extensions import db
from ..models import Word
from ..services import word_service
from ..services.game_service import get_game
from ..utils.auth import host_authorized, host_token_from_request
from ..utils.response import error_response, success_response

words_bp = Blueprint("words", __name__, url_prefix="/api")

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
        "Invalid or missing host session token.",
        code="UNAUTHORIZED",
        status=401,
    )


def _ensure_mutable(game):
    from ..services.game_service import GameFrozenError, assert_game_mutable

    try:
        assert_game_mutable(game)
    except GameFrozenError as exc:
        return error_response(str(exc), code=exc.code, status=exc.status)
    return None


def _handle(exc):
    return error_response(str(exc), code=exc.code, status=exc.status)


def _word_or_404(word_id):
    word = word_service.get_word(word_id)
    if word is None:
        return None, error_response(
            "Word not found.", code="WORD_NOT_FOUND", status=404
        )
    return word, None


def _resolve_actor(game, body):
    token = host_token_from_request()
    if token is not None:
        if not host_authorized(game):
            return None, _unauthorized()
        return word_service.Actor(host=True), None
    try:
        team = word_service.resolve_submitting_team(
            game,
            session_token=request.headers.get(SESSION_TOKEN_HEADER),
            team_id=(body or {}).get("team_id"),
        )
    except word_service.WordServiceError as exc:
        return None, _handle(exc)
    return word_service.Actor(team=team), None


@words_bp.post("/games/<int:game_id>/words")
def create_word(game_id):
    body = request.get_json(silent=True) or {}
    game, error = _load_game(game_id)
    if error is not None:
        return error
    host_mode = host_token_from_request() is not None
    if host_mode and not host_authorized(game):
        return _unauthorized()
    frozen = _ensure_mutable(game)
    if frozen is not None:
        return frozen
    try:
        if host_mode:
            team = word_service.resolve_team_for_host(
                game, body.get("team_id")
            )
            return _handle_submit(game, body, team, host_mode)
        team = word_service.resolve_submitting_team(
            game,
            session_token=request.headers.get(SESSION_TOKEN_HEADER),
            team_id=body.get("team_id"),
        )
        return _handle_submit(game, body, team, host_mode)
    except word_service.WordServiceError as exc:
        db.session.rollback()
        return _handle(exc)


def _handle_submit(game, body, team, host_mode):
    word = word_service.submit_word(
        game,
        team=team,
        category_id=body.get("category_id"),
        word_text=body.get("word_text"),
        host=host_mode,
    )
    db.session.commit()
    return success_response(data=word_service.word_payload(word), status=201)


@words_bp.get("/games/<int:game_id>/words/my")
def list_my_words(game_id):
    game, error = _load_game(game_id)
    if error is not None:
        return error
    try:
        team = word_service.resolve_submitting_team(
            game,
            session_token=request.headers.get(SESSION_TOKEN_HEADER),
            team_id=None,
        )
    except word_service.WordServiceError as exc:
        return _handle(exc)
    words = [
        word_service.word_payload(w, with_relations=True)
        for w in Word.query.filter_by(
            game_id=game.id, submitted_by_team_id=team.id
        ).order_by(Word.id).all()
    ]
    return success_response(data={"team_id": team.id, "words": words})


@words_bp.get("/games/<int:game_id>/words")
def list_words(game_id):
    game, error = _load_game(game_id)
    if error is not None:
        return error
    token = host_token_from_request()
    if token is None or not host_authorized(game):
        return _unauthorized()
    return success_response(data={"words": word_service.list_words(game)})


@words_bp.patch("/words/<int:word_id>")
def update_word(word_id):
    body = request.get_json(silent=True) or {}
    word, error = _word_or_404(word_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(word.game)
    if frozen is not None:
        return frozen
    actor, error = _resolve_actor(word.game, body)
    if error is not None:
        return error
    try:
        word = word_service.update_word(
            word, word.game, body.get("word_text"), actor
        )
        db.session.commit()
    except word_service.WordServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(data=word_service.word_payload(word))


@words_bp.delete("/words/<int:word_id>")
def delete_word(word_id):
    body = request.get_json(silent=True) or {}
    word, error = _word_or_404(word_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(word.game)
    if frozen is not None:
        return frozen
    actor, error = _resolve_actor(word.game, body)
    if error is not None:
        return error
    try:
        word_service.delete_word(word, word.game, actor)
        db.session.commit()
    except word_service.WordServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(message="Word deleted.")


@words_bp.post("/words/<int:word_id>/disable")
def disable_word(word_id):
    body = request.get_json(silent=True) or {}
    word, error = _word_or_404(word_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(word.game)
    if frozen is not None:
        return frozen
    actor, error = _resolve_actor(word.game, body)
    if error is not None:
        return error
    try:
        word = word_service.disable_word(word, word.game, actor)
        db.session.commit()
    except word_service.WordServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(data=word_service.word_payload(word))