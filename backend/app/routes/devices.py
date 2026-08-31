from flask import Blueprint, request

from ..extensions import db
from ..services import team_service
from ..utils.rate_limit import rate_limit
from ..utils.response import error_response, success_response

devices_bp = Blueprint("devices", __name__, url_prefix="/api")


def _handle(exc):
    return error_response(str(exc), code=exc.code, status=exc.status)


def _body():
    return request.get_json(silent=True) or {}


@devices_bp.post("/devices/connect")
@rate_limit("devices_connect", limit=60, window_seconds=60)
def connect():
    body = _body()
    try:
        session = team_service.connect_device(
            connection_token=body.get("connection_token"),
            session_token=body.get("session_token"),
            device_id=body.get("device_id"),
        )
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(
        data=team_service.session_payload(session), status=201
    )


@devices_bp.post("/devices/heartbeat")
@rate_limit("devices_heartbeat", limit=120, window_seconds=60)
def heartbeat():
    body = _body()
    try:
        session = team_service.heartbeat(
            body.get("session_token"), device_id=body.get("device_id")
        )
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(
        data={
            "session_token": session.session_token,
            "last_heartbeat": session.last_heartbeat,
            "disconnected_at": session.disconnected_at,
        }
    )


@devices_bp.post("/devices/disconnect")
@rate_limit("devices_disconnect", limit=60, window_seconds=60)
def disconnect():
    body = _body()
    try:
        session = team_service.disconnect_device(
            body.get("session_token"), device_id=body.get("device_id")
        )
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(
        data={
            "session_token": session.session_token,
            "disconnected_at": session.disconnected_at,
        }
    )