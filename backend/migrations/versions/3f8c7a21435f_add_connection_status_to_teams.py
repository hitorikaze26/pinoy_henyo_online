"""add connection_status to teams for host-approval flow

Revision ID: 3f8c7a21435f
Revises: 5f3c91a7d2b8
Create Date: 2026-09-01 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3f8c7a21435f'
down_revision = '5f3c91a7d2b8'
branch_labels = None
depends_on = None


def upgrade():
    # Team-level host-connection state: NOT_CONNECTED / CONNECTION_REQUESTED /
    # CONNECTED / DECLINED / DISCONNECTED. Existing teams were implicitly
    # "connected" once they created a session, so backfill to CONNECTED.
    with op.batch_alter_table('teams', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'connection_status',
                sa.String(length=24),
                nullable=False,
                server_default='CONNECTED',
            )
        )
        batch_op.create_index(batch_op.f('ix_teams_connection_status'), ['connection_status'])


def downgrade():
    with op.batch_alter_table('teams', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_teams_connection_status'))
        batch_op.drop_column('connection_status')