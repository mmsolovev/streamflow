"""Shared storage and typed associations for public media assets."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import MEDIA_STORAGE_DIR
from database.models import (
    GameMediaAsset,
    MediaAsset,
    SocialLink,
    StreamRecordingMedia,
)

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def media_storage_root() -> Path:
    configured = Path(MEDIA_STORAGE_DIR)
    return (configured if configured.is_absolute() else PROJECT_ROOT / configured).resolve()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def validate_media_url(value: str) -> str:
    url = (value or "").strip()
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Укажите корректный публичный HTTP(S) URL.")
    return url


def _image_extension(data: bytes) -> tuple[str, str]:
    signatures = (
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"),
    )
    actual = next((mime for signature, mime in signatures if data.startswith(signature)), None)
    if actual is None and len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        actual = "image/webp"
    if actual not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Поддерживаются только PNG, JPEG, WebP и GIF.")
    return actual, ALLOWED_IMAGE_TYPES[actual]


async def create_file_asset(
    session: AsyncSession,
    *,
    data: bytes,
    filename: str | None,
    source: str,
    created_by: int | None = None,
    source_ref: str | None = None,
) -> MediaAsset:
    if not data:
        raise ValueError("Файл пуст.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Максимальный размер изображения — 10 МБ.")
    mime_type, extension = _image_extension(data)
    digest = hashlib.sha256(data).hexdigest()

    existing_result = await session.execute(
        select(MediaAsset).where(
            MediaAsset.storage_kind == "file",
            MediaAsset.sha256 == digest,
        ).limit(1)
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        return existing

    storage_key = f"{digest[:2]}/{uuid.uuid4().hex}{extension}"
    root = media_storage_root()
    target = (root / PurePosixPath(storage_key)).resolve()
    if root not in target.parents:
        raise ValueError("Некорректный путь хранения файла.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    now = utcnow()
    asset = MediaAsset(
        storage_kind="file",
        storage_key=storage_key,
        original_filename=Path(filename or f"image{extension}").name,
        mime_type=mime_type,
        size_bytes=len(data),
        sha256=digest,
        source=source,
        source_ref=source_ref,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    session.add(asset)
    await session.flush()
    return asset


async def get_or_create_url_asset(
    session: AsyncSession,
    *,
    url: str,
    source: str,
    created_by: int | None = None,
) -> MediaAsset:
    normalized_url = validate_media_url(url)
    result = await session.execute(
        select(MediaAsset)
        .where(
            MediaAsset.storage_kind == "url",
            MediaAsset.url == normalized_url,
        )
        .limit(1)
    )
    asset = result.scalar_one_or_none()
    if asset is not None:
        return asset
    now = utcnow()
    asset = MediaAsset(
        storage_kind="url",
        url=normalized_url,
        source=source,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    session.add(asset)
    await session.flush()
    return asset


def public_asset_url(asset: MediaAsset | None) -> str | None:
    if asset is None:
        return None
    if asset.storage_kind == "url":
        return asset.url
    prefix = os.getenv("BACKEND_API_PREFIX", "/api/v1").rstrip("/")
    return f"{prefix}/media/assets/{int(asset.id)}/content"


def asset_file_path(asset: MediaAsset) -> Path:
    if asset.storage_kind != "file" or not asset.storage_key:
        raise ValueError("Медиафайл не хранится локально.")
    root = media_storage_root()
    path = (root / PurePosixPath(asset.storage_key)).resolve()
    if root not in path.parents:
        raise ValueError("Некорректный путь медиафайла.")
    return path


async def set_game_media(
    session: AsyncSession,
    *,
    game_id: int,
    asset: MediaAsset,
    role: str = "cover",
    source: str = "manual",
) -> None:
    result = await session.execute(
        select(GameMediaAsset).where(
            GameMediaAsset.game_id == int(game_id),
            GameMediaAsset.role == role,
            GameMediaAsset.source == source,
        )
    )
    link = result.scalar_one_or_none()
    if link is None:
        session.add(
            GameMediaAsset(
                game_id=int(game_id),
                asset_id=int(asset.id),
                role=role,
                source=source,
                created_at=utcnow(),
            )
        )
    else:
        link.asset_id = int(asset.id)
        session.add(link)
    await session.flush()


async def clear_game_media_source(
    session: AsyncSession,
    *,
    game_id: int,
    role: str,
    source: str,
) -> None:
    await session.execute(
        delete(GameMediaAsset).where(
            GameMediaAsset.game_id == int(game_id),
            GameMediaAsset.role == role,
            GameMediaAsset.source == source,
        )
    )


async def set_recording_media(
    session: AsyncSession,
    *,
    recording_id: int,
    asset: MediaAsset,
    role: str,
) -> None:
    result = await session.execute(
        select(StreamRecordingMedia).where(
            StreamRecordingMedia.recording_id == int(recording_id),
            StreamRecordingMedia.role == role,
        )
    )
    link = result.scalar_one_or_none()
    if link is None:
        session.add(
            StreamRecordingMedia(
                recording_id=int(recording_id),
                asset_id=int(asset.id),
                role=role,
                created_at=utcnow(),
            )
        )
    else:
        link.asset_id = int(asset.id)
        link.created_at = utcnow()
        session.add(link)
    await session.flush()


async def set_igdb_cover_url(
    session: AsyncSession, *, game_id: int, url: str | None
) -> None:
    if not url:
        return
    asset = await get_or_create_url_asset(session, url=url, source="igdb")
    await set_game_media(
        session, game_id=game_id, asset=asset, role="cover", source="igdb"
    )


async def set_recording_twitch_preview(
    session: AsyncSession, *, recording_id: int, url: str | None
) -> None:
    if not url:
        return
    asset = await get_or_create_url_asset(session, url=url, source="twitch")
    await set_recording_media(
        session,
        recording_id=recording_id,
        asset=asset,
        role="twitch_preview",
    )


async def get_game_cover_url(session: AsyncSession, game_id: int) -> str | None:
    result = await session.execute(
        select(MediaAsset)
        .join(GameMediaAsset, GameMediaAsset.asset_id == MediaAsset.id)
        .where(
            GameMediaAsset.game_id == int(game_id),
            GameMediaAsset.role == "cover",
        )
        .order_by(
            (GameMediaAsset.source == "manual").desc(),
            GameMediaAsset.id.desc(),
        )
    )
    assets = result.scalars().all()
    manual = next((asset for asset in assets if asset.source == "manual"), None)
    selected = manual or next((asset for asset in assets if asset.source == "igdb"), None)
    return public_asset_url(selected)


async def ensure_default_social_icons(session: AsyncSession) -> None:
    """Import shipped placeholder icons into persistent media storage once."""
    source_root = PROJECT_ROOT / "frontend" / "public" / "socials"
    links = (
        await session.execute(select(SocialLink).order_by(SocialLink.sort_order))
    ).scalars().all()
    for link in links:
        if link.icon_asset_id is not None:
            continue
        icon_path = source_root / f"{link.service_key}.png"
        if not icon_path.is_file():
            continue
        asset = await create_file_asset(
            session,
            data=icon_path.read_bytes(),
            filename=icon_path.name,
            source="seed_social",
            source_ref=link.service_key,
        )
        link.icon_asset_id = int(asset.id)
        link.updated_at = utcnow()
    await session.commit()
