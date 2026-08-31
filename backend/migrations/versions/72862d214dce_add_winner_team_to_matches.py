"""add winner team to matches

Revision ID: 72862d214dce
Revises: b7cffb15bef7
Create Date: 2026-08-29 19:32:57.711799

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '72862d214dce'
down_revision = 'b7cffb15bef7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "matches",
        sa.Column("winner_team_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_matches_winner_team", "matches", "teams", ["winner_team_id"], ["id"]
    )
    op.create_index(
        "ix_matches_winner_team_id", "matches", ["winner_team_id"], unique=False
    )


def downgrade():
    op.drop_index("ix_matches_winner_team_id", table_name="matches")
    op.drop_constraint("fk_matches_winner_team", "matches", type_="foreignkey")
    op.drop_column("matches", "winner_team_id")
