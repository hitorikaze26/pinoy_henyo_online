import secrets
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import DeviceSession, Game, GameEvent, Match, Team, TeamMember, Word  # noqa: F401
from ..utils.codes import generate_team_code
from ..utils.time import utcnow

MAX_TEAM_CODE_ATTEMPTS = 10
MAX_USERNAME_LENGTH = 50
MAX_TEAM_NAME_LENGTH = 50


class TeamServiceError(Exception):
    status = 400
    code = "TEAM_SERVICE_ERROR"


class TeamNotFoundError(TeamServiceError):
    status = 404
    code = "TEAM_NOT_FOUND"


class TeamNameInvalidError(TeamServiceError):
    status = 400
    code = "TEAM_NAME_INVALID"


class UsernameInvalidError(TeamServiceError):
    status = 400
    code = "USERNAME_INVALID"


class TeamCodeInvalidError(TeamServiceError):
    status = 400
    code = "TEAM_CODE_INVALID"


class JoinParamsInvalidError(TeamServiceError):
    status = 400
    code = "JOIN_PARAMS_INVALID"


class ConnectionTokenRequiredError(TeamServiceError):
    status = 400
    code = "CONNECTION_TOKEN_REQUIRED"


class ConnectionTokenInvalidError(TeamServiceError):
    status = 404
    code = "CONNECTION_TOKEN_INVALID"


class DeviceIdRequiredError(TeamServiceError):
    status = 400
    code = "DEVICE_ID_REQUIRED"


class SessionTokenRequiredError(TeamServiceError):
    status = 400
    code = "SESSION_TOKEN_REQUIRED"


class SessionNotFoundError(TeamServiceError):
    status = 404
    code = "SESSION_NOT_FOUND"


class SessionDisconnectedError(TeamServiceError):
    status = 410
    code = "SESSION_DISCONNECTED"


class UnauthorizedDeviceError(TeamServiceError):
    status = 401
    code = "UNAUTHORIZED"


class NotTeamLeaderError(TeamServiceError):
    status = 403
    code = "NOT_TEAM_LEADER"


class ConnectionRequestInvalidError(TeamServiceError):
    status = 403
    code = "CONNECTION_REQUEST_INVALID"


class ConnectionAlreadyConnectedError(TeamServiceError):
    status = 409
    code = "ALREADY_CONNECTED"


class ConnectionRequestPendingError(TeamServiceError):
    status = 409
    code = "REQUEST_PENDING"


class NoPendingRequestError(TeamServiceError):
    status = 409
    code = "NO_PENDING_REQUEST"


class TeamDeleteBlockedMatchError(TeamServiceError):
    status = 409
    code = "TEAM_DELETE_BLOCKED_MATCH_REFERENCE"


def _record_event(game, event_type, data=None):
    db.session.add(
        GameEvent(game_id=game.id, event_type=event_type, event_data=data)
    )


def _validate_username(username):
    username = (str(username or "").strip()) if username is not None else ""
    if not username or len(username) > MAX_USERNAME_LENGTH:
        raise UsernameInvalidError(
            "Username must be 1-{} characters and not blank.".format(
                MAX_USERNAME_LENGTH
            )
        )
    return username


def _validate_team_name(team_name):
    team_name = (
        (str(team_name or "").strip()) if team_name is not None else ""
    )
    if not team_name or len(team_name) > MAX_TEAM_NAME_LENGTH:
        raise TeamNameInvalidError(
            "Team name must be 1-{} characters and not blank.".format(
                MAX_TEAM_NAME_LENGTH
            )
        )
    return team_name


def _generate_connection_token():
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Teams & members
# ---------------------------------------------------------------------------


def get_team(team_id):
    return db.session.get(Team, team_id)


def create_team(game, team_name, username, connection_status=None):
    team_name = _validate_team_name(team_name)
    username = _validate_username(username)
    if connection_status is None:
        connection_status = Team.CONNECTION_NOT_CONNECTED
    elif connection_status not in Team.CONNECTION_STATUSES:
        raise TeamServiceError("Invalid connection status.")
    for _ in range(MAX_TEAM_CODE_ATTEMPTS):
        team = Team(
            game_id=game.id,
            team_code=generate_team_code(),
            team_name=team_name,
            connection_status=connection_status,
        )
        db.session.add(team)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            continue

        leader = TeamMember(
            team_id=team.id,
            username=username,
            device_role=TeamMember.DEVICE_ROLE_TEAM_LEADER,
            connection_token=_generate_connection_token(),
        )
        db.session.add(leader)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            continue

        team.leader_member_id = leader.id
        db.session.flush()
        _record_event(
            game,
            "TEAM_CREATED",
            {"team_id": team.id, "team_code": team.team_code},
        )
        _record_event(
            game,
            "MEMBER_JOINED",
            {
                "team_id": team.id,
                "member_id": leader.id,
                "username": username,
                "device_role": leader.device_role,
            },
        )
        return team
    raise RuntimeError("Could not allocate a unique team code")


