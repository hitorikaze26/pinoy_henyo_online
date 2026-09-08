"""add ai_generation_logs

Revision ID: a9c8e7f6d5b4
Revises: f2a9e8d7c6b5
Create Date: 2026-09-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9c8e7f6d5b4'
down_revision = 'f2a9e8d7c6b5'
branch_labels = None
depends_on = None


def upgrade():
    # Audit trail for every AI word-suggestion request (success or failure).
    # Purely additive; category/team FKs are SET NULL so history survives the
    # cleanup of those entities (category_name keeps the label for analytics).
    op.create_table(
        "ai_generation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("games.id"),
            nullable=False,
        ),
        sa.Column("actor_type", sa.String(length=10), nullable=False),
        sa.Column("actor_team_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("category_name", sa.String(length=50), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=True),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_ai_generation_logs_game_id", "ai_generation_logs", ["game_id"])
    op.create_index(
        "ix_ai_generation_logs_actor_team_id", "ai_generation_logs", ["actor_team_id"]
    )
    op.create_index(
        "ix_ai_generation_logs_category_id", "ai_generation_logs", ["category_id"]
    )
    op.create_foreign_key(
        "fk_ai_generation_logs_actor_team",
        "ai_generation_logs",
        "teams",
        ["actor_team_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_ai_generation_logs_category",
        "ai_generation_logs",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_ai_generation_logs_category", "ai_generation_logs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_ai_generation_logs_actor_team", "ai_generation_logs", type_="foreignkey"
    )
    op.drop_index("ix_ai_generation_logs_category_id", table_name="ai_generation_logs")
    op.drop_index(
        "ix_ai_generation_logs_actor_team_id", table_name="ai_generation_logs"
    )
    op.drop_index("ix_ai_generation_logs_game_id", table_name="ai_generation_logs")
    op.drop_table("ai_generation_logs")