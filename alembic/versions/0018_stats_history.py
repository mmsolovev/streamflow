"""stats change history and rollback batches

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-31

`stats_change_batches` — один прогон записи статистики, `stats_change_log` —
построчные изменения old/new. `game_stats.last_change_batch_id` связывает
строку с последним применившим её батчем. Откат создаёт новый батч с
`action='rollback'`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stats_change_batches",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "action", sa.String(length=20), nullable=False, server_default="apply"
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("stream_id", sa.Integer(), sa.ForeignKey("streams.id"), nullable=True),
        sa.Column("stream_session_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="applied"
        ),
        sa.Column(
            "changes_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "reverted_by_batch_id",
            sa.BigInteger(),
            sa.ForeignKey("stats_change_batches.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "ix_stats_change_batches_source_created",
        "stats_change_batches",
        ["source", "created_at"],
    )
    op.create_index(
        "ix_stats_change_batches_stream_id", "stats_change_batches", ["stream_id"]
    )

    op.create_table(
        "stats_change_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.BigInteger(),
            sa.ForeignKey("stats_change_batches.id"),
            nullable=False,
        ),
        sa.Column("entity", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("field", sa.String(length=40), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_stats_change_log_batch_id", "stats_change_log", ["batch_id"]
    )
    op.create_index(
        "ix_stats_change_log_entity_changed",
        "stats_change_log",
        ["entity", "entity_id", "changed_at"],
    )

    op.add_column(
        "game_stats",
        sa.Column(
            "last_change_batch_id",
            sa.BigInteger(),
            sa.ForeignKey("stats_change_batches.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("game_stats", "last_change_batch_id")

    op.drop_index(
        "ix_stats_change_log_entity_changed", table_name="stats_change_log"
    )
    op.drop_index("ix_stats_change_log_batch_id", table_name="stats_change_log")
    op.drop_table("stats_change_log")

    op.drop_index(
        "ix_stats_change_batches_stream_id", table_name="stats_change_batches"
    )
    op.drop_index(
        "ix_stats_change_batches_source_created",
        table_name="stats_change_batches",
    )
    op.drop_table("stats_change_batches")
