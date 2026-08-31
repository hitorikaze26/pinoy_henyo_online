"""add unique normalized word index

Revision ID: b5b94011900a
Revises: 08fbf0e3f1db
Create Date: 2026-08-29 18:37:07.686705

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5b94011900a'
down_revision = '08fbf0e3f1db'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_words_game_category_normalized",
        "words",
        ["game_id", "category_id", "normalized_word"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_words_game_category_normalized", table_name="words")
