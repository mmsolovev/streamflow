"""SQL helpers and read queries for managed media assets."""

from __future__ import annotations

from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_backend_settings
from database.models import GameMediaAsset, MediaAsset, SocialLink
from services.media_asset_service import public_asset_url


def _asset_url_expression():
    prefix = get_backend_settings().backend_api_prefix.rstrip("/")
    return case(
        (
            MediaAsset.storage_kind == "url",
            MediaAsset.url,
        ),
        else_=func.concat(
            prefix,
            "/media/assets/",
            cast(MediaAsset.id, String),
            "/content",
        ),
    )


def game_cover_url_expression(game_id_column):
    return (
        select(_asset_url_expression())
        .select_from(GameMediaAsset)
        .join(MediaAsset, MediaAsset.id == GameMediaAsset.asset_id)
        .where(
            GameMediaAsset.game_id == game_id_column,
            GameMediaAsset.role == "cover",
        )
        .order_by(
            case(
                (GameMediaAsset.source == "manual", 0),
                (GameMediaAsset.source == "igdb", 1),
                else_=2,
            ),
            GameMediaAsset.id.desc(),
        )
        .limit(1)
        .correlate_except(GameMediaAsset, MediaAsset)
        .scalar_subquery()
    )


async def list_social_links(
    session: AsyncSession, *, include_inactive: bool = False
) -> list[dict]:
    query = (
        select(SocialLink, MediaAsset)
        .outerjoin(MediaAsset, MediaAsset.id == SocialLink.icon_asset_id)
        .order_by(SocialLink.sort_order, SocialLink.id)
    )
    if not include_inactive:
        query = query.where(SocialLink.is_active.is_(True))
    result = await session.execute(query)
    return [
        {
            "id": int(link.id),
            "service_key": link.service_key,
            "name": link.name,
            "url": link.url,
            "description": link.description or "",
            "icon_url": public_asset_url(asset),
            "sort_order": int(link.sort_order),
            "is_active": bool(link.is_active),
        }
        for link, asset in result.all()
    ]
