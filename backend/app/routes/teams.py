from flask import Blueprint, request

from ..extensions import db, socketio
from ..models import DeviceSession, Team, TeamMember
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


def _ensure_joinable(game):
    """Return a player-facing 410 when the game has ended (terminal), so the
    connection/join path never surfaces the host-facing "read-only" mechanics
    message to players trying to connect."""
    from ..models.game import Game

    if game.status in (
        Game.STATUS_GAME_COMPLETE,
        Game.STATUS_CANCELLED,
        Game.STATUS_EXPIRED,
    ):
        return error_response(
            "That game has ended and is no longer accepting connections.",
            code="GAME_ENDED",
            status=410,
        )
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


def _creation_connection_status(game):
    """Teams always start NOT_CONNECTED regardless of creator.

    A team must never appear connected merely because it was created (or
    because the host created it). Even a host-created team's leader must go
    through the connection request + host approval flow before it is
    CONNECTED, matching the Part 5 contract.
    """
    return Team.CONNECTION_NOT_CONNECTED


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
            game,
            body.get("team_name"),
            body.get("username"),
            connection_status=_creation_connection_status(game),
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


@teams_bp.delete("/teams/<int:team_id>")
def delete_team(team_id):
    """Delete a team (host only, not connected)."""
    team, error = _team_or_404(team_id)
    if error is not None:
        return error
    token = host_token_from_request()
    if token is None or not host_authorized(team.game):
        return error_response(
            "Host token required.", code="UNAUTHORIZED", status=401
        )
    try:
        team_service.delete_team(team)
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(data={"team_id": team_id, "deleted": True})


@teams_bp.delete("/members/<int:member_id>")
def remove_member(member_id):
    """Remove a member from a team (host or team leader)."""
    member = db.session.get(TeamMember, member_id)
    if member is None:
        return error_response(
            "Member not found.", code="MEMBER_NOT_FOUND", status=404
        )
    token = host_token_from_request()
    is_host = token is not None and host_authorized(member.team.game)
    if not is_host:
        session_token = request.headers.get("X-Session-Token")
        if not gameplay_service.session_is_team_leader(member.team, session_token):
            return error_response(
                "Host token or team leader session required.",
                code="UNAUTHORIZED",
                status=401,
            )
    try:
        realtime.emit_member_left(member.team.game_id, member.team.id, member.id)
        team_service.remove_member(member)
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return success_response(
        data={"member_id": member_id, "deleted": True}
    )


@teams_bp.post("/games/<int:game_id>/join")
def join_game(game_id):
    body = request.get_json(silent=True) or {}
    game, error = _load_game(game_id)
    if error is not None:
        return error
    ended = _ensure_joinable(game)
    if ended is not None:
        return ended
    try:
        result = team_service.join_game(
            game,
            body.get("username"),
            team_name=body.get("team_name"),
            team_code=body.get("team_code"),
            connection_status=_creation_connection_status(game),
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


# ---------------------------------------------------------------------------
# Host connection / approval flow
# ---------------------------------------------------------------------------


def _leader_from_request(game):
    """Resolve the team leader making a request: prefer the X-Session-Token of
    a leader member of ``game``, else the leader connection_token in the body.
    Returns (member, error_response_or_None)."""
    session_token = request.headers.get("X-Session-Token")
    if session_token:
        session = DeviceSession.query.filter_by(
            game_id=game.id,
            session_token=session_token,
            disconnected_at=None,
        ).first()
        session_member = session.member if session is not None else None
        if session_member is not None and session_member.team_id is not None:
            if (
                session_member.device_role == TeamMember.DEVICE_ROLE_TEAM_LEADER
                and session_member.team.game_id == game.id
            ):
                return session_member, None
        body = request.get_json(silent=True) or {}
        has_body_token = bool(body.get("connection_token"))
        if session_member is not None and not has_body_token:
            return None, error_response(
                "Only the team leader can request connection.",
                code="NOT_TEAM_LEADER",
                status=403,
            )
    body = request.get_json(silent=True) or {}
    try:
        member = team_service.resolve_leader_by_connection_token(
            body.get("connection_token")
        )
    except team_service.TeamServiceError as exc:
        return None, _handle(exc)
    if member.team.game_id != game.id:
        return None, error_response(
            "This connection token belongs to another game.",
            code="CONNECTION_TOKEN_INVALID",
            status=404,
        )
    return member, None


@teams_bp.post("/games/<int:game_id>/connection-request")
def request_connection(game_id):
    body = request.get_json(silent=True) or {}
    game, error = _load_game(game_id)
    if error is not None:
        return error
    ended = _ensure_joinable(game)
    if ended is not None:
        return ended
    if body.get("connection_token") is None and not request.headers.get(
        "X-Session-Token"
    ):
        return error_response(
            "connection_token or a leader session is required.",
            code="CONNECTION_TOKEN_REQUIRED",
            status=400,
        )
    member, error = _leader_from_request(game)
    if error is not None:
        return error
    try:
        changed = team_service.request_connection(member)
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    team = member.team
    if changed and team.connection_status == Team.CONNECTION_CONNECTED:
        realtime.emit_connection_approved(team)
    else:
        realtime.emit_connection_requested(team, member=member)
    return success_response(
        data={
            "team_id": team.id,
            "connection_status": team.connection_status,
            "requested_now": changed,
        }
    )


def _host_decision_endpoint(game_id, team_id, action):
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
    team, error = _team_or_404(team_id)
    if error is not None:
        return error
    if team.game_id != game.id:
        return error_response(
            "Team does not belong to this game.",
            code="TEAM_NOT_IN_GAME",
            status=404,
        )
    try:
        changed = action(team)
        db.session.commit()
    except team_service.TeamServiceError as exc:
        db.session.rollback()
        return _handle(exc)
    return changed


@teams_bp.post("/games/<int:game_id>/connection-requests/<int:team_id>/approve")
def approve_connection(game_id, team_id):
    _changed = _host_decision_endpoint(
        game_id, team_id, team_service.approve_connection
    )
    if isinstance(_changed, tuple):
        return _changed
    team = team_service.get_team(team_id)
    realtime.emit_connection_approved(team)
    return success_response(
        data={
            "team_id": team.id,
            "connection_status": team.connection_status,
        }
    )


@teams_bp.post("/games/<int:game_id>/connection-requests/<int:team_id>/decline")
def decline_connection(game_id, team_id):
    _changed = _host_decision_endpoint(
        game_id, team_id, team_service.decline_connection
    )
    if isinstance(_changed, tuple):
        return _changed
    team = team_service.get_team(team_id)
    realtime.emit_connection_declined(team)
    return success_response(
        data={
            "team_id": team.id,
            "connection_status": team.connection_status,
        }
    )


@teams_bp.post("/games/<int:game_id>/connection-requests/<int:team_id>/disconnect")
def disconnect_connection(game_id, team_id):
    _changed = _host_decision_endpoint(
        game_id, team_id, team_service.disconnect_connection
    )
    if isinstance(_changed, tuple):
        return _changed
    team = team_service.get_team(team_id)
    realtime.emit_connection_disconnected(team)
    return success_response(
        data={
            "team_id": team.id,
            "connection_status": team.connection_status,
        }
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