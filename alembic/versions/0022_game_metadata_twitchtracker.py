"""Preserve TwitchTracker's per-game summary snapshot separately.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "game_metadata_twitchtracker",
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("games.id"),
            primary_key=True,
        ),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("hours_streamed", sa.Float(), nullable=True),
        sa.Column("avg_viewers", sa.Integer(), nullable=True),
        sa.Column("max_viewers", sa.Integer(), nullable=True),
        sa.Column("followers_per_hour", sa.Float(), nullable=True),
        sa.Column("last_stream", sa.DateTime(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
    )

    # Keep the latest TT-owned values before `game_stats` switches to values
    # calculated from per-stream detail.
    op.execute(
        """
        INSERT INTO game_metadata_twitchtracker (
            game_id, avg_viewers, followers_per_hour, synced_at
        )
        SELECT
            game_id,
            avg_viewers,
            followers_per_hour,
            COALESCE(tt_synced_at, synced_at, NOW())
        FROM game_stats
        WHERE avg_viewers IS NOT NULL OR followers_per_hour IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("game_metadata_twitchtracker")
