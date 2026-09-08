from ..extensions import db


class Turn(db.Model):
    __tablename__ = "turns"

    STATUS_WAITING = "WAITING"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_PAUSED = "PAUSED"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_TIMEOUT = "TIMEOUT"
    STATUS_FAILED = "FAILED"
    STATUSES = (
        STATUS_WAITING,
        STATUS_ACTIVE,
        STATUS_PAUSED,
        STATUS_COMPLETED,
        STATUS_TIMEOUT,
        STATUS_FAILED,
    )

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(
        db.Integer, db.ForeignKey("matches.id"), nullable=False, index=True
    )
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id"), nullable=False, index=True
    )
    round_id = db.Column(
        db.Integer, db.ForeignKey("rounds.id"), nullable=False, index=True
    )
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=True, index=True
    )
    turn_order = db.Column(
        db.Integer, nullable=False, default=1, server_default=db.text("1")
    )
    current_word_id = db.Column(
        db.Integer, db.ForeignKey("words.id"), nullable=True, index=True
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default=STATUS_WAITING,
        server_default=STATUS_WAITING,
    )
    starting_seconds = db.Column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    remaining_seconds = db.Column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    paused_at = db.Column(db.DateTime, nullable=True)
    pause_total_seconds = db.Column(
        db.Float, nullable=False, default=0, server_default=db.text("0")
    )
    timer_adjustment_seconds = db.Column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=db.text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        db.UniqueConstraint("match_id", "turn_order", name="uq_turns_match_turn_order"),
    )

    match = db.relationship("Match", back_populates="turns")
    team = db.relationship("Team")
    round = db.relationship("Round")
    category = db.relationship("Category")
    current_word = db.relationship("Word", foreign_keys=[current_word_id])
    turn_words = db.relationship(
        "TurnWord", back_populates="turn", cascade="all, delete-orphan"
    )
    penalties = db.relationship(
        "Penalty", back_populates="turn", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return "<Turn order={} status={}>".format(self.turn_order, self.status)


class TurnWord(db.Model):
    __tablename__ = "turn_words"

    RESULT_PENDING = "PENDING"
    RESULT_CORRECT = "CORRECT"
    RESULT_PASSED = "PASSED"
    RESULT_FAILED = "FAILED"
    RESULTS = (RESULT_PENDING, RESULT_CORRECT, RESULT_PASSED, RESULT_FAILED)

    id = db.Column(db.Integer, primary_key=True)
    turn_id = db.Column(
        db.Integer, db.ForeignKey("turns.id"), nullable=False, index=True
    )
    word_id = db.Column(
        db.Integer, db.ForeignKey("words.id"), nullable=False, index=True
    )
    sequence = db.Column(
        db.Integer, nullable=False, default=1, server_default=db.text("1")
    )
    result = db.Column(
        db.String(20),
        nullable=False,
        default=RESULT_PENDING,
        server_default=RESULT_PENDING,
    )
    used_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("turn_id", "sequence", name="uq_turn_words_sequence"),
        db.UniqueConstraint("turn_id", "word_id", name="uq_turn_words_word"),
    )

    turn = db.relationship("Turn", back_populates="turn_words")
    word = db.relationship("Word", back_populates="turn_words")

    def __repr__(self):
        return "<TurnWord word_id={} result={}>".format(self.word_id, self.result)