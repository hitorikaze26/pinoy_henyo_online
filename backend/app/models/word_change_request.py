from ..extensions import db


class WordChangeRequest(db.Model):
    __tablename__ = "word_change_requests"

    STATUS_PENDING = "PENDING"
    STATUS_RESOLVED = "RESOLVED"
    STATUS_CANCELLED = "CANCELLED"
    STATUSES = (STATUS_PENDING, STATUS_RESOLVED, STATUS_CANCELLED)

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(
        db.Integer, db.ForeignKey("games.id"), nullable=False, index=True
    )
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id"), nullable=True, index=True
    )
    word_id = db.Column(
        db.Integer, db.ForeignKey("words.id"), nullable=True, index=True
    )
    comment = db.Column(db.String(300), nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default=STATUS_PENDING,
        server_default=STATUS_PENDING,
    )
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=db.text("CURRENT_TIMESTAMP")
    )
    resolved_at = db.Column(db.DateTime, nullable=True)

    requesting_team = db.relationship("Team")
    target_word = db.relationship("Word")
    game = db.relationship("Game")

    def __repr__(self):
        return "<WordChangeRequest id={} status={} word_id={}>".format(
            self.id, self.status, self.word_id
        )