"""add round categories table

Revision ID: b7cffb15bef7
Revises: b5b94011900a
Create Date: 2026-08-29 19:12:13.690336

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7cffb15bef7'
down_revision = 'b5b94011900a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "round_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["rounds.id"],
            name="fk_round_categories_round",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_round_categories_category",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "round_id", "category_id", name="uq_round_categories_round_category"
        ),
    )
    op.create_index(
        "ix_round_categories_round_id",
        "round_categories",
        ["round_id"],
        unique=False,
    )
    op.create_index(
        "ix_round_categories_category_id",
        "round_categories",
        ["category_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_round_categories_category_id", table_name="round_categories"
    )
    op.drop_index(
        "ix_round_categories_round_id", table_name="round_categories"
    )
    op.drop_table("round_categories")
