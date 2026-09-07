"""add display start state to games

Revision ID: 4a9f2c8b31d0
Revises: 9f8e7d6c5b4a
Create Date: 2026-09-07 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4a9f2c8b31d0'
down_revision = '9f8e7d6c5b4a'
branch_labels = None
depends_on = None


def upgrade():
    # Two-stage display-start lifecycle (IDLE/ARMED/COUNTDOWN/RUNNING) with
    # the server-authoritative GO deadline and the match being started.
    op.add_column(
        "games",
        sa.Column(
            "display_status",
            sa.String(length=20),
            nullable=False,
            server_default="IDLE",
        ),
    )
    op.add_column(
        "games",
        sa.Column("display_go_match_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "games",
        sa.Column("display_go_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_games_display_go_match_id", "games", ["display_go_match_id"]
    )


def downgrade():
    op.drop_index("ix_games_display_go_match_id", table_name="games")
    op.drop_column("games", "display_go_at")
    op.drop_column("games", "display_go_match_id")
    op.drop_column("games", "display_status")