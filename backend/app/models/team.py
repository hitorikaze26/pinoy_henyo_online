from ..extensions import db
from ..utils.time import utcnow


class Team(db.Model):
    __tablename__ = "teams"

    STATUS_ACTIVE = "ACTIVE"
    STATUS_ELIMINATED = "ELIMINATED"
    STATUSES = (STATUS_ACTIVE, STATUS_ELIMINATED)

    # Host-connection state of the team (distinct from gameplay ``status``).
    # A team is created as NOT_CONNECTED; the team leader requests connection,
    # and the host must approve it before gameplay can begin.
    CONNECTION_NOT_CONNECTED = "NOT_CONNECTED"
    CONNECTION_REQUESTED = "CONNECTION_REQUESTED"
    CONNECTION_CONNECTED = "CONNECTED"
    CONNECTION_DECLINED = "DECLINED"
    CONNECTION_DISCONNECTED = "DISCONNECTED"
    CONNECTION_STATUSES = (
        CONNECTION_NOT_CONNECTED,
        CONNECTION_REQUESTED,
        CONNECTION_CONNECTED,
        CONNECTION_DECLINED,
        CONNECTION_DISCONNECTED,
    )

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(
        db.Integer, db.ForeignKey("games.id"), nullable=False, index=True
    )
    team_code = db.Column(db.String(16), nullable=False)
    team_name = db.Column(db.String(50), nullable=False)
    leader_member_id = db.Column(
        db.Integer,
        db.ForeignKey("team_members.id", name="fk_teams_leader_member", use_alter=True),
        nullable=True,
        index=True,
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default=STATUS_ACTIVE,
        server_default=STATUS_ACTIVE,
    )
    connection_status = db.Column(
        db.String(24),
        nullable=False,
        default=CONNECTION_NOT_CONNECTED,
        server_default=CONNECTION_NOT_CONNECTED,
        index=True,
    )
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=db.text("CURRENT_TIMESTAMP")
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.text("CURRENT_TIMESTAMP"),
        onupdate=utcnow,
    )

    __table_args__ = (
        db.UniqueConstraint("game_id", "team_code", name="uq_teams_game_team_code"),
    )

    game = db.relationship("Game", back_populates="teams")
    leader = db.relationship(
        "TeamMember", foreign_keys=[leader_member_id], post_update=True
    )
    members = db.relationship(
        "TeamMember",
        foreign_keys="TeamMember.team_id",
        back_populates="team",
        cascade="all, delete-orphan",
    )
    words = db.relationship(
        "Word", back_populates="submitting_team", cascade="all, delete-orphan"
    )
    device_sessions = db.relationship(
        "DeviceSession", back_populates="team", cascade="all, delete-orphan"
    )
    scores = db.relationship(
        "Score", back_populates="team", cascade="all, delete-orphan"
    )
    penalties = db.relationship(
        "Penalty", back_populates="team", cascade="all, delete-orphan"
    )
    matches_as_team = db.relationship(
        "Match",
        foreign_keys="Match.team_id",
        back_populates="team",
        cascade="all, delete-orphan",
    )
    matches_as_opponent = db.relationship(
        "Match",
        foreign_keys="Match.opponent_team_id",
        back_populates="opponent_team",
    )

    def __repr__(self):
        return "<Team {} game_id={}>".format(self.team_code, self.game_id)


class TeamMember(db.Model):
    __tablename__ = "team_members"

    DEVICE_ROLE_TEAM_LEADER = "TEAM_LEADER"
    DEVICE_ROLE_TEAM_MEMBER = "TEAM_MEMBER"
    DEVICE_ROLES = (DEVICE_ROLE_TEAM_LEADER, DEVICE_ROLE_TEAM_MEMBER)

    GAMEPLAY_ROLE_MANGHUHULA = "MANGHUHULA"
    GAMEPLAY_ROLE_TAGASAGOT = "TAGASAGOT"
    GAMEPLAY_ROLES = (GAMEPLAY_ROLE_MANGHUHULA, GAMEPLAY_ROLE_TAGASAGOT)

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id"), nullable=False, index=True
    )
    username = db.Column(db.String(50), nullable=False)
    device_role = db.Column(db.String(20), nullable=False)
    gameplay_role = db.Column(db.String(20), nullable=True)
    is_connected = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.text("false")
    )
    connection_token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=db.text("CURRENT_TIMESTAMP")
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.text("CURRENT_TIMESTAMP"),
        onupdate=utcnow,
    )
    last_seen_at = db.Column(db.DateTime, nullable=True)

    team = db.relationship(
        "Team", foreign_keys=[team_id], back_populates="members"
    )
    device_sessions = db.relationship(
        "DeviceSession", back_populates="member", cascade="all, delete-orphan"
    )
    events = db.relationship("GameEvent", back_populates="member")

    def __repr__(self):
        return "<TeamMember {} team_id={}>".format(self.username, self.team_id)