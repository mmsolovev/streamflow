"""stream_recordings as the single VOD registry

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-01

`stream_recordings` становится единственным хранилищем ссылок на VOD.
`telegram_announcement_vods` остаётся очередью поиска/привязки: вместо
`vod_url`/`duration_minutes`/`recorded_at` она ссылается на запись.

У одного стрима может быть несколько записей (реконнекты), поэтому связь
идёт через `recording_id`, а `stream_db_id` хранит `streams.id` для задач,
которые нашли запись не сразу.

Истёкшие VOD не удаляются: `is_available=False` скрывает их на сайте.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- stream_recordings: идентификация и доступность записи ------------
    op.add_column(
        "stream_recordings", sa.Column("twitch_stream_id", sa.Text(), nullable=True)
    )
    op.add_column(
        "stream_recordings", sa.Column("twitch_video_id", sa.Text(), nullable=True)
    )
    op.add_column(
        "stream_recordings",
        sa.Column(
            "is_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "stream_recordings", sa.Column("updated_at", sa.DateTime(), nullable=True)
    )
    op.create_index(
        "ix_stream_recordings_twitch_video_id",
        "stream_recordings",
        ["twitch_video_id"],
    )
    op.create_index(
        "ix_stream_recordings_twitch_stream_id",
        "stream_recordings",
        ["twitch_stream_id"],
    )

    op.execute(
        """
        UPDATE stream_recordings
        SET twitch_video_id = substring(url from '/videos/([0-9]+)')
        WHERE twitch_video_id IS NULL
          AND source = 'twitch'
          AND url ~ '/videos/[0-9]+'
        """
    )
    op.execute(
        """
        UPDATE stream_recordings
        SET updated_at = COALESCE(updated_at, created_at, NOW()),
            is_available = COALESCE(is_available, TRUE)
        """
    )

    # --- telegram_announcement_vods: ссылки вместо копии URL --------------
    op.add_column(
        "telegram_announcement_vods",
        sa.Column(
            "stream_db_id",
            sa.Integer(),
            sa.ForeignKey("streams.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "telegram_announcement_vods",
        sa.Column(
            "recording_id",
            sa.BigInteger(),
            sa.ForeignKey("stream_recordings.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_telegram_announcement_vods_stream_db_id",
        "telegram_announcement_vods",
        ["stream_db_id"],
    )
    op.create_index(
        "ix_telegram_announcement_vods_recording_id",
        "telegram_announcement_vods",
        ["recording_id"],
    )

    bind = op.get_bind()

    # Задачи, у которых broadcast id уже есть в streams.
    bind.execute(
        sa.text(
            """
            UPDATE telegram_announcement_vods AS j
            SET stream_db_id = s.id
            FROM streams AS s
            WHERE s.external_id = j.stream_id
              AND j.stream_db_id IS NULL
            """
        )
    )

    # Старые задачи без анонса создавались с check_at=NULL и никогда не
    # обрабатывались. Теперь запись VOD нужна и без Telegram, поэтому такие
    # задачи должны попасть в очередь.
    bind.execute(
        sa.text(
            """
            UPDATE telegram_announcement_vods
            SET check_at = NOW()
            WHERE status = 'pending_selection'
              AND check_at IS NULL
            """
        )
    )

    # Запись уже перенесена миграцией/импортом, а строки streams с таким
    # broadcast id нет: ссылка живёт в записи другого стрима (одна строка
    # streams может объединять реконнекты). Создавать дубль стрима нельзя.
    bind.execute(
        sa.text(
            """
            UPDATE telegram_announcement_vods AS j
            SET stream_db_id = r.stream_id,
                recording_id = r.id
            FROM stream_recordings AS r
            WHERE j.stream_db_id IS NULL
              AND j.vod_url IS NOT NULL
              AND r.source = 'twitch'
              AND r.url = j.vod_url
            """
        )
    )

    # Запись есть, а строки streams нет (бывает у самых старых задач):
    # создаём минимальную строку, чтобы не потерять ссылку при удалении
    # колонки vod_url. Даты уже нормализованы к UTC.
    bind.execute(
        sa.text(
            """
            INSERT INTO streams (external_id, started_at, ended_at, created_at, updated_at)
            SELECT j.stream_id, j.stream_started_at, j.stream_ended_at, NOW(), NOW()
            FROM telegram_announcement_vods AS j
            WHERE j.vod_url IS NOT NULL
              AND j.stream_db_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM streams AS s WHERE s.external_id = j.stream_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM stream_recordings AS r
                  WHERE r.source = 'twitch'
                    AND (
                        r.url = j.vod_url
                        OR (
                            substring(j.vod_url from '/videos/([0-9]+)') IS NOT NULL
                            AND r.twitch_video_id =
                                substring(j.vod_url from '/videos/([0-9]+)')
                        )
                    )
              )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE telegram_announcement_vods AS j
            SET stream_db_id = s.id
            FROM streams AS s
            WHERE s.external_id = j.stream_id
              AND j.stream_db_id IS NULL
            """
        )
    )

    # Переносим URL из очереди в записи.
    bind.execute(
        sa.text(
            """
            INSERT INTO stream_recordings (
                stream_id, source, url, twitch_stream_id, twitch_video_id,
                duration_minutes, recorded_at, is_available, created_at, updated_at
            )
            SELECT
                j.stream_db_id,
                'twitch',
                j.vod_url,
                j.stream_id,
                substring(j.vod_url from '/videos/([0-9]+)'),
                j.duration_minutes,
                j.recorded_at,
                TRUE,
                NOW(),
                NOW()
            FROM telegram_announcement_vods AS j
            WHERE j.vod_url IS NOT NULL
              AND j.stream_db_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM stream_recordings AS r
                  WHERE r.source = 'twitch'
                    AND (
                        r.url = j.vod_url
                        OR (
                            substring(j.vod_url from '/videos/([0-9]+)') IS NOT NULL
                            AND r.twitch_video_id =
                                substring(j.vod_url from '/videos/([0-9]+)')
                        )
                    )
              )
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE telegram_announcement_vods AS j
            SET recording_id = r.id
            FROM stream_recordings AS r
            WHERE j.recording_id IS NULL
              AND j.vod_url IS NOT NULL
              AND r.source = 'twitch'
              AND r.url = j.vod_url
            """
        )
    )

    # Задачи без vod_url (не нашли запись), но у стрима ровно одна запись:
    # связь однозначна и её можно восстановить.
    bind.execute(
        sa.text(
            """
            UPDATE telegram_announcement_vods AS j
            SET recording_id = r.id
            FROM stream_recordings AS r
            WHERE j.recording_id IS NULL
              AND j.stream_db_id = r.stream_id
              AND r.source = 'twitch'
              AND (
                  SELECT count(*)
                  FROM stream_recordings AS r2
                  WHERE r2.stream_id = j.stream_db_id
                    AND r2.source = 'twitch'
              ) = 1
            """
        )
    )

    op.drop_column("telegram_announcement_vods", "vod_url")
    op.drop_column("telegram_announcement_vods", "duration_minutes")
    op.drop_column("telegram_announcement_vods", "recorded_at")


def downgrade() -> None:
    op.add_column("telegram_announcement_vods", sa.Column("vod_url", sa.Text()))
    op.add_column(
        "telegram_announcement_vods", sa.Column("duration_minutes", sa.Integer())
    )
    op.add_column(
        "telegram_announcement_vods", sa.Column("recorded_at", sa.DateTime())
    )

    op.execute(
        """
        UPDATE telegram_announcement_vods AS j
        SET vod_url = r.url,
            duration_minutes = r.duration_minutes,
            recorded_at = r.recorded_at
        FROM stream_recordings AS r
        WHERE j.recording_id = r.id
        """
    )

    op.drop_index(
        "ix_telegram_announcement_vods_recording_id",
        table_name="telegram_announcement_vods",
    )
    op.drop_index(
        "ix_telegram_announcement_vods_stream_db_id",
        table_name="telegram_announcement_vods",
    )
    op.drop_column("telegram_announcement_vods", "recording_id")
    op.drop_column("telegram_announcement_vods", "stream_db_id")

    op.drop_index(
        "ix_stream_recordings_twitch_stream_id", table_name="stream_recordings"
    )
    op.drop_index(
        "ix_stream_recordings_twitch_video_id", table_name="stream_recordings"
    )
    op.drop_column("stream_recordings", "updated_at")
    op.drop_column("stream_recordings", "is_available")
    op.drop_column("stream_recordings", "twitch_video_id")
    op.drop_column("stream_recordings", "twitch_stream_id")
