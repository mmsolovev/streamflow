"""runtime self-collection: sessions, samples, buckets, aggregation queue

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-31

Переводит runtime-коллектор с JSON-файлов на PostgreSQL:
`stream_runtime_sessions` (одна сессия на строку `streams`), расширенные
сэмплы и 10-минутные бакеты, очередь отложенной агрегации
`stream_stats_jobs`, провенанс `game_stats` и `games.twitch_category_id`.

Все новые колонки nullable или с server_default, поэтому миграция безопасна
для существующих данных.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- games: стабильный Twitch category id -------------------------------
    op.add_column("games", sa.Column("twitch_category_id", sa.Text(), nullable=True))
    op.create_index("ix_games_twitch_category_id", "games", ["twitch_category_id"])

    # --- game_stats: провенанс полей ---------------------------------------
    op.add_column("game_stats", sa.Column("tt_synced_at", sa.DateTime(), nullable=True))
    op.add_column(
        "game_stats", sa.Column("runtime_synced_at", sa.DateTime(), nullable=True)
    )

    # --- stream_runtime_sessions -------------------------------------------
    op.create_table(
        "stream_runtime_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "stream_id",
            sa.Integer(),
            sa.ForeignKey("streams.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("twitch_stream_id", sa.Text(), nullable=False),
        sa.Column("broadcaster_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="collecting",
        ),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("finalize_reason", sa.Text(), nullable=True),
        sa.Column("last_sample_at", sa.DateTime(), nullable=True),
        sa.Column(
            "samples_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "collector_version", sa.Integer(), nullable=False, server_default="3"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_stream_runtime_sessions_status", "stream_runtime_sessions", ["status"]
    )
    op.create_index(
        "ix_stream_runtime_sessions_twitch_stream_id",
        "stream_runtime_sessions",
        ["twitch_stream_id"],
    )
    op.create_index(
        "ix_stream_runtime_sessions_status_started",
        "stream_runtime_sessions",
        ["status", "started_at"],
    )

    # --- stream_runtime_samples --------------------------------------------
    op.add_column(
        "stream_runtime_samples",
        sa.Column(
            "stream_session_id",
            sa.BigInteger(),
            sa.ForeignKey("stream_runtime_sessions.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "stream_runtime_samples", sa.Column("category_id", sa.Text(), nullable=True)
    )
    op.add_column(
        "stream_runtime_samples",
        sa.Column("viewers_source", sa.String(length=30), nullable=True),
    )
    op.create_unique_constraint(
        "uq_stream_runtime_samples_stream_sampled",
        "stream_runtime_samples",
        ["stream_id", "sampled_at"],
    )

    # --- stream_runtime_buckets --------------------------------------------
    op.add_column(
        "stream_runtime_buckets",
        sa.Column(
            "stream_session_id",
            sa.BigInteger(),
            sa.ForeignKey("stream_runtime_sessions.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "stream_runtime_buckets",
        sa.Column("duration_hours", sa.Numeric(6, 4), nullable=True),
    )
    op.add_column(
        "stream_runtime_buckets",
        sa.Column("hours_watched", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "stream_runtime_buckets",
        sa.Column(
            "viewers_sum", sa.BigInteger(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "stream_runtime_buckets",
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "stream_runtime_buckets",
        sa.Column("followers_first", sa.Integer(), nullable=True),
    )
    op.add_column(
        "stream_runtime_buckets",
        sa.Column("followers_last", sa.Integer(), nullable=True),
    )
    # Таблица была пустой заготовкой: можно снять nullable с границы бакета.
    op.alter_column(
        "stream_runtime_buckets",
        "bucket_start",
        existing_type=sa.DateTime(),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_stream_runtime_buckets_stream_start",
        "stream_runtime_buckets",
        ["stream_id", "bucket_start"],
    )

    # --- stream_stats_jobs -------------------------------------------------
    op.create_table(
        "stream_stats_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "stream_session_id",
            sa.BigInteger(),
            sa.ForeignKey("stream_runtime_sessions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("stream_id", sa.Integer(), sa.ForeignKey("streams.id"), nullable=False),
        sa.Column("check_at", sa.DateTime(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_stream_stats_jobs_status_check_at",
        "stream_stats_jobs",
        ["status", "check_at"],
    )
    op.create_index(
        "ix_stream_stats_jobs_stream_id", "stream_stats_jobs", ["stream_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_stream_stats_jobs_stream_id", table_name="stream_stats_jobs")
    op.drop_index(
        "ix_stream_stats_jobs_status_check_at", table_name="stream_stats_jobs"
    )
    op.drop_table("stream_stats_jobs")

    op.drop_constraint(
        "uq_stream_runtime_buckets_stream_start",
        "stream_runtime_buckets",
        type_="unique",
    )
    op.alter_column(
        "stream_runtime_buckets",
        "bucket_start",
        existing_type=sa.DateTime(),
        nullable=True,
    )
    for column in (
        "followers_last",
        "followers_first",
        "sample_count",
        "viewers_sum",
        "hours_watched",
        "duration_hours",
        "stream_session_id",
    ):
        op.drop_column("stream_runtime_buckets", column)

    op.drop_constraint(
        "uq_stream_runtime_samples_stream_sampled",
        "stream_runtime_samples",
        type_="unique",
    )
    for column in ("viewers_source", "category_id", "stream_session_id"):
        op.drop_column("stream_runtime_samples", column)

    op.drop_index(
        "ix_stream_runtime_sessions_status_started",
        table_name="stream_runtime_sessions",
    )
    op.drop_index(
        "ix_stream_runtime_sessions_twitch_stream_id",
        table_name="stream_runtime_sessions",
    )
    op.drop_index(
        "ix_stream_runtime_sessions_status", table_name="stream_runtime_sessions"
    )
    op.drop_table("stream_runtime_sessions")

    op.drop_column("game_stats", "runtime_synced_at")
    op.drop_column("game_stats", "tt_synced_at")

    op.drop_index("ix_games_twitch_category_id", table_name="games")
    op.drop_column("games", "twitch_category_id")
