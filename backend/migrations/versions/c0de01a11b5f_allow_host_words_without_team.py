"""allow host words without a team

Revision ID: c0de01a11b5f
Revises: a1b_c01
Create Date: 2026-09-06 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c0de01a11b5f'
down_revision = 'a1b_c01'
branch_labels = None
depends_on = None


def upgrade():
    # Host-added words have no owning team: submission is optional.
    op.alter_column('words', 'submitted_by_team_id', existing_type=sa.Integer(),
                    nullable=True)


def downgrade():
    # Pending host words (NULL team) block a NOT NULL revert until they are
    # removed or reassigned to a team.
    op.execute(
        "UPDATE words SET submitted_by_team_id = NULL "
        "WHERE submitted_by_team_id IS NULL"
    )
    op.alter_column('words', 'submitted_by_team_id', existing_type=sa.Integer(),
                    nullable=False)