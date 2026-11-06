"""chat log, stream participants and extended command usage

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-31

Логируется только основной канал (TWITCH_PRIMARY_CHANNEL). Сообщения чата
хранятся бессрочно (CHAT_LOG_RETENTION_DAYS=0), `deleted_at` — точечное
удаление. Команды по-прежнему пишутся только при успешном вызове; новые поля
связывают запись со стримом и сообщением чата.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- chat_messages -----------------------------------------------------
    op.add_column(
        "chat_messages", sa.Column("twitch_message_id", sa.Text(), nullable=True)
    )
    op.add_column(
        "chat_messages",
        sa.Column("stream_id", sa.Integer(), sa.ForeignKey("streams.id"), nullable=True),
    )
    op.add_column("chat_messages", sa.Column("channel_login", sa.Text(), nullable=True))
    op.add_column(
        "chat_messages",
        sa.Column(
            "is_command", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "chat_messages", sa.Column("reply_parent_message_id", sa.Text(), nullable=True)
    )
    op.add_column("chat_messages", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_unique_constraint(
        "uq_chat_messages_twitch_message_id",
        "chat_messages",
        ["twitch_message_id"],
    )
    op.create_index(
        "ix_chat_messages_stream_created",
        "chat_messages",
        ["stream_id", "created_at"],
    )
    op.create_index(
        "ix_chat_messages_user_created",
        "chat_messages",
        ["user_id", "created_at"],
    )

    # --- stream_chat_participants -----------------------------------------
    op.create_table(
        "stream_chat_participants",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("stream_id", sa.Integer(), sa.ForeignKey("streams.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("first_message_at", sa.DateTime(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column(
            "messages_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.create_unique_constraint(
        "uq_stream_chat_participants_stream_user",
        "stream_chat_participants",
        ["stream_id", "user_id"],
    )
    op.create_index(
        "ix_stream_chat_participants_user_last",
        "stream_chat_participants",
        ["user_id", "last_message_at"],
    )

    # --- command_usage_logs -----------------------------------------------
    op.add_column(
        "command_usage_logs",
        sa.Column("stream_id", sa.Integer(), sa.ForeignKey("streams.id"), nullable=True),
    )
    op.add_column("command_usage_logs", sa.Column("invoked_name", sa.Text(), nullable=True))
    op.add_column(
        "command_usage_logs", sa.Column("twitch_message_id", sa.Text(), nullable=True)
    )
    op.create_index(
        "ix_command_usage_logs_stream_id",
        "command_usage_logs",
        ["stream_id"],
    )
    op.create_index(
        "ix_command_usage_logs_twitch_message_id",
        "command_usage_logs",
        ["twitch_message_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_command_usage_logs_twitch_message_id", table_name="command_usage_logs"
    )
    op.drop_index("ix_command_usage_logs_stream_id", table_name="command_usage_logs")
    op.drop_column("command_usage_logs", "twitch_message_id")
    op.drop_column("command_usage_logs", "invoked_name")
    op.drop_column("command_usage_logs", "stream_id")

    op.drop_index(
        "ix_stream_chat_participants_user_last",
        table_name="stream_chat_participants",
    )
    op.drop_constraint(
        "uq_stream_chat_participants_stream_user",
        "stream_chat_participants",
        type_="unique",
    )
    op.drop_table("stream_chat_participants")

    op.drop_index("ix_chat_messages_user_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_stream_created", table_name="chat_messages")
    op.drop_constraint(
        "uq_chat_messages_twitch_message_id", "chat_messages", type_="unique"
    )
    for column in (
        "deleted_at",
        "reply_parent_message_id",
        "is_command",
        "channel_login",
        "stream_id",
        "twitch_message_id",
    ):
        op.drop_column("chat_messages", column)
