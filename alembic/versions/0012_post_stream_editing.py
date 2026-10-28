"""add post-stream editing settings and operations

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_HEADER = "Запись стрима:\n\n"
DEFAULT_ITEM = "🎥{{link}}~"
DEFAULT_SEPARATOR = "\n"


def upgrade() -> None:
    op.add_column("telegram_announcements", sa.Column("original_text", sa.Text(), nullable=True))
    op.add_column("telegram_announcements", sa.Column("original_caption", sa.Text(), nullable=True))
    op.add_column("telegram_announcements", sa.Column("original_entities", sa.Text(), nullable=True))
    op.add_column("telegram_announcements", sa.Column("text_entities_snapshot", sa.Text(), nullable=True))
    op.add_column("telegram_announcements", sa.Column("caption_entities_snapshot", sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE telegram_announcements
        SET original_text = text_snapshot,
            original_caption = caption_snapshot
        WHERE original_text IS NULL AND original_caption IS NULL
        """
    )

    op.alter_column(
        "telegram_announcement_vods",
        "announcement_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.add_column(
        "telegram_announcement_vods",
        sa.Column("selected_by_admin", sa.Boolean(), server_default=sa.false(), nullable=True),
    )
    op.add_column(
        "telegram_announcement_vods",
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "telegram_announcement_vods",
        sa.Column("publish_now_requested_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "telegram_announcement_vods",
        sa.Column("undo_requested_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "telegram_announcement_vods",
        sa.Column("applied_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "telegram_announcement_vods",
        sa.Column("applied_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "telegram_announcement_vods",
        sa.Column("applied_entities", sa.Text(), nullable=True),
    )
    op.add_column(
        "telegram_announcement_vods",
        sa.Column("undone_at", sa.DateTime(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_telegram_announcement_vods_stream_id",
        "telegram_announcement_vods",
        ["stream_id"],
    )

    op.create_table(
        "telegram_post_edit_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("delay_seconds", sa.Integer(), nullable=False, server_default="660"),
        sa.Column("header", sa.Text(), nullable=False, server_default=DEFAULT_HEADER),
        sa.Column("item", sa.Text(), nullable=False, server_default=DEFAULT_ITEM),
        sa.Column("separator", sa.Text(), nullable=False, server_default=DEFAULT_SEPARATOR),
        sa.Column("footer", sa.Text(), nullable=False, server_default=""),
        sa.Column("link_label", sa.Text(), nullable=False, server_default="TWITCH"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.execute(
        f"""
        INSERT INTO telegram_post_edit_settings
            (id, enabled, delay_seconds, header, item, separator, footer, link_label)
        VALUES
            (1, true, 660, '{DEFAULT_HEADER}', '{DEFAULT_ITEM}', '{DEFAULT_SEPARATOR}', '', 'TWITCH')
        """
    )

    op.create_table(
        "telegram_post_edit_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("telegram_announcement_vods.id"),
            nullable=False,
        ),
        sa.Column(
            "announcement_id",
            sa.Integer(),
            sa.ForeignKey("telegram_announcements.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False, server_default="publish"),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("before_text", sa.Text(), nullable=True),
        sa.Column("before_entities", sa.Text(), nullable=True),
        sa.Column("after_text", sa.Text(), nullable=True),
        sa.Column("after_entities", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_telegram_post_edit_operations_job_id",
        "telegram_post_edit_operations",
        ["job_id", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_post_edit_operations_job_id",
        table_name="telegram_post_edit_operations",
    )
    op.drop_table("telegram_post_edit_operations")
    op.drop_table("telegram_post_edit_settings")

    op.drop_constraint(
        "uq_telegram_announcement_vods_stream_id",
        "telegram_announcement_vods",
        type_="unique",
    )
    for column in (
        "undone_at",
        "applied_entities",
        "applied_text",
        "applied_at",
        "undo_requested_at",
        "publish_now_requested_at",
        "last_checked_at",
        "selected_by_admin",
    ):
        op.drop_column("telegram_announcement_vods", column)
    op.alter_column(
        "telegram_announcement_vods",
        "announcement_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    for column in (
        "caption_entities_snapshot",
        "text_entities_snapshot",
        "original_entities",
        "original_caption",
        "original_text",
    ):
        op.drop_column("telegram_announcements", column)
