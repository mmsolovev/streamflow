"""Add media metadata and durable clip synchronization state.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stream_recordings", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("stream_recordings", sa.Column("thumbnail_url", sa.Text(), nullable=True))
    op.add_column("stream_recordings", sa.Column("views_count", sa.Integer(), nullable=True))
    op.add_column("clips", sa.Column("twitch_video_id", sa.Text(), nullable=True))
    op.create_index(
        "ix_clips_twitch_video_id",
        "clips",
        ["twitch_video_id"],
    )

    op.create_table(
        "clip_sync_state",
        sa.Column("state_key", sa.String(length=64), primary_key=True),
        sa.Column("cursor_at", sa.DateTime(), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "clip_sync_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "stream_id",
            sa.Integer(),
            sa.ForeignKey("streams.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("check_at", sa.DateTime(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_clip_sync_jobs_status_check_at",
        "clip_sync_jobs",
        ["status", "check_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_clip_sync_jobs_status_check_at", table_name="clip_sync_jobs")
    op.drop_table("clip_sync_jobs")
    op.drop_table("clip_sync_state")
    op.drop_index("ix_clips_twitch_video_id", table_name="clips")
    op.drop_column("clips", "twitch_video_id")
    op.drop_column("stream_recordings", "views_count")
    op.drop_column("stream_recordings", "thumbnail_url")
    op.drop_column("stream_recordings", "title")
