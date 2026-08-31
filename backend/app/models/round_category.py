from ..extensions import db


class RoundCategory(db.Model):
    __tablename__ = "round_categories"

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(
        db.Integer,
        db.ForeignKey("rounds.id", name="fk_round_categories_round"),
        nullable=False,
        index=True,
    )
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("categories.id", name="fk_round_categories_category"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=db.text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        db.UniqueConstraint(
            "round_id", "category_id", name="uq_round_categories_round_category"
        ),
    )

    round = db.relationship("Round", back_populates="selected_categories")
    category = db.relationship("Category", back_populates="round_selections")

    def __repr__(self):
        return "<RoundCategory round_id={} category_id={}>".format(
            self.round_id, self.category_id
        )