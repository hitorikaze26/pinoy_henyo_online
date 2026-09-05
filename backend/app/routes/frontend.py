import os
from urllib.parse import quote

from flask import Blueprint, redirect, request, send_from_directory

# Resolve the frontend directory relative to this file:
# backend/app/routes/ -> backend/app/ -> backend/ -> project root -> frontend/
_FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend")
)

frontend_bp = Blueprint("frontend", __name__)


def _is_joinable(game):
    """A deep-link only makes sense for games that still accept players."""
    from ..models.game import Game

    return game is not None and game.status in (
        Game.STATUS_LOBBY,
        Game.STATUS_SETUP,
        Game.STATUS_READY,
        Game.STATUS_ROUND_1,
        Game.STATUS_ROUND_2,
        Game.STATUS_PAUSED,
        Game.STATUS_TIE_BREAKER,
    )


@frontend_bp.get("/")
def index():
    """Serve the landing page."""
    return send_from_directory(_FRONTEND_DIR, "index.html")


@frontend_bp.get("/join/game/<string:game_code>")
def join_game_deep_link(game_code):
    """Resolve a scanned/tapped game QR deep-link to the landing page.

    The landing page consumes ``?game=`` (and ``?team=``) to pre-fill the
    Join modal (see Connect.parseLocation / handleDeepLinkJoin). Only the
    public game code is carried — never auth tokens.
    """
    from ..services.game_service import get_game_by_code

    code = game_code.upper()
    game = get_game_by_code(code)
    if not _is_joinable(game):
        return redirect("/?error=not_found&game={}".format(quote(code)))
    return redirect("/?game={}".format(quote(code)))


@frontend_bp.get("/join/team/<string:team_code>")
def join_team_deep_link(team_code):
    """Resolve a scanned/tapped team QR deep-link to the landing page.

    The team QR payload carries both codes: ``/join/team/<TEAM_CODE>?game=
    <GAME_CODE>``. Resolve the game + team and forward both to the landing
    page so the Join modal can pre-fill them.
    """
    from ..db.team_repo import find_by_game_and_code
    from ..services.game_service import get_game_by_code

    code = team_code.upper()
    game_code = request.args.get("game", "").upper().strip()
    if not game_code:
        return redirect("/?error=missing_game&team={}".format(quote(code)))
    game = get_game_by_code(game_code)
    if not _is_joinable(game):
        return redirect("/?error=not_found&game={}".format(quote(game_code)))
    team = find_by_game_and_code(game.id, code)
    if team is None:
        return redirect(
            "/?error=team_not_found&game={}".format(quote(game_code))
        )
    return redirect(
        "/?game={}&team={}".format(quote(game_code), quote(code))
    )


@frontend_bp.get("/<path:filename>")
def static_files(filename):
    """Serve any other frontend asset (CSS, JS, images, pages, etc.)."""
    return send_from_directory(_FRONTEND_DIR, filename)