"""add category to matches and turns

Revision ID: f2a9e8d7c6b5
Revises: e1a2b3c4d5e6
Create Date: 2026-09-08 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2a9e8d7c6b5'
down_revision = 'e1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    # The playing team picks one category for its Round 1 turn; the pick is
    # held on the match so the go countdown worker deals words from it. Round
    # 2 turns keep the value for traceability but draw from the enabled set.
    op.add_column(
        "matches",
        sa.Column("category_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_matches_category_id", "matches", ["category_id"])
    op.create_foreign_key(
        "fk_matches_category", "matches", "categories",
        ["category_id"], ["id"],
    )

    op.add_column(
        "turns",
        sa.Column("category_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_turns_category_id", "turns", ["category_id"])
    op.create_foreign_key(
        "fk_turns_category", "turns", "categories",
        ["category_id"], ["id"],
    )


def downgrade():
    op.drop_constraint("fk_turns_category", "turns", type_="foreignkey")
    op.drop_index("ix_turns_category_id", table_name="turns")
    op.drop_column("turns", "category_id")

    op.drop_constraint("fk_matches_category", "matches", type_="foreignkey")
    op.drop_index("ix_matches_category_id", table_name="matches")
    op.drop_column("matches", "category_id")