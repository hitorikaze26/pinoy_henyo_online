from ..extensions import db


class Round(db.Model):
    __tablename__ = "rounds"

    STATUS_PENDING = "PENDING"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_COMPLETED = "COMPLETED"
    STATUSES = (STATUS_PENDING, STATUS_ACTIVE, STATUS_COMPLETED)

    TIMER_MODE_COUNTDOWN = "COUNTDOWN"
    TIMER_MODE_COUNTUP = "COUNTUP"
    TIMER_MODES = (TIMER_MODE_COUNTDOWN, TIMER_MODE_COUNTUP)

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(
        db.Integer, db.ForeignKey("games.id"), nullable=False, index=True
    )
    round_number = db.Column(
        db.Integer, nullable=False, default=1, server_default=db.text("1")
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default=STATUS_PENDING,
        server_default=STATUS_PENDING,
    )
    timer_seconds = db.Column(
        db.Integer, nullable=False, default=60, server_default=db.text("60")
    )
    timer_mode = db.Column(
        db.String(20),
        nullable=False,
        default=TIMER_MODE_COUNTDOWN,
        server_default=TIMER_MODE_COUNTDOWN,
    )
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=db.text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        db.UniqueConstraint("game_id", "round_number", name="uq_rounds_game_round_number"),
    )

    game = db.relationship("Game", back_populates="rounds")
    matches = db.relationship(
        "Match", back_populates="round", cascade="all, delete-orphan"
    )
    selected_categories = db.relationship(
        "RoundCategory",
        back_populates="round",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return "<Round {} game_id={} status={}>".format(
            self.round_number, self.game_id, self.status
        )