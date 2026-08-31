from ..extensions import db


class GameEvent(db.Model):
    __tablename__ = "game_events"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(
        db.Integer, db.ForeignKey("games.id"), nullable=False, index=True
    )
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=True, index=True)
    member_id = db.Column(
        db.Integer, db.ForeignKey("team_members.id"), nullable=True, index=True
    )
    event_type = db.Column(db.String(50), nullable=False, index=True)
    event_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, server_default=db.text("CURRENT_TIMESTAMP")
    )

    game = db.relationship("Game", back_populates="events")
    team = db.relationship("Team")
    member = db.relationship("TeamMember", back_populates="events")

    def __repr__(self):
        return "<GameEvent type={} game_id={}>".format(self.event_type, self.game_id)