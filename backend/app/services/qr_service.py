import base64
import io

from flask import current_app

import segno

DEFAULT_QR_BASE_URL = "https://pinoyhenyo.online"

QR_PNG_DATA_URI_PREFIX = "data:image/png;base64,"


def _base_url():
    return current_app.config.get("QR_BASE_URL", DEFAULT_QR_BASE_URL)


def game_qr_payload(game):
    """Safe deep-link used to join a game. Contains only the public game code."""
    return "{}/join/game/{}".format(_base_url(), game.game_code)


def team_qr_payload(team):
    """Safe deep-link used to join a team. Contains only public team/game codes."""
    return "{}/join/team/{}?game={}".format(
        _base_url(), team.team_code, team.game.game_code
    )


def qr_image_base64(payload, scale=4):
    qr = segno.make(payload)
    buffer = io.BytesIO()
    qr.save(buffer, kind="png", scale=scale)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def qr_data_uri(payload):
    return QR_PNG_DATA_URI_PREFIX + qr_image_base64(payload)