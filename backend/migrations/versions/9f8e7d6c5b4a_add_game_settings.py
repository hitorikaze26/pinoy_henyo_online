"""add game_settings

Revision ID: 9f8e7d6c5b4a
Revises: d21a9c04fe6b
Create Date: 2026-09-06 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f8e7d6c5b4a'
down_revision = 'd21a9c04fe6b'
branch_labels = None
depends_on = None


def upgrade():
    # Per-game server-backed settings (1:1 with games). Gameplay rules are
    # enforced by the backend from these values; display flags are consumed by
    # the player UI. Audio preferences stay device-local and are not stored.
    op.create_table(
        "game_settings",
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column(
            "max_words_per_category",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column(
            "penalty_seconds",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
        sa.Column(
            "allow_new_teams",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "auto_approve_connections",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "max_teams", sa.Integer(), nullable=False, server_default="8"
        ),
        sa.Column(
            "max_members", sa.Integer(), nullable=False, server_default="6"
        ),
        sa.Column(
            "show_player_names",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "show_role_labels",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "show_scores",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "show_qr_code",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "show_round_category",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"], name="fk_game_settings_game"
        ),
        sa.PrimaryKeyConstraint("game_id"),
    )


def downgrade():
    op.drop_table("game_settings")