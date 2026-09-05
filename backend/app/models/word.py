from ..extensions import db
from ..utils.time import utcnow


class Word(db.Model):
    __tablename__ = "words"

    STATUS_AVAILABLE = "AVAILABLE"
    STATUS_SELECTED = "SELECTED"
    STATUS_USED = "USED"
    STATUS_PASSED = "PASSED"
    STATUS_DISABLED = "DISABLED"
    STATUSES = (STATUS_AVAILABLE, STATUS_SELECTED, STATUS_USED, STATUS_PASSED, STATUS_DISABLED)

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(
        db.Integer, db.ForeignKey("games.id"), nullable=False, index=True
    )
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=True, index=True
    )
    submitted_by_team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id"), nullable=True, index=True
    )
    word_text = db.Column(db.String(100), nullable=False)
    normalized_word = db.Column(db.String(100), nullable=False, index=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default=STATUS_AVAILABLE,
        server_default=STATUS_AVAILABLE,
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
        db.Index("ix_words_game_status", "game_id", "status"),
        db.Index(
            "ix_words_game_category_normalized",
            "game_id",
            "category_id",
            "normalized_word",
            unique=True,
        ),
    )

    game = db.relationship("Game", back_populates="words")
    category = db.relationship("Category", back_populates="words")
    submitting_team = db.relationship("Team", back_populates="words")
    turn_words = db.relationship(
        "TurnWord", back_populates="word", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return "<Word {} status={}>".format(self.word_text, self.status)