def update_team_name(team, team_name):
    team.team_name = _validate_team_name(team_name)
    _record_event(
        team.game,
        "TEAM_UPDATED",
        {"team_id": team.id, "team_name": team.team_name},
    )
    return team


def update_member_username(member, username):
    member.username = _validate_username(username)
    _record_event(
        member.team.game,
        "MEMBER_UPDATED",
        {
            "team_id": member.team_id,
            "member_id": member.id,
            "username": member.username,
        },
    )
    return member


def add_member(team, username):
    username = _validate_username(username)
    member = TeamMember(
        team_id=team.id,
        username=username,
        device_role=TeamMember.DEVICE_ROLE_TEAM_MEMBER,
        connection_token=_generate_connection_token(),
    )
    db.session.add(member)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise TeamServiceError("Could not create team member.")
    _record_event(
        team.game,
        "MEMBER_JOINED",
        {
            "team_id": team.id,
            "member_id": member.id,
            "username": username,
            "device_role": member.device_role,
        },
    )
    return member


def remove_member(member):
    """Remove a member from a team.

    The team leader cannot be removed (transfer leadership first).
    Disconnecting does not delete — use this only for explicit removal.
    """
    team = member.team
    if team.leader_member_id == member.id:
        raise NotTeamLeaderError(
            "Cannot remove the team leader. Transfer leadership first."
        )
    _record_event(
        team.game,
        "MEMBER_LEFT",
        {
            "team_id": team.id,
            "member_id": member.id,
            "username": member.username,
        },
    )
    # Keep historical events; detach their member FK so removal does not
    # violate the FK and does not destroy audit history.
    GameEvent.query.filter_by(member_id=member.id).update({"member_id": None})
    db.session.delete(member)


def delete_team(team):
    """Delete a team and cascade to its members, words, scores, etc.

    Connected teams should not be casually deleted during gameplay.
    """
    if team.connection_status == Team.CONNECTION_CONNECTED:
        raise TeamServiceError(
            "Cannot delete a connected team during gameplay. Disconnect first."
        )
    match_ref = Match.query.filter(
        (Match.team_id == team.id)
        | (Match.opponent_team_id == team.id)
        | (Match.winner_team_id == team.id)
    ).first()
    if match_ref is not None:
        raise TeamDeleteBlockedMatchError(
            "This team is part of a match and cannot be deleted."
        )
    game = team.game
    _record_event(
        game,
        "TEAM_DELETED",
        {"team_id": team.id, "team_code": team.team_code},
    )
    db.session.delete(team)


def join_game(game, username, team_name=None, team_code=None, connection_status=None):
    if team_name:
        team = create_team(game, team_name, username, connection_status=connection_status)
        return {"joined_as_member": False, "team": team}
    if team_code:
        team = Team.query.filter_by(
            game_id=game.id, team_code=team_code
        ).first()
        if team is None:
            raise TeamCodeInvalidError(
                "No team with this code exists in the game."
            )
        member = add_member(team, username)
        return {"joined_as_member": True, "team": team, "member": member}
    raise JoinParamsInvalidError(
        "Provide either team_name to create a team or team_code to join one."
    )


def join_team(team, username):
    return add_member(team, username)


def resolve_leader_by_connection_token(connection_token):
    """Resolve the team leader from a connection token, if valid."""
    if not connection_token:
        raise ConnectionTokenRequiredError("connection_token is required.")
    member = TeamMember.query.filter_by(
        connection_token=connection_token
    ).first()
    if member is None:
        raise ConnectionTokenInvalidError("Invalid connection token.")
    if member.device_role != TeamMember.DEVICE_ROLE_TEAM_LEADER:
        raise NotTeamLeaderError("Only the team leader can request connection.")
    return member


# ---------------------------------------------------------------------------
# Host connection (approval) state machine
# ---------------------------------------------------------------------------
# A team is created NOT_CONNECTED. The team leader must explicitly request a
# connection (scanning the host QR or entering the host code), and the host
# must approve it. The decision is team-scoped and stored in
# ``Team.connection_status``, independent of any single member's live socket.


