import base64
import io

from flask import current_app, request

import segno

DEFAULT_QR_BASE_URL = "http://localhost:5000"

QR_PNG_DATA_URI_PREFIX = "data:image/png;base64,"


def qr_base_url():
    """Return the origin used to build join deep-links.

    Prefer an explicitly-configured QR_BASE_URL (e.g. a production domain).
    Otherwise fall back to the origin the current request actually arrived on,
    so the QR works regardless of how the app is published (localhost, a
    Cloudflare Tunnel hostname, or a custom domain). Never return an empty
    origin — the frontend/players must have somewhere to land.
    """
    override = current_app.config.get("QR_BASE_URL")
    if override and override.startswith(("http://", "https://")):
        return override.rstrip("/")
    # Reconstruct the public origin, respecting proxy headers set by
    # Cloudflare Tunnel / reverse proxies (https scheme + public host).
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host") or request.host
    origin = "{}://{}".format(scheme, host)
    return origin.rstrip("/") or DEFAULT_QR_BASE_URL


def game_qr_payload(game, base_url=None):
    """Safe deep-link used to join a game. Contains only the public game code."""
    return "{}/join/game/{}".format(base_url or qr_base_url(), game.game_code)


def team_qr_payload(team, base_url=None):
    """Safe deep-link used to join a team. Contains only public team/game codes."""
    return "{}/join/team/{}?game={}".format(
        base_url or qr_base_url(), team.team_code, team.game.game_code
    )


def qr_image_base64(payload, scale=4):
    qr = segno.make(payload)
    buffer = io.BytesIO()
    qr.save(buffer, kind="png", scale=scale)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def qr_data_uri(payload):
    return QR_PNG_DATA_URI_PREFIX + qr_image_base64(payload)