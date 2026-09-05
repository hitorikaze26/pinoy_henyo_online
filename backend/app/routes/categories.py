from flask import Blueprint, request

from ..extensions import db
from ..services import word_service
from ..services.game_service import get_game
from ..utils.auth import host_authorized, host_token_from_request
from ..utils.response import error_response, success_response

categories_bp = Blueprint("categories", __name__, url_prefix="/api")


def _load_game(game_id):
    game = get_game(game_id)
    if game is None:
        return None, error_response(
            "Game not found.", code="GAME_NOT_FOUND", status=404
        )
    return game, None


def _host_required(game):
    token = host_token_from_request()
    if token is None or not host_authorized(game):
        return error_response(
            "Invalid or missing host session token.",
            code="UNAUTHORIZED",
            status=401,
        )
    return None


def _handle(exc):
    return error_response(str(exc), code=exc.code, status=exc.status)


def _ensure_mutable(game):
    from ..services.game_service import GameFrozenError, assert_game_mutable

    try:
        assert_game_mutable(game)
    except GameFrozenError as exc:
        return error_response(str(exc), code=exc.code, status=exc.status)
    return None


@categories_bp.post("/games/<int:game_id>/categories")
def create_category(game_id):
    body = request.get_json(silent=True) or {}
    game, error = _load_game(game_id)
    if error is not None:
        return error
    denied = _host_required(game)
    if denied is not None:
        return denied
    frozen = _ensure_mutable(game)
    if frozen is not None:
        return frozen
    try:
        category = word_service.create_category(game, body.get("name"))
        db.session.commit()
    except word_service.WordServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(
        data=word_service.category_payload(category), status=201
    )


@categories_bp.get("/games/<int:game_id>/categories")
def list_categories(game_id):
    game, error = _load_game(game_id)
    if error is not None:
        return error
    if game.status in ("LOBBY", "SETUP", "READY"):
        try:
            categories = word_service.ensure_default_categories(game)
            db.session.commit()
        except word_service.WordServiceError as exc:
            db.session.rollback()
            return _handle(exc)
    else:
        categories = word_service.list_categories(game)
    return success_response(data={"categories": categories})


@categories_bp.patch("/categories/<int:category_id>")
def update_category(category_id):
    body = request.get_json(silent=True) or {}
    category = word_service.get_category(category_id)
    if category is None:
        return error_response(
            "Category not found.", code="CATEGORY_NOT_FOUND", status=404
        )
    denied = _host_required(category.game)
    if denied is not None:
        return denied
    frozen = _ensure_mutable(category.game)
    if frozen is not None:
        return frozen
    try:
        category = word_service.update_category(
            category, body.get("name")
        )
        db.session.commit()
    except word_service.WordServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(data=word_service.category_payload(category))


@categories_bp.delete("/categories/<int:category_id>")
def delete_category(category_id):
    category = word_service.get_category(category_id)
    if category is None:
        return error_response(
            "Category not found.", code="CATEGORY_NOT_FOUND", status=404
        )
    denied = _host_required(category.game)
    if denied is not None:
        return denied
    frozen = _ensure_mutable(category.game)
    if frozen is not None:
        return frozen
    try:
        word_service.delete_category(category)
        db.session.commit()
    except word_service.WordServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(message="Category deleted.")