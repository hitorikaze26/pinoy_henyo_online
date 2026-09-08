import secrets
from functools import wraps

from flask import request

from ..extensions import db
from ..models import DeviceSession, Game
from .response import error_response
from .time import utcnow

HOST_TOKEN_HEADER = "X-Host-Token"
SESSION_TOKEN_HEADER = "X-Session-Token"


def host_token_from_request():
    token = request.headers.get(HOST_TOKEN_HEADER)
    if token:
        return token
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        return authorization[len("Bearer "):]
    return None


def game_session_authorized(game):
    """True when a valid, connected device session exists for this game.

    Used for read-only player-facing endpoints (e.g. the leaderboard) where
    any active device of any team in the game may read public game state.
    """
    session_token = request.headers.get(SESSION_TOKEN_HEADER)
    if not session_token:
        return False
    session = (
        DeviceSession.query.filter_by(
            session_token=session_token,
            game_id=game.id,
            disconnected_at=None,
        ).first()
        if game is not None
        else None
    )
    return session is not None


def host_authorized(game):
    token = host_token_from_request()
    if not token:
        return False
    expected = game.host_session_token or ""
    return secrets.compare_digest(token, expected)


def require_host(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        game_id = kwargs.pop("game_id", None)
        game = db.session.get(Game, game_id) if game_id is not None else None
        if game is None:
            return error_response(
                "Game not found.", code="GAME_NOT_FOUND", status=404
            )
        token = host_token_from_request()
        expected = game.host_session_token or ""
        if not token or not secrets.compare_digest(token, expected):
            return error_response(
                "Invalid or missing host session token.",
                code="UNAUTHORIZED",
                status=401,
            )
        kwargs["game"] = game
        # Track host activity so the maintenance sweeper can expire games whose
        # host has been absent for > HOST_INACTIVITY_TIMEOUT.
        game.host_last_seen_at = utcnow()
        return fn(*args, **kwargs)

    return wrapper