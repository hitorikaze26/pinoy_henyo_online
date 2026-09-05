"""add assigned_round to words

Revision ID: d21a9c04fe6b
Revises: c0de01a11b5f
Create Date: 2026-09-06 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd21a9c04fe6b'
down_revision = 'c0de01a11b5f'
branch_labels = None
depends_on = None


def upgrade():
    # Each word is assigned to exactly one round (1 or 2). Default 1: newly
    # submitted words land in Round 1 until the host moves them.
    op.add_column(
        "words",
        sa.Column(
            "assigned_round",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_words_assigned_round", "words", "assigned_round IN (1, 2)"
    )

    # Backfill preserving the old semantics: words whose category was selected
    # for Round 1 stay in Round 1; every other word moves to Round 2. This is
    # only meaningful for games that already have words + a Round 1 selection.
    op.execute(
        """
        UPDATE words
        SET assigned_round = 2
        WHERE NOT EXISTS (
            SELECT 1
            FROM round_categories rc
            JOIN rounds r ON r.id = rc.round_id
            WHERE rc.category_id = words.category_id
              AND r.round_number = 1
              AND r.game_id = words.game_id
        )
        """
    )


def downgrade():
    op.drop_constraint("ck_words_assigned_round", "words", type_="check")
    op.drop_column("words", "assigned_round")