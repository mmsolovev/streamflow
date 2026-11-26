"""Admin CRUD for links shown in the channel dropdown."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlalchemy import select

from backend.deps import AdminDep, SessionDep
from backend.repositories.media_assets import list_social_links
from backend.schemas.media import (
    MediaUrlIn,
    SocialLinkCreateIn,
    SocialLinkUpdateIn,
    SocialLinkView,
)
from database.models import SocialLink
from services.media_asset_service import (
    MAX_IMAGE_BYTES,
    create_file_asset,
    get_or_create_url_asset,
    public_asset_url,
)

router = APIRouter(prefix="/admin/links", tags=["admin-links"])


def _validate_link_url(value: str) -> str:
    value = (value or "").strip()
    if value == "#":
        return value
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise HTTPException(
            status_code=422,
            detail="Укажите ссылку с протоколом http:// или https://.",
        )
    return value


@router.get("", response_model=list[SocialLinkView])
async def list_admin_links(
    session: SessionDep, _admin: AdminDep
) -> list[SocialLinkView]:
    return [
        SocialLinkView(**item)
        for item in await list_social_links(session, include_inactive=True)
    ]


@router.post("", response_model=SocialLinkView)
async def create_link(
    body: SocialLinkCreateIn,
    session: SessionDep,
    admin: AdminDep,
) -> SocialLinkView:
    service_key = body.service_key.strip().lower()
    if not service_key or len(service_key) > 40:
        raise HTTPException(status_code=422, detail="Некорректный ключ сервиса.")
    exists = await session.execute(
        select(SocialLink.id).where(SocialLink.service_key == service_key)
    )
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Такой ключ сервиса уже существует.")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Укажите название сервиса.")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    link = SocialLink(
        service_key=service_key,
        name=name,
        url=_validate_link_url(body.url),
        description=body.description.strip(),
        sort_order=body.sort_order,
        is_active=body.is_active,
        created_at=now,
        updated_at=now,
    )
    session.add(link)
    await session.commit()
    await session.refresh(link)
    return SocialLinkView(
        id=int(link.id),
        service_key=link.service_key,
        name=link.name,
        url=link.url,
        description=link.description,
        icon_url=None,
        sort_order=link.sort_order,
        is_active=link.is_active,
    )


@router.patch("/{link_id}", response_model=SocialLinkView)
async def update_link(
    link_id: int,
    body: SocialLinkUpdateIn,
    session: SessionDep,
    _admin: AdminDep,
) -> SocialLinkView:
    link = await session.get(SocialLink, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Ссылка не найдена.")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        name = (changes["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Укажите название сервиса.")
        link.name = name
    if "url" in changes:
        link.url = _validate_link_url(changes["url"] or "#")
    if "description" in changes:
        link.description = (changes["description"] or "").strip()
    if "sort_order" in changes and changes["sort_order"] is not None:
        link.sort_order = changes["sort_order"]
    if "is_active" in changes and changes["is_active"] is not None:
        link.is_active = changes["is_active"]
    from services.media_asset_service import utcnow

    link.updated_at = utcnow()
    await session.commit()
    await session.refresh(link)
    items = await list_social_links(session, include_inactive=True)
    return SocialLinkView(**next(item for item in items if item["id"] == link_id))


@router.delete("/{link_id}", status_code=204)
async def delete_link(
    link_id: int,
    session: SessionDep,
    _admin: AdminDep,
) -> None:
    link = await session.get(SocialLink, link_id)
    if link is not None:
        await session.delete(link)
        await session.commit()


@router.put("/{link_id}/icon/url")
async def set_link_icon_url(
    link_id: int,
    body: MediaUrlIn,
    session: SessionDep,
    admin: AdminDep,
) -> dict:
    link = await session.get(SocialLink, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Ссылка не найдена.")
    try:
        asset = await get_or_create_url_asset(
            session,
            url=body.url,
            source="social",
            created_by=admin.user_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    link.icon_asset_id = int(asset.id)
    from services.media_asset_service import utcnow

    link.updated_at = utcnow()
    await session.commit()
    return {"id": link_id, "icon_url": public_asset_url(asset)}


@router.post("/{link_id}/icon/file")
async def upload_link_icon(
    link_id: int,
    session: SessionDep,
    admin: AdminDep,
    file: UploadFile = File(...),
) -> dict:
    link = await session.get(SocialLink, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Ссылка не найдена.")
    try:
        asset = await create_file_asset(
            session,
            data=await file.read(MAX_IMAGE_BYTES + 1),
            filename=file.filename,
            source="social",
            created_by=admin.user_id,
        )
    except ValueError as error:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    link.icon_asset_id = int(asset.id)
    from services.media_asset_service import utcnow

    link.updated_at = utcnow()
    await session.commit()
    return {"id": link_id, "icon_url": public_asset_url(asset)}


@router.delete("/{link_id}/icon", status_code=204)
async def delete_link_icon(
    link_id: int,
    session: SessionDep,
    _admin: AdminDep,
) -> None:
    link = await session.get(SocialLink, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Ссылка не найдена.")
    link.icon_asset_id = None
    from services.media_asset_service import utcnow

    link.updated_at = utcnow()
    await session.commit()
