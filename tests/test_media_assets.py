"""Validation and storage-path safety for the shared media library."""

import asyncio
import hashlib

import pytest

from database.models import MediaAsset
from services.media_asset_service import (
    _image_extension,
    asset_file_path,
    create_file_asset,
    validate_media_url,
)


def test_media_url_accepts_http_and_https_only():
    assert validate_media_url(" https://example.test/cover.jpg ") == (
        "https://example.test/cover.jpg"
    )
    with pytest.raises(ValueError):
        validate_media_url("javascript:alert(1)")
    with pytest.raises(ValueError):
        validate_media_url("https://user:secret@example.test/image.png")


def test_upload_type_is_verified_from_image_signature():
    mime_type, extension = _image_extension(
        b"\x89PNG\r\n\x1a\nfake-image"
    )
    assert mime_type == "image/png"
    assert extension == ".png"

    with pytest.raises(ValueError, match="Поддерживаются"):
        _image_extension(b"<svg onload='alert(1)'>")


def test_storage_key_cannot_escape_media_root():
    asset = MediaAsset(storage_kind="file", storage_key="../secret.txt")
    with pytest.raises(ValueError, match="путь"):
        asset_file_path(asset)


def test_same_photo_bytes_reuse_the_existing_asset():
    data = b"\x89PNG\r\n\x1a\nsame-photo"
    existing = MediaAsset(
        id=19,
        storage_kind="file",
        storage_key="ab/existing.png",
        sha256=hashlib.sha256(data).hexdigest(),
    )

    class Result:
        def scalar_one_or_none(self):
            return existing

    class Session:
        async def execute(self, _query):
            return Result()

    result = asyncio.run(
        create_file_asset(
            Session(),
            data=data,
            filename="telegram-photo.png",
            source="telegram",
        )
    )
    assert result is existing