def request_connection(member):
    """Transition a team to CONNECTION_REQUESTED (idempotent-request).

    Returns True if the state actually changed to REQUESTED; False if the
    request was already pending (no duplicate state machine rotation).
    """
    team = member.team
    if team.game is None:
        raise TeamServiceError("Team has no game.")
    if member.device_role != TeamMember.DEVICE_ROLE_TEAM_LEADER:
        raise NotTeamLeaderError("Only the team leader can request connection.")
    if team.connection_status == Team.CONNECTION_CONNECTED:
        raise ConnectionAlreadyConnectedError("This team is already connected.")
    if team.connection_status == Team.CONNECTION_REQUESTED:
        return False
    if team.connection_status in (
        Team.CONNECTION_NOT_CONNECTED,
        Team.CONNECTION_DECLINED,
        Team.CONNECTION_DISCONNECTED,
    ):
        team.connection_status = Team.CONNECTION_REQUESTED
        _record_event(
            team.game,
            "CONNECTION_REQUESTED",
            {
                "team_id": team.id,
                "member_id": member.id,
                "username": member.username,
            },
        )
        return True
    raise ConnectionRequestInvalidError(
        "Cannot request connection from this team state."
    )


def approve_connection(team, actor_member=None):
    """Host approves a pending request: REQUESTED -> CONNECTED.

    Idempotent if the team is already CONNECTED (double-click safe).
    """
    if team.connection_status == Team.CONNECTION_CONNECTED:
        return False
    if team.connection_status != Team.CONNECTION_REQUESTED:
        raise NoPendingRequestError("This team has no pending connection request.")
    team.connection_status = Team.CONNECTION_CONNECTED
    _record_event(
        team.game,
        "CONNECTION_APPROVED",
        {
            "team_id": team.id,
            "member_id": actor_member.id if actor_member is not None else None,
        },
    )
    return True


def decline_connection(team, actor_member=None):
    """Host declines a pending request: REQUESTED -> DECLINED."""
    if team.connection_status != Team.CONNECTION_REQUESTED:
        raise NoPendingRequestError("This team has no pending connection request.")
    team.connection_status = Team.CONNECTION_DECLINED
    _record_event(
        team.game,
        "CONNECTION_DECLINED",
        {
            "team_id": team.id,
            "member_id": actor_member.id if actor_member is not None else None,
        },
    )
    return True


def disconnect_connection(team, actor_member=None):
    """Host disconnects a connected (or pending) team: -> DISCONNECTED."""
    if team.connection_status in (
        Team.CONNECTION_NOT_CONNECTED,
        Team.CONNECTION_DISCONNECTED,
    ):
        return False
    team.connection_status = Team.CONNECTION_DISCONNECTED
    _record_event(
        team.game,
        "CONNECTION_DISCONNECTED",
        {
            "team_id": team.id,
            "member_id": actor_member.id if actor_member is not None else None,
        },
    )
    return True


# ---------------------------------------------------------------------------
# Device sessions
# ---------------------------------------------------------------------------


def _get_device_session(session_token):
    if not session_token:
        raise SessionTokenRequiredError("session_token is required.")
    session = DeviceSession.query.filter_by(
        session_token=session_token
    ).first()
    if session is None:
        raise SessionNotFoundError(
            "No device session found for this session token."
        )
    return session


def _deactivate_active_sessions(member_id, now):
    for session in DeviceSession.query.filter_by(
        member_id=member_id, disconnected_at=None
    ).all():
        session.disconnected_at = now


def _member_has_active_session(member_id):
    count = db.session.query(DeviceSession.id).filter(
        DeviceSession.member_id == member_id,
        DeviceSession.disconnected_at.is_(None),
    ).count()
    return count > 0


def connect_device(connection_token=None, session_token=None, device_id=None):
    now = utcnow()
    if not device_id:
        raise DeviceIdRequiredError("device_id is required.")

    if connection_token:
        # A fresh connection token (create/join/add-member) is authoritative:
        # the device is always bound to THAT member/team/game. A stale
        # session_token forwarded by an older client is superseded instead of
        # being reused, so a new team is never orphaned behind the previous
        # game/team session.
        member = TeamMember.query.filter_by(
            connection_token=connection_token
        ).first()
        if member is None:
            raise ConnectionTokenInvalidError(
                "Invalid connection token."
            )
        team = member.team
        if session_token:
            stale = _get_device_session(session_token)
            if stale.device_id != device_id:
                raise UnauthorizedDeviceError(
                    "This session belongs to a different device."
                )
            stale.disconnected_at = now
            stale_member = stale.member
            if (
                stale_member is not None
                and not _member_has_active_session(stale_member.id)
            ):
                stale_member.is_connected = False
        _deactivate_active_sessions(member.id, now)
        device_type = (
            DeviceSession.DEVICE_TYPE_TEAM_LEADER
            if member.device_role == TeamMember.DEVICE_ROLE_TEAM_LEADER
            else DeviceSession.DEVICE_TYPE_TEAM_MEMBER
        )
        session = DeviceSession(
            game_id=team.game_id,
            team_id=team.id,
            member_id=member.id,
            device_id=device_id,
            session_token=secrets.token_urlsafe(32),
            device_type=device_type,
            connected_at=now,
            last_heartbeat=now,
        )
        db.session.add(session)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            raise TeamServiceError("Could not establish a device session.")
        member.is_connected = True
        member.last_seen_at = now
        _record_event(
            team.game,
            "DEVICE_CONNECTED",
            {
                "session_id": session.id,
                "game_id": team.game_id,
                "team_id": team.id,
                "member_id": member.id,
                "device_type": device_type,
            },
        )
        return session

    if session_token:
        session = _get_device_session(session_token)
        if session.device_id != device_id:
            raise UnauthorizedDeviceError(
                "This session belongs to a different device."
            )
        session.disconnected_at = None
        session.last_heartbeat = now
        member = session.member
        if member is not None:
            member.is_connected = True
            member.last_seen_at = now
        return session

    raise ConnectionTokenRequiredError(
        "Either connection_token or session_token is required."
    )


