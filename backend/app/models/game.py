from ..extensions import db
from ..utils.time import utcnow


class Game(db.Model):
    __tablename__ = "games"

    STATUS_LOBBY = "LOBBY"
    STATUS_SETUP = "SETUP"
    STATUS_READY = "READY"
    STATUS_ROUND_1 = "ROUND_1"
    STATUS_ROUND_2 = "ROUND_2"
    STATUS_PAUSED = "PAUSED"
    STATUS_GAME_COMPLETE = "GAME_COMPLETE"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_EXPIRED = "EXPIRED"
    STATUS_TIE_BREAKER = "TIE_BREAKER"
    STATUSES = (
        STATUS_LOBBY,
        STATUS_SETUP,
        STATUS_READY,
        STATUS_ROUND_1,
        STATUS_ROUND_2,
        STATUS_PAUSED,
        STATUS_GAME_COMPLETE,
        STATUS_CANCELLED,
        STATUS_EXPIRED,
        STATUS_TIE_BREAKER,
    )

    id = db.Column(db.Integer, primary_key=True)
    game_code = db.Column(db.String(16), nullable=False, unique=True, index=True)
    host_session_token = db.Column(db.String(64), nullable=False, index=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default=STATUS_LOBBY,
        server_default=STATUS_LOBBY,
    )
    current_round = db.Column(db.Integer, nullable=True)
    # Updated whenever the host authenticates (REST) or opens/reconnects its
    # socket. Used by the maintenance sweeper to expire games whose host has
    # been absent for > HOST_INACTIVITY_TIMEOUT (host disconnect handling).
    host_last_seen_at = db.Column(db.DateTime, nullable=True, index=True)
    current_match_id = db.Column(
        db.Integer,
        db.ForeignKey("matches.id", name="fk_games_current_match", use_alter=True),
        nullable=True,
        index=True,
    )
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=db.text("CURRENT_TIMESTAMP")
    )
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.text("CURRENT_TIMESTAMP"),
        onupdate=utcnow,
    )

    current_match = db.relationship(
        "Match", foreign_keys=[current_match_id], post_update=True
    )
    matches = db.relationship(
        "Match",
        back_populates="game",
        foreign_keys="Match.game_id",
        cascade="all, delete-orphan",
    )
    teams = db.relationship(
        "Team", back_populates="game", cascade="all, delete-orphan"
    )
    categories = db.relationship(
        "Category", back_populates="game", cascade="all, delete-orphan"
    )
    words = db.relationship(
        "Word", back_populates="game", cascade="all, delete-orphan"
    )
    rounds = db.relationship(
        "Round", back_populates="game", cascade="all, delete-orphan"
    )
    device_sessions = db.relationship(
        "DeviceSession", back_populates="game", cascade="all, delete-orphan"
    )
    scores = db.relationship(
        "Score", back_populates="game", cascade="all, delete-orphan"
    )
    events = db.relationship(
        "GameEvent", back_populates="game", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return "<Game code={} status={}>".format(self.game_code, self.status)