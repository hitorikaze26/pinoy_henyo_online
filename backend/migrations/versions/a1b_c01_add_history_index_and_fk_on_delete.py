"""add host history composite index

Revision ID: a1b_c01
Revises: 3f8c7a21435f
Create Date: 2026-09-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b_c01'
down_revision = '3f8c7a21435f'
branch_labels = None
depends_on = None


def upgrade():
    # Composite index for efficient host history queries.
    # games_history_for_host filters by host_session_token and sorts by created_at.
    op.create_index(
        'ix_games_host_token_created',
        'games',
        ['host_session_token', 'created_at'],
        unique=False,
    )


def downgrade():
    op.drop_index('ix_games_host_token_created', table_name='games')