def heartbeat(session_token, device_id=None):
    now = utcnow()
    session = _get_device_session(session_token)
    if device_id and session.device_id != device_id:
        raise UnauthorizedDeviceError(
            "This session belongs to a different device."
        )
    if session.disconnected_at is not None:
        raise SessionDisconnectedError(
            "This session is disconnected. Reconnect to continue."
        )
    session.last_heartbeat = now
    member = session.member
    if member is not None:
        member.is_connected = True
        member.last_seen_at = now
    return session


def disconnect_device(session_token, device_id=None):
    now = utcnow()
    session = _get_device_session(session_token)
    if device_id and session.device_id != device_id:
        raise UnauthorizedDeviceError(
            "This session belongs to a different device."
        )
    if session.disconnected_at is None:
        session.disconnected_at = now
        _record_event(
            session.game,
            "DEVICE_DISCONNECTED",
            {
                "session_id": session.id,
                "game_id": session.game_id,
                "team_id": session.team_id,
                "member_id": session.member_id,
            },
        )
    member = session.member
    if member is not None and not _member_has_active_session(member.id):
        member.is_connected = False
    return session


def expire_stale_sessions(timeout_seconds):
    """Mark device sessions that missed their heartbeat as disconnected.

    Returns a list of ``(game_id, team_id, member_id)`` tuples describing each
    member whose presence flipped to offline, so callers can fan out realtime
    disconnect events after committing.
    """
    cutoff = utcnow() - timedelta(seconds=timeout_seconds)
    stale = DeviceSession.query.filter(
        DeviceSession.disconnected_at.is_(None),
        DeviceSession.last_heartbeat < cutoff,
    ).all()
    now = utcnow()
    disconnected_members = {}
    for session in stale:
        session.disconnected_at = now
        member = session.member
        if member is None or _member_has_active_session(member.id):
            continue
        member.is_connected = False
        if member.id not in disconnected_members:
            disconnected_members[member.id] = (
                session.game_id,
                session.team_id,
                member.id,
            )
    return list(disconnected_members.values())


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


def team_payload(team, include_leader=False):
    data = {
        "team_id": team.id,
        "team_code": team.team_code,
        "team_name": team.team_name,
        "team_status": team.status,
        "connection_status": team.connection_status,
    }
    if include_leader:
        data["leader"] = member_payload(team.leader) if team.leader else None
    return data


def member_payload(member):
    return {
        "member_id": member.id,
        "team_id": member.team_id,
        "username": member.username,
        "device_role": member.device_role,
        "gameplay_role": member.gameplay_role,
        "connection_token": member.connection_token,
        "is_connected": member.is_connected,
    }


def team_roster_payload(team):
    """Full team payload with its member roster (for the host teams page)."""
    return {
        "team_id": team.id,
        "team_code": team.team_code,
        "team_name": team.team_name,
        "team_status": team.status,
        "connection_status": team.connection_status,
        "leader": (member_payload(team.leader) if team.leader else None),
        "members": sorted(
            [member_payload(m) for m in team.members],
            key=lambda p: p["member_id"],
        ),
    }


def list_teams_for_game(game):
    """Return the real roster payload for every team in a game."""
    teams = sorted(game.teams, key=lambda t: t.id)
    return [team_roster_payload(t) for t in teams]



def session_payload(session):
    return {
        "session_token": session.session_token,
        "game_id": session.game_id,
        "team_id": session.team_id,
        "member_id": session.member_id,
        "device_id": session.device_id,
        "device_type": session.device_type,
        "connected_at": session.connected_at,
        "last_heartbeat": session.last_heartbeat,
        "disconnected_at": session.disconnected_at,
    }