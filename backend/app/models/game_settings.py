from ..extensions import db
from ..utils.time import utcnow


class GameSettings(db.Model):
    """Per-game gameplay + player-display configuration.

    One row per game (1:1 with ``games``). Gameplay rules served from here
    are the backend-authoritative values: the word-per-category cap, penalty
    step, team/member caps, connection behavior, and player display flags.
    Audio preferences are intentionally NOT stored here — they remain
    device-local (``pinoy_henyo_settings.audio.*``)."""

    __tablename__ = "game_settings"

    ALLOWED_MAX_WORDS_PER_CATEGORY = (3, 4, 5, 6, 8)
    ALLOWED_PENALTY_SECONDS = (0, 3, 5, 10)
    ALLOWED_MAX_TEAMS = (4, 6, 8, 10)
    ALLOWED_MAX_MEMBERS = (4, 6, 8)

    # Fields frozen once the game leaves LOBBY/SETUP (mirrors word_pool_locked).
    LOCKED_FIELDS = ("max_words_per_category", "max_teams", "max_members")

    game_id = db.Column(
        db.Integer, db.ForeignKey("games.id"), primary_key=True
    )
    max_words_per_category = db.Column(
        db.Integer,
        nullable=False,
        default=5,
        server_default="5",
    )
    penalty_seconds = db.Column(
        db.Integer,
        nullable=False,
        default=3,
        server_default="3",
    )
    allow_new_teams = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.text("true"),
    )
    auto_approve_connections = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.text("false"),
    )
    max_teams = db.Column(
        db.Integer,
        nullable=False,
        default=8,
        server_default="8",
    )
    max_members = db.Column(
        db.Integer,
        nullable=False,
        default=6,
        server_default="6",
    )
    show_player_names = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.text("true"),
    )
    show_role_labels = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.text("true"),
    )
    show_scores = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.text("true"),
    )
    show_qr_code = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.text("true"),
    )
    show_round_category = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.text("true"),
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

    game = db.relationship("Game", back_populates="settings", uselist=False)

    def __repr__(self):
        return "<GameSettings game_id={} max_words={}>".format(
            self.game_id, self.max_words_per_category
        )