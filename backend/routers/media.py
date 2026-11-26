"""Public endpoints for Twitch recordings and clips."""

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from backend.deps import EditorDep, SessionDep
from backend.repositories import media as repo
from backend.schemas.common import Page
from backend.schemas.media import (
    ClipView,
    MediaFilterOptions,
    MediaUrlIn,
    RecordingPreviewOut,
    RecordingView,
    SocialLinkView,
)
from database.models import MediaAsset, StreamRecording, StreamRecordingMedia
from services.media_asset_service import (
    MAX_IMAGE_BYTES,
    asset_file_path,
    create_file_asset,
    get_or_create_url_asset,
    public_asset_url,
    set_recording_media,
)
from sqlalchemy import select

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/filters", response_model=MediaFilterOptions)
async def list_media_filters(
    session: SessionDep,
    section: str = Query(..., pattern="^(recordings|clips)$"),
) -> MediaFilterOptions:
    result = await repo.list_filter_options(session, section=section)
    return MediaFilterOptions(**result)


@router.get("/social-links", response_model=list[SocialLinkView])
async def social_links(session: SessionDep) -> list[SocialLinkView]:
    from backend.repositories.media_assets import list_social_links

    return [
        SocialLinkView(**item)
        for item in await list_social_links(session)
    ]


@router.get("/assets/{asset_id}/content")
async def media_asset_content(asset_id: int, session: SessionDep):
    asset = await session.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Файл не найден.")
    if asset.storage_kind == "url":
        raise HTTPException(status_code=404, detail="Для внешней ссылки нет локального файла.")
    try:
        path: Path = asset_file_path(asset)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Файл не найден.") from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден.")
    return FileResponse(
        path,
        media_type=asset.mime_type or "application/octet-stream",
        filename=asset.original_filename,
        content_disposition_type="inline",
    )


@router.put(
    "/recordings/{recording_id}/preview/url",
    response_model=RecordingPreviewOut,
)
async def set_recording_preview_url(
    recording_id: int,
    body: MediaUrlIn,
    session: SessionDep,
    actor: EditorDep,
) -> RecordingPreviewOut:
    recording = await session.get(StreamRecording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Запись не найдена.")
    try:
        asset = await get_or_create_url_asset(
            session,
            url=body.url,
            source="manual",
            created_by=actor.user_id,
        )
        await set_recording_media(
            session,
            recording_id=recording_id,
            asset=asset,
            role="manual_preview",
        )
        await session.commit()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RecordingPreviewOut(
        recording_id=recording_id,
        thumbnail_url=public_asset_url(asset),
        message="Превью записи обновлено.",
    )


@router.post(
    "/recordings/{recording_id}/preview/file",
    response_model=RecordingPreviewOut,
)
async def upload_recording_preview(
    recording_id: int,
    session: SessionDep,
    actor: EditorDep,
    file: UploadFile = File(...),
) -> RecordingPreviewOut:
    recording = await session.get(StreamRecording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Запись не найдена.")
    try:
        data = await file.read(MAX_IMAGE_BYTES + 1)
        asset = await create_file_asset(
            session,
            data=data,
            filename=file.filename,
            source="manual",
            created_by=actor.user_id,
        )
        await set_recording_media(
            session,
            recording_id=recording_id,
            asset=asset,
            role="manual_preview",
        )
        await session.commit()
    except ValueError as error:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RecordingPreviewOut(
        recording_id=recording_id,
        thumbnail_url=public_asset_url(asset),
        message="Превью записи загружено.",
    )


@router.delete("/recordings/{recording_id}/preview", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recording_preview(
    recording_id: int,
    session: SessionDep,
    _actor: EditorDep,
) -> None:
    recording = await session.get(StreamRecording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Запись не найдена.")
    link = (
        await session.execute(
            select(StreamRecordingMedia).where(
                StreamRecordingMedia.recording_id == recording_id,
                StreamRecordingMedia.role == "manual_preview",
            )
        )
    ).scalar_one_or_none()
    if link is not None:
        await session.delete(link)
        await session.commit()


@router.get("/recordings", response_model=Page[RecordingView])
async def list_recordings(
    session: SessionDep,
    search: str | None = Query(None, max_length=100),
    sort: str = Query("date", pattern="^(date|views|title|duration)$"),
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    filters: list[str] = Query(default=[]),
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[RecordingView]:
    items, total, total_all = await repo.list_recordings(
        session,
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        direction=direction,
        filters=filters,
    )
    return Page[RecordingView](
        items=[RecordingView(**item) for item in items],
        total=total,
        total_all=total_all,
        limit=limit,
        offset=offset,
    )


@router.get("/clips", response_model=Page[ClipView])
async def list_clips(
    session: SessionDep,
    period: str = Query("week", pattern="^(day|week|month|all)$"),
    search: str | None = Query(None, max_length=100),
    sort: str = Query("views", pattern="^(date|views|title|duration)$"),
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    filters: list[str] = Query(default=[]),
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[ClipView]:
    items, total, total_all = await repo.list_clips(
        session,
        limit=limit,
        offset=offset,
        period=period,
        search=search,
        sort=sort,
        direction=direction,
        filters=filters,
    )
    return Page[ClipView](
        items=[ClipView(**item) for item in items],
        total=total,
        total_all=total_all,
        limit=limit,
        offset=offset,
    )
