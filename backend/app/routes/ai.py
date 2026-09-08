import time
from threading import Lock

from flask import Blueprint, current_app, request

from ..extensions import db
from ..models import Category
from ..services import ai_word_service, word_service
from ..services.game_service import get_game
from ..utils.auth import (
    SESSION_TOKEN_HEADER,
    host_authorized,
    host_token_from_request,
)
from ..utils.rate_limit import check_rate_limit
from ..utils.response import error_response, success_response

ai_bp = Blueprint("ai", __name__, url_prefix="/api")


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


def _handle(exc):
    return error_response(str(exc), code=exc.code, status=exc.status)


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


# Per-(game, actor) in-memory cooldown so one device cannot hammer Gemini.
def _cooldown_store():
    if not hasattr(current_app, "_ai_cooldown"):
        current_app._ai_cooldown = {}
        current_app._ai_cooldown_lock = Lock()
    return current_app._ai_cooldown, current_app._ai_cooldown_lock


def _cooldown_key(game, actor):
    who = "host" if actor.host else "team:{}".format(actor.team_id)
    return "{}:{}".format(game.id, who)


def _rate_limited_resp(retry_after):
    resp, status = error_response(
        "Too many AI word requests. Try again shortly.",
        code="AI_RATE_LIMITED",
        status=429,
        retry_after=retry_after,
    )
    resp.headers["Retry-After"] = str(retry_after)
    return resp, status


def _log_and_rate_limit(game, actor, category, language, count, retry_after):
    ai_word_service.log_generation(
        game,
        actor,
        category,
        requested_count=count,
        accepted_count=0,
        success=False,
        language=language,
        error_code="AI_RATE_LIMITED",
    )
    return _rate_limited_resp(retry_after)


@ai_bp.post("/games/<int:game_id>/ai/generate-words")
def generate_words(game_id):
    body = request.get_json(silent=True) or {}
    game, error = _load_game(game_id)
    if error is not None:
        return error
    actor, error = _resolve_actor(game, body)
    if error is not None:
        return error

    category_id = body.get("category_id")
    if category_id is None:
        return error_response(
            "A category is required.", code="CATEGORY_REQUIRED", status=400
        )
    category = db.session.get(Category, category_id)
    if category is None or category.game_id != game.id:
        return error_response(
            "The category does not belong to this game.",
            code="CATEGORY_NOT_IN_GAME",
            status=400,
        )

    count = body.get("count")
    max_request = current_app.config.get("AI_MAX_WORDS_PER_REQUEST", 20)
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or count < 1
        or count > max_request
    ):
        return error_response(
            "count must be an integer between 1 and {}.".format(max_request),
            code="AI_WORD_COUNT_INVALID",
            status=400,
        )

    language = str(body.get("language") or ai_word_service.LANGUAGE_TAGALOG).lower()
    place = ai_word_service.is_place_category(category)
    if not place and language not in ai_word_service.LANGUAGES:
        return error_response(
            "language must be one of: {}.".format(
                ", ".join(ai_word_service.LANGUAGES)
            ),
            code="AI_LANGUAGE_INVALID",
            status=400,
        )
    effective = None if place else language

    exclude_words = body.get("exclude_words")
    if exclude_words is not None and not isinstance(exclude_words, list):
        return error_response(
            "exclude_words must be a list of words.",
            code="AI_EXCLUDE_WORDS_INVALID",
            status=400,
        )

    ok, retry_after = check_rate_limit(
        "ai_generate_words",
        current_app.config.get("AI_MAX_REQUESTS_PER_MINUTE", 5),
        60,
    )
    if not ok:
        return _log_and_rate_limit(
            game, actor, category, effective, count, retry_after
        )

    store, lock = _cooldown_store()
    now = time.monotonic()
    cooldown = current_app.config.get("AI_REQUEST_COOLDOWN_SECONDS", 5)
    with lock:
        last = store.get(_cooldown_key(game, actor))
        if last is not None and now - last < cooldown:
            retry_after = max(0, int(cooldown - (now - last)))
            return _log_and_rate_limit(
                game, actor, category, effective, count, retry_after
            )
        store[_cooldown_key(game, actor)] = now

    try:
        result = ai_word_service.generate_suggestions(
            game,
            actor,
            category,
            count=count,
            language=language,
            exclude_words=exclude_words or [],
        )
    except ai_word_service.AIServiceError as exc:
        db.session.rollback()
        ai_word_service.log_generation(
            game,
            actor,
            category,
            requested_count=count,
            accepted_count=0,
            success=False,
            language=effective,
            error_code=exc.code,
        )
        return _handle(exc)

    ai_word_service.log_generation(
        game,
        actor,
        category,
        requested_count=count,
        accepted_count=len(result["suggestions"]),
        success=True,
        language=result["language"],
    )
    db.session.commit()
    return success_response(data=result)