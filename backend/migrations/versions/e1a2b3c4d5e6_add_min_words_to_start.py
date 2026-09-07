"""add min_words_to_start to game settings

Revision ID: e1a2b3c4d5e6
Revises: d04a5b1c2e3f
Create Date: 2026-09-07 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1a2b3c4d5e6'
down_revision = 'd04a5b1c2e3f'
branch_labels = None
depends_on = None


def upgrade():
    # Configurable minimum word-pool size required before the host can start
    # the game (5/10/15/20/25). Defaults to 15.
    op.add_column(
        "game_settings",
        sa.Column(
            "min_words_to_start",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
    )


def downgrade():
    op.drop_column("game_settings", "min_words_to_start")