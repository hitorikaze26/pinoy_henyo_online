from ..extensions import db


class Match(db.Model):
    __tablename__ = "matches"

    STATUS_PENDING = "PENDING"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_COMPLETED = "COMPLETED"
    STATUSES = (STATUS_PENDING, STATUS_ACTIVE, STATUS_COMPLETED)

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(
        db.Integer, db.ForeignKey("games.id"), nullable=False, index=True
    )
    round_id = db.Column(
        db.Integer, db.ForeignKey("rounds.id"), nullable=False, index=True
    )
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=True, index=True
    )
    match_order = db.Column(
        db.Integer, nullable=False, default=1, server_default=db.text("1")
    )
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id"), nullable=False, index=True
    )
    opponent_team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id"), nullable=True, index=True
    )
    winner_team_id = db.Column(
        db.Integer,
        db.ForeignKey("teams.id", name="fk_matches_winner_team"),
        nullable=True,
        index=True,
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default=STATUS_PENDING,
        server_default=STATUS_PENDING,
    )
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("round_id", "match_order", name="uq_matches_round_match_order"),
    )

    game = db.relationship(
        "Game", foreign_keys=[game_id], back_populates="matches"
    )
    round = db.relationship("Round", back_populates="matches")
    category = db.relationship("Category")
    team = db.relationship(
        "Team", foreign_keys=[team_id], back_populates="matches_as_team"
    )
    opponent_team = db.relationship(
        "Team", foreign_keys=[opponent_team_id], back_populates="matches_as_opponent"
    )
    winner_team = db.relationship(
        "Team", foreign_keys=[winner_team_id], post_update=True
    )
    turns = db.relationship(
        "Turn", back_populates="match", cascade="all, delete-orphan"
    )
    scores = db.relationship(
        "Score", back_populates="match", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return "<Match order={} round_id={} status={}>".format(
            self.match_order, self.round_id, self.status
        )