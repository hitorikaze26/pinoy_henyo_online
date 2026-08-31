from ..extensions import db
from ..utils.time import utcnow


class Score(db.Model):
    __tablename__ = "scores"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(
        db.Integer, db.ForeignKey("games.id"), nullable=False, index=True
    )
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id"), nullable=False, index=True
    )
    round_id = db.Column(
        db.Integer, db.ForeignKey("rounds.id"), nullable=True, index=True
    )
    match_id = db.Column(
        db.Integer, db.ForeignKey("matches.id"), nullable=True, index=True
    )
    points = db.Column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    correct_words = db.Column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    passed_words = db.Column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    failed_words = db.Column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    penalty_seconds = db.Column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    time_bonus_seconds = db.Column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
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

    game = db.relationship("Game", back_populates="scores")
    team = db.relationship("Team", back_populates="scores")
    round = db.relationship("Round")
    match = db.relationship("Match", back_populates="scores")

    def __repr__(self):
        return "<Score points={} game_id={}>".format(self.points, self.game_id)