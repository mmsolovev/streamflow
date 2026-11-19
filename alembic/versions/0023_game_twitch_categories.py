"""Track Twitch category IDs independently from canonical games.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "game_twitch_categories",
        sa.Column("twitch_category_id", sa.Text(), primary_key=True),
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("games.id"),
            nullable=False,
        ),
        sa.Column("category_name", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_game_twitch_categories_game_id",
        "game_twitch_categories",
        ["game_id"],
    )

    # Preserve the current primary Twitch category IDs as the initial
    # category-to-game crosswalk. Ambiguous duplicate IDs are deliberately
    # excluded instead of choosing an arbitrary game.
    op.execute(
        """
        INSERT INTO game_twitch_categories (
            twitch_category_id, game_id, category_name, source,
            first_seen_at, last_seen_at
        )
        SELECT
            twitch_category_id,
            MIN(id),
            MIN(name),
            'migration',
            COALESCE(MIN(created_at), NOW()),
            COALESCE(MAX(updated_at), MAX(created_at), NOW())
        FROM games
        WHERE twitch_category_id IS NOT NULL
          AND btrim(twitch_category_id) <> ''
        GROUP BY twitch_category_id
        HAVING COUNT(DISTINCT id) = 1
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_game_twitch_categories_game_id",
        table_name="game_twitch_categories",
    )
    op.drop_table("game_twitch_categories")
