from flask import Blueprint, request

from ..extensions import db, socketio
from ..models import DeviceSession, TeamMember
from ..services import gameplay_service, qr_service, realtime, team_service
from ..services.game_service import get_game
from ..utils.auth import host_authorized, host_token_from_request
from ..utils.response import error_response, success_response

teams_bp = Blueprint("teams", __name__, url_prefix="/api")


def _load_game(game_id):
    game = get_game(game_id)
    if game is None:
        return None, error_response(
            "Game not found.", code="GAME_NOT_FOUND", status=404
        )
    return game, None


def _handle(exc):
    return error_response(str(exc), code=exc.code, status=exc.status)


def _team_or_404(team_id):
    team = team_service.get_team(team_id)
    if team is None:
        return None, error_response(
            "Team not found.", code="TEAM_NOT_FOUND", status=404
        )
    return team, None


def _ensure_mutable(game):
    from ..services.game_service import GameFrozenError, assert_game_mutable

    try:
        assert_game_mutable(game)
    except GameFrozenError as exc:
        return error_response(str(exc), code=exc.code, status=exc.status)
    return None


def _join_result_payload(result):
    if result["joined_as_member"]:
        return team_service.member_payload(result["member"])
    return team_service.team_payload(
        result["team"], include_leader=True
    )


def _session_member_for_team(team):
    """Return the active member of ``team`` whose session is presented in the
    request, or None if no valid session for that team is present."""
    session_token = request.headers.get("X-Session-Token")
    if not session_token:
        return None
    session = DeviceSession.query.filter_by(
        game_id=team.game_id,
        session_token=session_token,
        disconnected_at=None,
    ).first()
    if session is None or session.team_id != team.id or session.member_id is None:
        return None
    return session.member


