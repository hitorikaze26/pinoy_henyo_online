from flask import request

from ..extensions import db, socketio
from ..models import DeviceSession, Game, TeamMember, Turn
from ..services import realtime
from ..utils.time import utcnow


USER_AUTH_REFUSED = "USER_AUTH_REFUSED"


def _token_from_auth(auth):
    if isinstance(auth, dict) and auth.get("token"):
        return auth["token"]
    return request.args.get("token")


def _device_id_from_request():
    return request.args.get("device_id")


def _send_error(sid, code, message):
    socketio.emit("error", {"code": code, "message": message}, to=sid)


def handle_connect(auth=None):
    token = _token_from_auth(auth)
    if not token:
        raise ConnectionRefusedError(USER_AUTH_REFUSED)

    game = Game.query.filter_by(host_session_token=token).first()
    if game is not None:
        if game.status == Game.STATUS_CANCELLED:
            raise ConnectionRefusedError(USER_AUTH_REFUSED)
        game.host_last_seen_at = utcnow()
        db.session.commit()
        realtime.register_peer(
            request.sid,
            role="HOST",
            game_id=game.id,
            session_token=token,
        )
        socketio.server.enter_room(request.sid, realtime.game_room(game.id))
        return

    session = DeviceSession.query.filter_by(session_token=token).first()
    if session is None:
        raise ConnectionRefusedError(USER_AUTH_REFUSED)
    member = session.member
    if member is None or member.team_id is None:
        raise ConnectionRefusedError(USER_AUTH_REFUSED)
    if session.game is None or session.game.status == Game.STATUS_CANCELLED:
        raise ConnectionRefusedError(USER_AUTH_REFUSED)

    expected_device_id = _device_id_from_request()
    if expected_device_id is not None and session.device_id != expected_device_id:
        raise ConnectionRefusedError(USER_AUTH_REFUSED)

    if member.device_role == TeamMember.DEVICE_ROLE_TEAM_LEADER:
        role = TeamMember.DEVICE_ROLE_TEAM_LEADER
    else:
        role = TeamMember.DEVICE_ROLE_TEAM_MEMBER

    now = utcnow()
    session.disconnected_at = None
    session.last_heartbeat = now
    member.is_connected = True
    member.last_seen_at = now
    db.session.commit()

    team = session.team
    realtime.register_peer(
        request.sid,
        role=role,
        game_id=session.game_id,
        team_id=team.id,
        member_id=member.id,
        session_token=token,
        device_type=session.device_type,
    )
    socketio.server.enter_room(request.sid, realtime.game_room(session.game_id))
    socketio.server.enter_room(request.sid, realtime.team_room(team.id))
    socketio.server.enter_room(request.sid, realtime.member_room(member.id))
    if member.gameplay_role == TeamMember.GAMEPLAY_ROLE_MANGHUHULA:
        socketio.server.enter_room(request.sid, realtime.manghuhula_room(team.id))
    realtime.emit_team_connected(team, member, session.device_type, skip_sid=request.sid)


def handle_disconnect():
    peer = realtime.pick_peer(request.sid)
    if peer is None:
        return
    game_id = peer.get("game_id")
    team_id = peer.get("team_id")
    member_id = peer.get("member_id")
    session_token = peer.get("session_token")

    if team_id is not None:
        session = None
        if session_token:
            session = DeviceSession.query.filter_by(session_token=session_token).first()
        if session is not None:
            session.disconnected_at = utcnow()
            session.last_heartbeat = utcnow()
        if member_id is not None:
            member = db.session.get(TeamMember, member_id)
            if member is not None:
                member.last_seen_at = utcnow()
        remaining = DeviceSession.query.filter_by(
            member_id=member_id, disconnected_at=None
        ).count()
        if remaining == 0:
            if member is not None:
                member.is_connected = False
        db.session.commit()
        realtime.emit_team_disconnected(game_id, team_id, member_id)
    realtime.drop_peer(request.sid)


def handle_join_turn(turn_id):
    peer = realtime.pick_peer(request.sid)
    turn = db.session.get(Turn, turn_id) if turn_id is not None else None
    if turn is None:
        _send_error(request.sid, "TURN_NOT_FOUND", "Turn not found.")
        return
    if not realtime.can_join_turn(peer, turn):
        _send_error(request.sid, "FORBIDDEN", "You cannot join this turn room.")
        return
    socketio.server.enter_room(request.sid, realtime.turn_room(turn.id))
    realtime.emit_turn_state_to(request.sid, turn)


def handle_leave_turn(turn_id):
    if turn_id is None:
        return
    socketio.server.leave_room(request.sid, realtime.turn_room(turn_id))


def register():
    socketio.on("connect")(handle_connect)
    socketio.on("disconnect")(handle_disconnect)
    socketio.on("join_turn")(handle_join_turn)
    socketio.on("leave_turn")(handle_leave_turn)