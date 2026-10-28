"""Configurable post-stream message template."""

from __future__ import annotations

import re
from dataclasses import dataclass

from telegram.entities import build_link_entity, utf16_length
from telegram.templates import fit_entities, fit_to_media_limit, normalize_vod_urls


DEFAULT_HEADER = "Запись стрима:\n\n"
DEFAULT_ITEM = "🎥{{link}}~"
DEFAULT_SEPARATOR = "\n"
DEFAULT_FOOTER = ""
DEFAULT_LINK_LABEL = "TWITCH"
DEFAULT_DELAY_SECONDS = 660
PREVIEW_URL = "https://www.twitch.tv/videos/000000000"

TOKEN_PATTERN = re.compile(r"\{\{\s*([A-Za-z_]+)\s*\}\}")
SUPPORTED_TOKENS = {"link"}


@dataclass(frozen=True)
class PostEditTemplate:
    header: str = DEFAULT_HEADER
    item: str = DEFAULT_ITEM
    separator: str = DEFAULT_SEPARATOR
    footer: str = DEFAULT_FOOTER
    link_label: str = DEFAULT_LINK_LABEL

    @classmethod
    def defaults(cls) -> "PostEditTemplate":
        return cls()


def _tokens(value: str) -> set[str]:
    return {match.group(1) for match in TOKEN_PATTERN.finditer(value or "")}


def validate_template(template: PostEditTemplate) -> list[str]:
    errors: list[str] = []
    if not (template.item or "").strip():
        errors.append("Шаблон записи не может быть пустым")
    if not (template.link_label or "").strip():
        errors.append("Текст ссылки не может быть пустым")

    item_tokens = _tokens(template.item)
    if "link" not in item_tokens:
        errors.append("В шаблоне записи нужен токен {{link}}")

    for name, value in (
        ("заголовке", template.header),
        ("разделителе", template.separator),
        ("подвале", template.footer),
    ):
        if _tokens(value):
            errors.append(f"В {name} нельзя использовать токены")

    unknown = item_tokens - SUPPORTED_TOKENS
    if unknown:
        errors.append("Неизвестные токены: " + ", ".join(sorted(unknown)))

    return errors


def _render_item(item: str, url: str, label: str) -> tuple[str, list[dict]]:
    text = ""
    entities: list[dict] = []
    position = 0

    for match in TOKEN_PATTERN.finditer(item):
        text += item[position:match.start()]
        if match.group(1) == "link":
            offset = utf16_length(text)
            entities.append(build_link_entity(offset, utf16_length(label), url))
            text += label
        position = match.end()

    text += item[position:]
    return text, entities


def render_post(
    template: PostEditTemplate,
    vod_urls,
    *,
    media_kind: str | None = None,
) -> tuple[str, list[dict]]:
    errors = validate_template(template)
    if errors:
        raise ValueError("; ".join(errors))

    urls = normalize_vod_urls(vod_urls)
    if not urls:
        return "", []

    text = template.header or ""
    entities: list[dict] = []

    for index, url in enumerate(urls):
        if index:
            text += template.separator or ""
        item_text, item_entities = _render_item(template.item, url, template.link_label)
        base = utf16_length(text)
        text += item_text
        for entity in item_entities:
            shifted = dict(entity)
            shifted["offset"] = int(shifted["offset"]) + base
            entities.append(shifted)

    text += template.footer or ""
    fitted = fit_to_media_limit(text, media_kind)
    return fitted, fit_entities(fitted, entities)


def render_preview(
    template: PostEditTemplate,
    vod_urls,
    *,
    media_kind: str | None = None,
) -> tuple[str, list[dict]]:
    urls = normalize_vod_urls(vod_urls) or [PREVIEW_URL]
    return render_post(template, urls, media_kind=media_kind)


__all__ = [
    "DEFAULT_DELAY_SECONDS",
    "DEFAULT_FOOTER",
    "DEFAULT_HEADER",
    "DEFAULT_ITEM",
    "DEFAULT_LINK_LABEL",
    "DEFAULT_SEPARATOR",
    "PREVIEW_URL",
    "PostEditTemplate",
    "SUPPORTED_TOKENS",
    "render_post",
    "render_preview",
    "validate_template",
]
