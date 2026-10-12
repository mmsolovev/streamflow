"""Ручная проверка и внедрение ссылки на VOD в анонс Telegram-канала.

Нужен, когда автоматика не сработала: запись вышла, а в посте ссылки нет.
Позволяет посмотреть, какие посты вообще считаются кандидатами, и вручную
добавить ссылку конкретному посту.

Запуск:
    .venv\\Scripts\\python.exe utils\\telegram_vod_link.py --dry-run
    .venv\\Scripts\\python.exe utils\\telegram_vod_link.py --dry-run --message-id 777

    # без --dry-run пост реально правится:
    .venv\\Scripts\\python.exe utils\\telegram_vod_link.py --message-id 777

    # выбрать пост по id из telegram_announcements (а не по message_id):
        --announcement-id 25 --vod-url https://www.twitch.tv/videos/2889608958

    # проверить конкретный стрим:
    .venv\\Scripts\\python.exe utils\\telegram_vod_link.py --stream-id 123456789

По умолчанию скрипт ничего не меняет: без явного --message-id и без --apply
он только печатает кандидатов.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from aiogram import Bot  # noqa: E402
from aiogram.exceptions import TelegramBadRequest  # noqa: E402
from aiogram.types import LinkPreviewOptions, MessageEntity  # noqa: E402

import config.settings as settings  # noqa: E402
from database.db import AsyncSessionLocal  # noqa: E402
from telegram import announcements, vod_jobs  # noqa: E402
from telegram.matcher import build_channel_link_matcher, pick_candidate  # noqa: E402
from telegram.service import TelegramService  # noqa: E402
from telegram.templates import (  # noqa: E402
    build_finished_entities,
    fit_entities,
    fit_to_media_limit,
    media_text_limit,
)
from telegram.vod_service import VodLookupError, fetch_vod_for_stream  # noqa: E402


def describe(post: Any) -> str:
    text = post.caption_snapshot or post.text_snapshot or ""
    preview = " ".join(text.split())[:80]
    return (
        f"  message_id={post.message_id}  id={post.id}  status={post.status}  "
        f"media={post.media_kind or '-'}  posted_at={post.posted_at}\n"
        f"    {preview}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Показать кандидатов анонса и, по --apply, добавить ссылку на VOD.",
    )
    parser.add_argument(
        "--message-id",
        type=int,
        help="Править именно этот пост по message_id.",
    )
    parser.add_argument(
        "--announcement-id",
        type=int,
        dest="announcement_id",
        help=(
            "Править пост по id из telegram_announcements. Это НЕ message_id "
            "из Telegram: у поста 25 в таблице message_id может быть совсем "
            "другим, и путать их легко."
        ),
    )
    parser.add_argument("--stream-id", help="Twitch stream_id для поиска VOD.")
    parser.add_argument("--vod-url", help="Готовая ссылка на VOD вместо поиска в архиве.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Реально править пост. Без флага скрипт только печатает.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Править даже пост со статусом skipped (обход защиты от ручных правок).",
    )
    args = parser.parse_args()

    service = TelegramService()
    if not settings.TELEGRAM_ENABLED:
        print("TELEGRAM_ENABLED=false — скрипт всё равно разбирается с настройками вручную.")

    chat_id = service.chat_id
    matcher = build_channel_link_matcher(
        settings.TELEGRAM_CHANNEL_URL,
        settings.TELEGRAM_LINK_DOMAINS,
    )
    print(f"Канал: chat_id={chat_id}, стример={service.channel_login}")
    print(f"Ссылка на канал: {settings.TELEGRAM_CHANNEL_URL}\n")

    vod_urls: list[str] = []
    if args.vod_url:
        vod_urls = [args.vod_url]
    elif args.stream_id:
        print(f"Ищу VOD для stream_id={args.stream_id}…")
        import aiohttp

        async with aiohttp.ClientSession() as http:
            try:
                vod = await fetch_vod_for_stream(
                    session=http,
                    channel_login=service.channel_login,
                    stream_id=args.stream_id,
                    client_id=settings.CLIENT_ID,
                )
            except VodLookupError as exc:
                print(f"  Ошибка поиска VOD: {exc}")
                return
        if not vod or not vod.get("url"):
            print("  VOD не найден в архиве канала.")
            return
        vod_urls = [vod["url"]]
        print(f"  Найдено: {vod['url']} ({vod.get('duration_minutes')} мин)")
    else:
        print("Ссылка на VOD не задана (--stream-id или --vod-url).")
        print("Показываю только кандидатов.\n")

    async with AsyncSessionLocal() as session:
        if args.announcement_id:
            post = await announcements.get_by_id(session, args.announcement_id)
            if post is None:
                print(f"\nАнонс id={args.announcement_id} не найден в telegram_announcements.")
                print("Проверьте id: это НЕ message_id из Telegram.")
                return
            print(f"\nЦелевой пост:\n{describe(post)}")
            urls = vod_urls or await vod_jobs.resolved_urls(session, post.id)
        elif args.message_id:
            post = await announcements.get_by_chat_message(
                session,
                chat_id=chat_id,
                message_id=args.message_id,
            )
            if post is None:
                print(f"\nПост {args.message_id} не найден в telegram_announcements.")
                print("Если пост создан до запуска бота, запиши его вручную (см. --help).")
                return
            print(f"\nЦелевой пост:\n{describe(post)}")
            urls = vod_urls or await vod_jobs.resolved_urls(session, post.id)
        else:
            from datetime import datetime, timedelta, timezone

            since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)
            posts = await announcements.recent_posts(session, chat_id=chat_id, posted_after=since)
            print(f"Постов в БД за 3 дня: {len(posts)}")
            for post in posts:
                print(describe(post))

            bound = await announcements.recent_bound_ids(session, chat_id=chat_id, posted_after=since)
            candidates = [
                {
                    "id": post.id,
                    "message_id": post.message_id,
                    "posted_at": post.posted_at,
                    "text_snapshot": post.text_snapshot,
                    "caption_snapshot": post.caption_snapshot,
                    "is_forward": post.is_forward,
                }
                for post in posts
            ]
            chosen = pick_candidate(
                candidates,
                matcher=matcher,
                started_at=datetime.now(timezone.utc).replace(tzinfo=None),
                ended_at=None,
                exclude_message_ids=bound,
            )
            print(f"\nКандидат по умолчанию: {chosen['message_id'] if chosen else 'нет'}")
            print("Укажи --message-id, чтобы выбрать вручную.")
            return

        if not urls:
            print("\nНет ссылок на VOD — нечего вставлять.")
            print("Передайте --stream-id <id> или --vod-url <ссылка>.")
            return

        # Пост, который бот признал непригодным, ручной скрипт тоже не должен
        # молча переписывать: причину пропуска стример или оператор выбрали
        # осознанно. Обход делается явным --force.
        if (post.status == "skipped" or post.manually_edited) and not args.force:
            print(
                f"\nПост помечен как skipped"
                f"{' (правили вручную)' if post.manually_edited else ''}."
            )
            print("Бот такие посты больше не трогает. Если правка нужна — добавьте --force.")
            return

        text, entities = build_finished_entities(urls, post.media_kind)
        text = fit_to_media_limit(text, post.media_kind)
        entities = fit_entities(text, entities)
        print(f"\nНовый текст:\n{text}\n")
        print(f"С длиной {len(text)} символов (лимит "
              f"{media_text_limit(post.media_kind)}), сущностей: {len(entities)}.")
        if not args.apply:
            print("Это dry-run. Добавьте --apply, чтобы реально отредактировать пост.")
            return

        if not settings.TELEGRAM_BOT_TOKEN:
            print("\nНет TELEGRAM_BOT_TOKEN — правка невозможна.")
            return

        # parse_mode не передаётся: текст уходит с entities, а Telegram
        # запрещает смешивать entities с parse_mode. Словари из шаблона
        # превращаются в MessageEntity на границе с API.
        message_entities = [MessageEntity(**entity) for entity in entities] or None

        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

        # Сначала БД, потом API — ровно как в TelegramService._apply_edit.
        # Порядок обязателен: правка возвращается в канал апдейтом
        # `edited_channel_post`, и handlers.py узнаёт в ней эхо по совпадению
        # с `edited_text`. Записать его после вызова API означало бы, что в
        # момент обработки апдейта поле ещё пустое, бот решит, что пост
        # правили руками, и помечает его skipped(manual_edit) навсегда.
        await announcements.mark_edited(
            session,
            announcement_id=post.id,
            text=text,
        )
        await session.commit()

        try:
            if post.media_kind:
                await bot.edit_message_caption(
                    chat_id=post.chat_id,
                    message_id=post.message_id,
                    caption=text,
                    caption_entities=message_entities,
                )
            else:
                await bot.edit_message_text(
                    chat_id=post.chat_id,
                    message_id=post.message_id,
                    text=text,
                    entities=message_entities,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
        except TelegramBadRequest as exc:
            error = str(exc)
            print(f"\nTelegram отклонил правку: {error}")
            if "MESSAGE_ID_INVALID" in error:
                print(
                    "  Пост недоступен для редактирования: он мог быть удалён "
                    "после получения update, либо указан не тот chat_id."
                )
            print(
                f"  В БД статус уже записан как edited (text записан ДО вызова "
                f"API). Если правка не нужна — верните статус вручную:"
                f" UPDATE telegram_announcements SET status='observed', "
                f"edited_text=NULL, updated_at=NOW() WHERE id={post.id};"
            )
            return
        finally:
            if bot.session is not None:
                await bot.session.close()

        print(
            f"Пост {post.message_id} (id={post.id}) обновлён.\n"
            f"Ссылка на запись: {urls[0]}"
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nПрервано.")
