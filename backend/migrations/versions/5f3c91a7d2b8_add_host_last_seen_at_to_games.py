"""add host_last_seen_at to games for host-disconnect expiry

Revision ID: 5f3c91a7d2b8
Revises: ddfa399e4013
Create Date: 2026-08-31 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5f3c91a7d2b8'
down_revision = 'ddfa399e4013'
branch_labels = None
depends_on = None


def upgrade():
    # Track host presence so the maintenance sweeper can expire games whose
    # host has been absent for > HOST_INACTIVITY_TIMEOUT (host disconnect).
    with op.batch_alter_table('games', schema=None) as batch_op:
        batch_op.add_column(sa.Column('host_last_seen_at', sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f('ix_games_host_last_seen_at'), ['host_last_seen_at'])


def downgrade():
    with op.batch_alter_table('games', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_games_host_last_seen_at'))
        batch_op.drop_column('host_last_seen_at')
