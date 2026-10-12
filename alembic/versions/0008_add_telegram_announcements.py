"""add telegram_announcements + telegram_announcement_vods

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-01

Summary:
1. telegram_announcements — посты Telegram-канала, которые бот считает анонсами стрима.
   UNIQUE(chat_id, message_id) делает повторную обработку апдейта идемпотентной.
2. telegram_announcement_vods — задача «найти VOD для стрима» в рамках одного поста.
   Свое состояние (а не колонка в announcement) потому, что после краша трансляции
   и перезапуска broadcast один и тот же пост получает несколько VOD: каждый
   Twitch stream_id — отдельная задача со своим статусом.
   UNIQUE(announcement_id, stream_id) не даёт завести две задачи на один стрим.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_announcements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("media_kind", sa.String(length=20), nullable=True),
        sa.Column("media_group_id", sa.Text(), nullable=True),
        sa.Column("is_forward", sa.Boolean(), nullable=True),
        sa.Column("text_snapshot", sa.Text(), nullable=True),
        sa.Column("caption_snapshot", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("edited_text", sa.Text(), nullable=True),
        sa.Column("manually_edited", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chat_id", "message_id",
            name="uq_telegram_announcements_chat_message",
        ),
    )
    op.create_index(
        "ix_telegram_announcements_status", "telegram_announcements", ["status"], unique=False,
    )
    op.create_index(
        "ix_telegram_announcements_posted_at", "telegram_announcements", ["posted_at"], unique=False,
    )

    op.create_table(
        "telegram_announcement_vods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("announcement_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Text(), nullable=False),
        sa.Column("stream_started_at", sa.DateTime(), nullable=False),
        sa.Column("stream_ended_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("vod_url", sa.Text(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=True),
        sa.Column("check_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["announcement_id"], ["telegram_announcements.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "announcement_id", "stream_id",
            name="uq_telegram_announcement_vods_announcement_stream",
        ),
    )
    op.create_index(
        "ix_telegram_announcement_vods_status_check_at",
        "telegram_announcement_vods", ["status", "check_at"], unique=False,
    )
    op.create_index(
        "ix_telegram_announcement_vods_stream_id",
        "telegram_announcement_vods", ["stream_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_announcement_vods_stream_id", table_name="telegram_announcement_vods",
    )
    op.drop_index(
        "ix_telegram_announcement_vods_status_check_at",
        table_name="telegram_announcement_vods",
    )
    op.drop_table("telegram_announcement_vods")

    op.drop_index("ix_telegram_announcements_posted_at", table_name="telegram_announcements")
    op.drop_index("ix_telegram_announcements_status", table_name="telegram_announcements")
    op.drop_table("telegram_announcements")