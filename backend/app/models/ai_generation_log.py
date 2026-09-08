from ..extensions import db
from ..utils.time import utcnow


class AIGenerationLog(db.Model):
    """Audit trail for every AI word-suggestion request (success or failure).

    One row per generation call. Purely additive — rows never affect gameplay
    and are written best-effort (a logging hiccup must never block the actual
    generation response). Category/team FKs are ``SET NULL`` on delete so the
    snapshot columns (``category_name``) keep working for analytics even after
    cleanup, matching the game-event history convention.
    """

    __tablename__ = "ai_generation_logs"

    ACTOR_HOST = "HOST"
    ACTOR_TEAM = "TEAM"
    ACTOR_TYPES = (ACTOR_HOST, ACTOR_TEAM)

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(
        db.Integer, db.ForeignKey("games.id"), nullable=False, index=True
    )
    actor_type = db.Column(db.String(10), nullable=False)
    actor_team_id = db.Column(
        db.Integer,
        db.ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Snapshot so category names survive category deletion for analytics.
    category_name = db.Column(db.String(50), nullable=False)
    language = db.Column(db.String(10), nullable=True)
    requested_count = db.Column(db.Integer, nullable=False)
    accepted_count = db.Column(db.Integer, nullable=False)
    success = db.Column(db.Boolean, nullable=False)
    error_code = db.Column(db.String(50), nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=db.text("CURRENT_TIMESTAMP")
    )

    game = db.relationship("Game", back_populates="ai_generation_logs")
    actor_team = db.relationship("Team", foreign_keys=[actor_team_id])
    category = db.relationship("Category", foreign_keys=[category_id])

    def __repr__(self):
        return "<AIGenerationLog {} game_id={} success={}>".format(
            self.id, self.game_id, self.success
        )