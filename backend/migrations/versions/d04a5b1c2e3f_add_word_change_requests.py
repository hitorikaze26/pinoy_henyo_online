"""add word change requests table

Revision ID: d04a5b1c2e3f
Revises: 4a9f2c8b31d0
Create Date: 2026-09-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd04a5b1c2e3f'
down_revision = '4a9f2c8b31d0'
branch_labels = None
depends_on = None


def upgrade():
    # Persistent word-change requests: a team requests a change to one of the
    # words it submitted; the host resolves or cancels it. Words under review
    # are marked Word.STATUS_UNDER_REVIEW (value only, no schema change).
    op.create_table(
        "word_change_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "game_id", sa.Integer(), sa.ForeignKey("games.id"),
            nullable=False,
        ),
        sa.Column(
            "team_id", sa.Integer(), sa.ForeignKey("teams.id"),
            nullable=True,
        ),
        sa.Column(
            "word_id", sa.Integer(), sa.ForeignKey("words.id"),
            nullable=True,
        ),
        sa.Column("comment", sa.String(length=300), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_word_change_requests_game_id",
        "word_change_requests",
        ["game_id"],
    )
    op.create_index(
        "ix_word_change_requests_team_id",
        "word_change_requests",
        ["team_id"],
    )
    op.create_index(
        "ix_word_change_requests_word_id",
        "word_change_requests",
        ["word_id"],
    )


def downgrade():
    op.drop_index("ix_word_change_requests_word_id", table_name="word_change_requests")
    op.drop_index("ix_word_change_requests_team_id", table_name="word_change_requests")
    op.drop_index("ix_word_change_requests_game_id", table_name="word_change_requests")
    op.drop_table("word_change_requests")