@teams_bp.post("/games/<int:game_id>/teams")
def create_team(game_id):
    body = request.get_json(silent=True) or {}
    game, error = _load_game(game_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(game)
    if frozen is not None:
        return frozen
    try:
        team = team_service.create_team(
            game, body.get("team_name"), body.get("username")
        )
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    if team.leader is not None:
        realtime.emit_member_joined(team, team.leader)
    return success_response(
        data=team_service.team_payload(team, include_leader=True), status=201
    )


@teams_bp.get("/games/<int:game_id>/teams")
def list_teams(game_id):
    game, error = _load_game(game_id)
    if error is not None:
        return error
    token = host_token_from_request()
    if token is None or not host_authorized(game):
        return error_response(
            "Invalid or missing host session token.",
            code="UNAUTHORIZED",
            status=401,
        )
    return success_response(data={"teams": team_service.list_teams_for_game(game)})


@teams_bp.post("/teams/<int:team_id>/members")
def add_member(team_id):
    body = request.get_json(silent=True) or {}
    team, error = _team_or_404(team_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(team.game)
    if frozen is not None:
        return frozen
    try:
        member = team_service.add_member(team, body.get("username"))
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    realtime.emit_member_joined(team, member)
    return success_response(
        data=team_service.member_payload(member), status=201
    )


@teams_bp.get("/teams/<int:team_id>")
def get_team(team_id):
    team, error = _team_or_404(team_id)
    if error is not None:
        return error
    # Allow: host token OR an active session whose member belongs to this team.
    token = host_token_from_request()
    is_host = token is not None and host_authorized(team.game)
    member = None if is_host else _session_member_for_team(team)
    if not is_host and member is None:
        return error_response(
            "Host token or a session for this team is required.",
            code="UNAUTHORIZED",
            status=401,
        )
    payload = team_service.team_roster_payload(team)
    payload["my_member_id"] = member.id if member is not None else None
    return success_response(data=payload)


@teams_bp.patch("/teams/<int:team_id>")
def update_team(team_id):
    body = request.get_json(silent=True) or {}
    team, error = _team_or_404(team_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(team.game)
    if frozen is not None:
        return frozen
    token = host_token_from_request()
    is_host = token is not None and host_authorized(team.game)
    if not is_host:
        session_token = request.headers.get("X-Session-Token")
        if not gameplay_service.session_is_team_leader(team, session_token):
            return error_response(
                "Host token or team leader session required.",
                code="UNAUTHORIZED",
                status=401,
            )
    try:
        team = team_service.update_team_name(team, body.get("team_name"))
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    realtime.emit_team_updated(team)
    return success_response(data=team_service.team_payload(team))


@teams_bp.patch("/members/<int:member_id>")
def update_member(member_id):
    body = request.get_json(silent=True) or {}
    member = db.session.get(TeamMember, member_id)
    if member is None:
        return error_response(
            "Member not found.", code="MEMBER_NOT_FOUND", status=404
        )
    frozen = _ensure_mutable(member.team.game)
    if frozen is not None:
        return frozen
    token = host_token_from_request()
    is_host = token is not None and host_authorized(member.team.game)
    if not is_host:
        session_member = _session_member_for_team(member.team)
        if session_member is None or session_member.id != member.id:
            return error_response(
                "Host token or the member's own session is required.",
                code="UNAUTHORIZED",
                status=401,
            )
    try:
        member = team_service.update_member_username(
            member, body.get("username")
        )
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    realtime.emit_member_updated(member.team, member)
    return success_response(data=team_service.member_payload(member))


@teams_bp.post("/games/<int:game_id>/join")
def join_game(game_id):
    body = request.get_json(silent=True) or {}
    game, error = _load_game(game_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(game)
    if frozen is not None:
        return frozen
    try:
        result = team_service.join_game(
            game,
            body.get("username"),
            team_name=body.get("team_name"),
            team_code=body.get("team_code"),
        )
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    member = result.get("member")
    if member is None:
        member = result.get("team").leader if result.get("team") else None
    if member is not None:
        realtime.emit_member_joined(member.team, member)
    return success_response(data=_join_result_payload(result), status=201)


@teams_bp.post("/teams/<int:team_id>/join")
def join_team(team_id):
    body = request.get_json(silent=True) or {}
    team, error = _team_or_404(team_id)
    if error is not None:
        return error
    frozen = _ensure_mutable(team.game)
    if frozen is not None:
        return frozen
    try:
        member = team_service.join_team(team, body.get("username"))
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    realtime.emit_member_joined(team, member)
    return success_response(
        data=team_service.member_payload(member), status=201
    )


@teams_bp.post("/teams/<int:team_id>/roles")
def assign_roles(team_id):
    body = request.get_json(silent=True) or {}
    team, error = _team_or_404(team_id)
    if error is not None:
        return error
    token = host_token_from_request()
    if token is None or not host_authorized(team.game):
        session_token = request.headers.get("X-Session-Token")
        if not gameplay_service.session_is_team_leader(team, session_token):
            return error_response(
                "Host token or team leader session required.",
                code="UNAUTHORIZED",
                status=401,
            )
    frozen = _ensure_mutable(team.game)
    if frozen is not None:
        return frozen
    for entry in body.get("roles") or []:
        if not isinstance(entry, dict) or "member_id" not in entry:
            return error_response(
                "Each role entry must include member_id.",
                code="ROLE_INVALID",
                status=400,
            )
        try:
            gameplay_service.assign_member_role(
                team.game,
                team,
                entry["member_id"],
                entry.get("gameplay_role"),
            )
        except gameplay_service.GameplayServiceError as exc:
            db.session.rollback()
            return _handle(exc)
    db.session.commit()
    for entry in body.get("roles") or []:
        member = db.session.get(TeamMember, entry.get("member_id"))
        if member is None:
            continue
        realtime.emit_role_updated(team, member)
        _sync_manghuhula_room(member)
    return success_response(
        data=team_service.team_payload(team, include_leader=True)
    )


def _sync_manghuhula_room(member):
    target = (
        realtime.manghuhula_room(member.team_id)
        if member.gameplay_role == TeamMember.GAMEPLAY_ROLE_MANGHUHULA
        else None
    )
    for sid, peer in list(realtime.SOCKET_PEERS.items()):
        if peer.get("member_id") != member.id:
            continue
        try:
            socketio.server.leave_room(sid, realtime.manghuhula_room(member.team_id))
        except (KeyError, ValueError):
            continue
        if target is not None:
            try:
                socketio.server.enter_room(sid, target)
            except (KeyError, ValueError):
                continue


@teams_bp.get("/games/<int:game_id>/qr")
def game_qr(game_id):
    game, error = _load_game(game_id)
    if error is not None:
        return error
    token = host_token_from_request()
    if token is None or not host_authorized(game):
        return error_response(
            "Invalid or missing host session token.",
            code="UNAUTHORIZED",
            status=401,
        )
    payload = qr_service.game_qr_payload(game)
    return success_response(
        data={"payload": payload, "qr_image": qr_service.qr_data_uri(payload)}
    )


@teams_bp.get("/teams/<int:team_id>/qr")
def team_qr(team_id):
    team, error = _team_or_404(team_id)
    if error is not None:
        return error
    # Allow: host token OR team-leader session for the owning team.
    token = host_token_from_request()
    is_host = token is not None and host_authorized(team.game)
    session_token = request.headers.get("X-Session-Token")
    is_leader = gameplay_service.session_is_team_leader(team, session_token)
    if not is_host and not is_leader:
        return error_response(
            "Host token or team leader session required.",
            code="UNAUTHORIZED",
            status=401,
        )
    payload = qr_service.team_qr_payload(team)
    return success_response(
        data={"payload": payload, "qr_image": qr_service.qr_data_uri(payload)}
    )