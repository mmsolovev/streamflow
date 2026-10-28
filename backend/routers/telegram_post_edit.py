"""Admin API for the Telegram post-stream editing section."""
from __future__ import annotations

from datetime import datetime
from html import escape

import aiohttp
from fastapi import APIRouter, HTTPException, Query, status

import config.settings as settings
from backend.deps import EditorDep, SessionDep
from backend.repositories import telegram_post_edit as repo
from backend.schemas.telegram_post_edit import (
    ActionAcceptedOut,
    AnnouncementOption,
    PostEditRunView,
    PostEditSettingsPatch,
    PostEditSettingsView,
    PostStreamView,
    PreviewView,
    RunActionIn,
    SetTargetIn,
    VodCheckOut,
)
from database.models import TelegramAnnouncement, TelegramAnnouncementVod
from telegram import announcements, post_edit, post_edit_store, vod_jobs
from telegram.entities import utf16_to_index
from telegram.vod_service import fetch_vod_for_stream

router = APIRouter(prefix="/admin/telegram/post-stream", tags=["telegram-post-stream"])


def _settings_view(row) -> PostEditSettingsView:
    return PostEditSettingsView(
        enabled=row.enabled,
        delay_seconds=row.delay_seconds,
        header=row.header,
        item=row.item,
        separator=row.separator,
        footer=row.footer,
        link_label=row.link_label,
        updated_at=row.updated_at,
    )


def _run_view(row) -> PostEditRunView:
    run, stream = row
    return PostEditRunView(
        id=run.id,
        stream_id=run.stream_id,
        stream_title=stream.title if stream else None,
        stream_started_at=run.stream_started_at,
        stream_ended_at=run.stream_ended_at,
        announcement_id=run.announcement_id,
        status=run.status,
        vod_url=run.vod_url,
        last_error=run.last_error,
        selected_by_admin=bool(run.selected_by_admin),
        check_at=run.check_at,
        applied_at=run.applied_at,
        undone_at=run.undone_at,
    )


def _announcement_view(post: TelegramAnnouncement) -> AnnouncementOption:
    return AnnouncementOption(
        id=post.id,
        message_id=post.message_id,
        posted_at=post.posted_at,
        media_kind=post.media_kind,
        status=post.status,
        manually_edited=bool(post.manually_edited),
        preview=repo.announcement_preview(post),
        link_urls=announcements.load_link_urls(post.link_urls),
    )


def _preview_html(text: str, entities: list[dict]) -> str:
    links = [
        entity for entity in entities
        if entity.get("type") == "text_link" and entity.get("url")
    ]
    if not links:
        return escape(text)

    parts: list[str] = []
    cursor = 0
    for entity in sorted(links, key=lambda item: int(item.get("offset", 0))):
        start = utf16_to_index(text, int(entity.get("offset", 0)))
        end = utf16_to_index(text, int(entity.get("offset", 0)) + int(entity.get("length", 0)))
        if start < cursor or end > len(text) or end <= start:
            continue
        parts.append(escape(text[cursor:start]))
        parts.append(
            f'<a href="{escape(str(entity["url"]), quote=True)}" target="_blank" rel="noreferrer">'
            f"{escape(text[start:end])}</a>"
        )
        cursor = end

    parts.append(escape(text[cursor:]))
    return "".join(parts)


async def _build_state(session, *, run_id: int | None) -> PostStreamView:
    settings_row = await repo.get_settings(session)
    target_row = await repo.get_run(session, run_id) if run_id else await repo.latest_run(session)
    runs = await repo.list_runs(session)
    posts = await repo.list_announcements(session)
    template = post_edit_store.template_from_settings(settings_row)

    media_kind = None
    urls: list[str] = []
    if target_row is not None:
        run, _stream = target_row
        if run.announcement_id is not None:
            post = await repo.get_announcement(session, run.announcement_id)
            if post is not None and all(item.id != post.id for item in posts):
                posts.append(post)
            media_kind = post.media_kind if post else None
            urls = await repo.urls_for_announcement(session, run.announcement_id)
        elif run.vod_url:
            urls = [run.vod_url]

    try:
        text, entities = post_edit.render_preview(template, urls, media_kind=media_kind)
        preview_html = _preview_html(text, entities)
    except ValueError as exc:
        text = f"Ошибка шаблона: {exc}"
        preview_html = escape(text)

    await session.commit()

    return PostStreamView(
        settings=_settings_view(settings_row),
        target=_run_view(target_row) if target_row is not None else None,
        runs=[_run_view(row) for row in runs],
        announcements=[_announcement_view(post) for post in posts],
        preview=PreviewView(
            text=text,
            html=preview_html,
            media_kind=media_kind,
        ),
    )


@router.get("", response_model=PostStreamView)
async def get_post_stream(
    session: SessionDep,
    _user: EditorDep,
    run_id: int | None = Query(None),
) -> PostStreamView:
    return await _build_state(session, run_id=run_id)


@router.patch("/settings", response_model=PostEditSettingsView)
async def update_settings(
    body: PostEditSettingsPatch,
    session: SessionDep,
    user: EditorDep,
) -> PostEditSettingsView:
    row = await repo.get_settings(session)
    values = body.model_dump(exclude_unset=True)
    for key, value in values.items():
        if value is not None:
            setattr(row, key, value)

    template = post_edit_store.template_from_settings(row)
    errors = post_edit.validate_template(template)
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))

    row.updated_at = datetime.utcnow()
    row.updated_by_user_id = user.id
    if "delay_seconds" in values:
        await post_edit_store.reschedule_waiting(session, row.delay_seconds)
    await session.commit()
    return _settings_view(row)


