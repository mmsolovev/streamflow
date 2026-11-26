"""Central media assets, typed links, and editable social links.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("storage_kind", sa.String(length=10), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True, unique=True),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=30),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(storage_kind = 'url' AND url IS NOT NULL) OR "
            "(storage_kind = 'file' AND storage_key IS NOT NULL)",
            name="ck_media_assets_storage_reference",
        ),
        sa.CheckConstraint(
            "storage_kind IN ('url', 'file')",
            name="ck_media_assets_storage_kind",
        ),
    )
    op.create_index("ix_media_assets_source", "media_assets", ["source"])
    op.create_index("ix_media_assets_sha256", "media_assets", ["sha256"])

    op.create_table(
        "game_media_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            sa.BigInteger(),
            sa.ForeignKey("media_assets.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=30), nullable=False, server_default="cover"),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "game_id", "role", "source", name="uq_game_media_role_source"
        ),
    )
    op.create_index("ix_game_media_assets_asset_id", "game_media_assets", ["asset_id"])

    op.create_table(
        "stream_recording_media",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "recording_id",
            sa.BigInteger(),
            sa.ForeignKey("stream_recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            sa.BigInteger(),
            sa.ForeignKey("media_assets.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "recording_id", "role", name="uq_recording_media_role"
        ),
    )
    op.create_index(
        "ix_stream_recording_media_asset_id",
        "stream_recording_media",
        ["asset_id"],
    )

    op.create_table(
        "telegram_announcement_media",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "announcement_id",
            sa.Integer(),
            sa.ForeignKey("telegram_announcements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            sa.BigInteger(),
            sa.ForeignKey("media_assets.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=30), nullable=False, server_default="photo"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "announcement_id",
            "role",
            "position",
            name="uq_telegram_announcement_media_role_position",
        ),
    )
    op.create_index(
        "ix_telegram_announcement_media_asset_id",
        "telegram_announcement_media",
        ["asset_id"],
    )

    op.create_table(
        "social_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("service_key", sa.String(length=40), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, server_default="#"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "icon_asset_id",
            sa.BigInteger(),
            sa.ForeignKey("media_assets.id"),
            nullable=True,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_social_links_active_order",
        "social_links",
        ["is_active", "sort_order"],
    )

    # Move existing IGDB cover URLs, including values available only in raw_payload,
    # into the central media library before removing the legacy column.
    op.execute(
        """
        WITH source_covers AS (
            SELECT
                game_id,
                CASE
                    WHEN COALESCE(NULLIF(cover_url, ''), NULLIF(raw_payload #>> '{cover,url}', '')) LIKE '//%'
                        THEN 'https:' || COALESCE(NULLIF(cover_url, ''), raw_payload #>> '{cover,url}')
                    WHEN COALESCE(NULLIF(cover_url, ''), NULLIF(raw_payload #>> '{cover,url}', '')) LIKE '/%'
                        THEN 'https://images.igdb.com' || COALESCE(NULLIF(cover_url, ''), raw_payload #>> '{cover,url}')
                    ELSE COALESCE(NULLIF(cover_url, ''), NULLIF(raw_payload #>> '{cover,url}', ''))
                END AS url
            FROM game_metadata_igdb
        ),
        unique_urls AS (
            SELECT DISTINCT url FROM source_covers WHERE url IS NOT NULL
        ),
        inserted_assets AS (
            INSERT INTO media_assets
                (storage_kind, url, source, created_at, updated_at)
            SELECT 'url', url, 'igdb', now(), now()
            FROM unique_urls
            RETURNING id, url
        )
        INSERT INTO game_media_assets (game_id, asset_id, role, source, created_at)
        SELECT source_covers.game_id, inserted_assets.id, 'cover', 'igdb', now()
        FROM source_covers
        JOIN inserted_assets ON inserted_assets.url = source_covers.url
        WHERE source_covers.url IS NOT NULL
        ON CONFLICT (game_id, role, source) DO NOTHING
        """
    )

    # Preserve Twitch's own VOD thumbnails as fallback media assets.
    op.execute(
        """
        WITH unique_thumbnails AS (
            SELECT DISTINCT thumbnail_url
            FROM stream_recordings
            WHERE thumbnail_url IS NOT NULL AND btrim(thumbnail_url) <> ''
        ),
        inserted_assets AS (
            INSERT INTO media_assets
                (storage_kind, url, source, created_at, updated_at)
            SELECT 'url', thumbnail_url, 'twitch', now(), now()
            FROM unique_thumbnails
            RETURNING id, url
        )
        INSERT INTO stream_recording_media
            (recording_id, asset_id, role, created_at)
        SELECT recording.id, asset.id, 'twitch_preview', now()
        FROM stream_recordings AS recording
        JOIN inserted_assets AS asset ON asset.url = recording.thumbnail_url
        WHERE recording.thumbnail_url IS NOT NULL
        ON CONFLICT (recording_id, role) DO NOTHING
        """
    )

    # Existing channel dropdown services become editable DB rows. Their icons are
    # imported into the shared media volume by the backend bootstrap seeder.
    op.execute(
        """
        INSERT INTO social_links
            (service_key, name, url, description, sort_order, is_active, created_at, updated_at)
        VALUES
            ('twitch', 'Twitch', '#', '', 10, true, now(), now()),
            ('telegram', 'Telegram', '#', '', 20, true, now(), now()),
            ('youtube', 'YouTube', '#', '', 30, true, now(), now()),
            ('boosty', 'Boosty', '#', '', 40, true, now(), now()),
            ('discord', 'Discord', '#', '', 50, true, now(), now())
        ON CONFLICT (service_key) DO NOTHING
        """
    )

    op.drop_column("game_metadata_igdb", "cover_url")
    op.drop_column("stream_recordings", "thumbnail_url")


def downgrade() -> None:
    op.add_column("stream_recordings", sa.Column("thumbnail_url", sa.Text(), nullable=True))
    op.add_column("game_metadata_igdb", sa.Column("cover_url", sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE stream_recordings AS recording
        SET thumbnail_url = (
            SELECT asset.url
            FROM stream_recording_media AS link
            JOIN media_assets AS asset ON asset.id = link.asset_id
            WHERE link.recording_id = recording.id
              AND link.role = 'twitch_preview'
            LIMIT 1
        )
        """
    )
    op.execute(
        """
        UPDATE game_metadata_igdb AS metadata
        SET cover_url = (
            SELECT asset.url
            FROM game_media_assets AS link
            JOIN media_assets AS asset ON asset.id = link.asset_id
            WHERE link.game_id = metadata.game_id
              AND link.role = 'cover'
              AND link.source = 'igdb'
            LIMIT 1
        )
        """
    )

    op.drop_index("ix_social_links_active_order", table_name="social_links")
    op.drop_table("social_links")
    op.drop_index(
        "ix_telegram_announcement_media_asset_id",
        table_name="telegram_announcement_media",
    )
    op.drop_table("telegram_announcement_media")
    op.drop_index(
        "ix_stream_recording_media_asset_id",
        table_name="stream_recording_media",
    )
    op.drop_table("stream_recording_media")
    op.drop_index("ix_game_media_assets_asset_id", table_name="game_media_assets")
    op.drop_table("game_media_assets")
    op.drop_index("ix_media_assets_sha256", table_name="media_assets")
    op.drop_index("ix_media_assets_source", table_name="media_assets")
    op.drop_table("media_assets")
