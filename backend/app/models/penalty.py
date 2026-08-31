from ..extensions import db


class Penalty(db.Model):
    __tablename__ = "penalties"

    TYPE_ADD_TIME = "ADD_TIME"
    TYPE_REMOVE_TIME = "REMOVE_TIME"
    TYPE_REVERSAL = "REVERSAL"
    TYPES = (TYPE_ADD_TIME, TYPE_REMOVE_TIME, TYPE_REVERSAL)

    id = db.Column(db.Integer, primary_key=True)
    turn_id = db.Column(
        db.Integer, db.ForeignKey("turns.id"), nullable=False, index=True
    )
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id"), nullable=False, index=True
    )
    seconds = db.Column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    type = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=db.text("CURRENT_TIMESTAMP")
    )

    turn = db.relationship("Turn", back_populates="penalties")
    team = db.relationship("Team", back_populates="penalties")

    def __repr__(self):
        return "<Penalty type={} seconds={}>".format(self.type, self.seconds)