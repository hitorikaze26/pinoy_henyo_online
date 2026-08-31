from ..extensions import db


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(
        db.Integer, db.ForeignKey("games.id"), nullable=False, index=True
    )
    name = db.Column(db.String(50), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=db.text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        db.UniqueConstraint("game_id", "name", name="uq_categories_game_name"),
    )

    game = db.relationship("Game", back_populates="categories")
    words = db.relationship(
        "Word", back_populates="category", cascade="all, delete-orphan"
    )
    round_selections = db.relationship(
        "RoundCategory",
        back_populates="category",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return "<Category {} game_id={}>".format(self.name, self.game_id)