@router.post("/settings/reset", response_model=PostEditSettingsView)
async def reset_settings(session: SessionDep, user: EditorDep) -> PostEditSettingsView:
    row = await repo.get_settings(session)
    row.delay_seconds = post_edit.DEFAULT_DELAY_SECONDS
    row.header = post_edit.DEFAULT_HEADER
    row.item = post_edit.DEFAULT_ITEM
    row.separator = post_edit.DEFAULT_SEPARATOR
    row.footer = post_edit.DEFAULT_FOOTER
    row.link_label = post_edit.DEFAULT_LINK_LABEL
    row.updated_at = datetime.utcnow()
    row.updated_by_user_id = user.id
    await post_edit_store.reschedule_waiting(session, row.delay_seconds)
    await session.commit()
    return _settings_view(row)


@router.put("/target", response_model=ActionAcceptedOut)
async def set_target(
    body: SetTargetIn,
    session: SessionDep,
    _user: EditorDep,
) -> ActionAcceptedOut:
    row = await repo.get_run(session, body.run_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Стрим не найден.")
    run, _stream = row
    if run.status in {"applying", "edited"} and run.announcement_id != body.announcement_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Сначала отмените правку текущего поста.",
        )

    post = await repo.get_announcement(session, body.announcement_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден.")
    if post.status == "skipped" or post.manually_edited:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот пост изменён вручную и недоступен для правки.",
        )

    settings_row = await repo.get_settings(session)
    await repo.set_target(
        session,
        run_id=body.run_id,
        announcement_id=body.announcement_id,
        delay_seconds=settings_row.delay_seconds,
    )
    await session.commit()
    return ActionAcceptedOut(accepted=True, message="Пост выбран.")


@router.post("/publish", response_model=ActionAcceptedOut)
async def publish_now(
    body: RunActionIn,
    session: SessionDep,
    _user: EditorDep,
) -> ActionAcceptedOut:
    row = await repo.get_run(session, body.run_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Стрим не найден.")
    run, _stream = row
    if run.announcement_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сначала выберите пост.")
    if run.status in {"applying"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Правка уже выполняется.")
    if run.status == "edited":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Пост уже отредактирован.")

    post = await repo.get_announcement(session, run.announcement_id)
    if post is None or post.manually_edited or post.status == "skipped":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пост изменён вручную и недоступен для правки.",
        )

    await vod_jobs.request_publish(session, run.id)
    await session.commit()
    return ActionAcceptedOut(accepted=True, message="Публикация поставлена в очередь.")


@router.post("/undo", response_model=ActionAcceptedOut)
async def undo(
    body: RunActionIn,
    session: SessionDep,
    _user: EditorDep,
) -> ActionAcceptedOut:
    row = await repo.get_run(session, body.run_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Стрим не найден.")
    run, _stream = row
    operation = await repo.latest_applied_operation(session, run.id)
    if operation is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет правки для отмены.")
    if run.status == "applying":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Правка уже выполняется.")

    await vod_jobs.request_undo(session, run.id)
    await session.commit()
    return ActionAcceptedOut(accepted=True, message="Отмена поставлена в очередь.")


@router.post("/restore", response_model=ActionAcceptedOut)
async def restore_original(
    body: RunActionIn,
    session: SessionDep,
    _user: EditorDep,
) -> ActionAcceptedOut:
    row = await repo.get_run(session, body.run_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Стрим не найден.")
    run, _stream = row
    if run.announcement_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сначала выберите пост.")
    if run.status == "applying":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Правка уже выполняется.")

    post = await repo.get_announcement(session, run.announcement_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден.")
    if post.manually_edited or post.status == "skipped":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пост изменён вручную и недоступен для восстановления.",
        )
    text, entities = announcements.original_of(post)
    if text is None and not entities:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Оригинал поста не сохранён.")

    await vod_jobs.request_restore(session, run.id)
    await session.commit()
    return ActionAcceptedOut(accepted=True, message="Восстановление оригинала поставлено в очередь.")


@router.post("/check-vod", response_model=VodCheckOut)
async def check_vod(
    body: RunActionIn,
    session: SessionDep,
    _user: EditorDep,
) -> VodCheckOut:
    row = await repo.get_run(session, body.run_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Стрим не найден.")
    run, _stream = row
    checked_at = datetime.utcnow()

    if not settings.CLIENT_ID or not settings.TWITCH_PRIMARY_CHANNEL:
        run.last_checked_at = checked_at
        await session.commit()
        return VodCheckOut(
            available=False,
            error="Twitch API не настроен",
            checked_at=checked_at,
        )

    try:
        async with aiohttp.ClientSession() as http:
            vod = await fetch_vod_for_stream(
                session=http,
                channel_login=settings.TWITCH_PRIMARY_CHANNEL,
                stream_id=run.stream_id,
                client_id=settings.CLIENT_ID,
            )
    except Exception as exc:
        run.last_checked_at = checked_at
        await session.commit()
        return VodCheckOut(
            available=False,
            error=str(exc) or type(exc).__name__,
            checked_at=checked_at,
        )

    run.last_checked_at = checked_at
    await session.commit()
    if vod is None or not vod.get("url"):
        return VodCheckOut(
            available=False,
            error="VOD not found in channel archive",
            checked_at=checked_at,
        )
    return VodCheckOut(
        available=True,
        vod_url=vod.get("url"),
        duration_minutes=vod.get("duration_minutes"),
        checked_at=checked_at,
    )
