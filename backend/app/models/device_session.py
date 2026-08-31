from ..extensions import db


class DeviceSession(db.Model):
    __tablename__ = "device_sessions"

    DEVICE_TYPE_HOST = "HOST"
    DEVICE_TYPE_TEAM_LEADER = "TEAM_LEADER"
    DEVICE_TYPE_TEAM_MEMBER = "TEAM_MEMBER"
    DEVICE_TYPES = (DEVICE_TYPE_HOST, DEVICE_TYPE_TEAM_LEADER, DEVICE_TYPE_TEAM_MEMBER)

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(
        db.Integer, db.ForeignKey("games.id"), nullable=False, index=True
    )
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=True, index=True)
    member_id = db.Column(
        db.Integer, db.ForeignKey("team_members.id"), nullable=True, index=True
    )
    device_id = db.Column(db.String(128), nullable=False)
    session_token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    device_type = db.Column(db.String(20), nullable=False)
    connected_at = db.Column(
        db.DateTime, nullable=False, server_default=db.text("CURRENT_TIMESTAMP")
    )
    disconnected_at = db.Column(db.DateTime, nullable=True)
    last_heartbeat = db.Column(db.DateTime, nullable=True)

    game = db.relationship("Game", back_populates="device_sessions")
    team = db.relationship("Team", back_populates="device_sessions")
    member = db.relationship("TeamMember", back_populates="device_sessions")

    def __repr__(self):
        return "<DeviceSession token={} type={}>".format(
            self.session_token, self.device_type
        )