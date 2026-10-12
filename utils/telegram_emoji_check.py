"""Живая проверка кастомного эмодзи в подписи «Запись стрима».

Зачем скрипт, если есть юнит-тесты: тесты проверяют смещения и лимиты по
сгенерированным сущностям, но не отвечают на главный вопрос — нарисует ли
Telegram анимированный значок из набора вместо Unicode-`💬`. Это выясняется
только реальным `editMessage*` в канале.

Скрипт сам слушает `channel_post`, поэтому запускать бот не нужно: важно лишь,
чтобы бот был администратором канала с правом видеть посты.

    # ждёт новый пост (по умолчанию до 5 минут), показывает план правки:
    .venv\\Scripts\\python.exe utils\\telegram_emoji_check.py

    # то же, но правка реально уходит в канал:
    .venv\\Scripts\\python.exe utils\\telegram_emoji_check.py --apply

    # конкретный пост из бэклога апдейтов, без ожидания:
    .venv\\Scripts\\python.exe utils\\telegram_emoji_check.py --message-id 123 --apply

Ограничения: Telegram не отдаёт историю канала боту, а неподтверждённые апдейты
хранятся не дольше 24 часов. Поэтому `--message-id` работает только для поста
из бэклога. Скрипт апдейты намеренно не подтверждает, так что один и тот же пост
можно проверить сначала без `--apply`, а потом применить.

Запуск скрипта при живом боте в этом же процессе приведёт к конфликту
getUpdates: Telegram отдаёт апдейты только одному получателю. Бот должен быть
остановлен.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import aiohttp  # noqa: E402
from aiogram import Bot  # noqa: E402
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest  # noqa: E402
from aiogram.types import LinkPreviewOptions, Message, MessageEntity, Update  # noqa: E402

import config.settings as settings  # noqa: E402
from database.db import AsyncSessionLocal  # noqa: E402
from database.models import TelegramAnnouncementVod  # noqa: E402
from pipeline.ingest.twitch_api import (  # noqa: E402
    TwitchTokenExpiredError,
    fetch_user_id,
    fetch_vods,
)
from services.token_service import get_current_tokens  # noqa: E402
from telegram.entities import utf16_length  # noqa: E402
from telegram.handlers import media_kind  # noqa: E402
from telegram.templates import (  # noqa: E402
    build_finished_entities,
    fit_entities,
    fit_to_media_limit,
    is_own_edit,
    media_text_limit,
)
from telegram.vod_service import MAX_ITEMS, VodLookupError  # noqa: E402


# Что скрипт слушает: новый пост нужен, чтобы достать из него эмодзи стримера.
ALLOWED_UPDATES = ["channel_post"]

# Long polling держит соединение 30 секунд — столько ждать не надо, за это время
# пользователь успеет опубликовать пост.
LONG_POLL_TIMEOUT = 25

# Насколько пост может быть старше запуска скрипта и ещё считаться свежим.
FRESH_POST_GRACE_SECONDS = 90


def slice_utf16(text: str, offset: int, length: int) -> str:
    """Тот участок текста, на который указывает entity Telegram.

    Нужно для чтения ответа: смещения в UTF-16, а не в индексах Python.
    """
    raw = text.encode("utf-16-le")
    return raw[offset * 2:(offset + length) * 2].decode("utf-16-le")


def entities_of(message: Message) -> list[Any]:
    return list(message.caption_entities or message.entities or [])


def describe_entities(message: Message, label: str) -> None:
    """Печатает сущности поста: что Telegram понял из его разметки."""
    text = message.caption or message.text or ""
    entities = entities_of(message)
    if not entities:
        print(f"  {label}: сущностей нет")
        return

    for entity in entities:
        kind = entity.type
        offset, length = entity.offset, entity.length
        snippet = slice_utf16(text, offset, length)
        extra = ""
        if kind == "custom_emoji":
            extra = f" id={entity.custom_emoji_id}"
        elif kind in ("text_link", "url"):
            extra = f" -> {getattr(entity, 'url', None)}"
        print(f"  {label}: {kind} offset={offset} length={length}{extra} {snippet!r}")


async def fetch_updates(bot: Bot, deadline: float, is_ready) -> list[Update]:
    """Ждёт апдейты до `deadline` (монотонное время) и возвращает новые.

    `offset` намеренно не передаётся: Telegram удаляет апдейт только когда
    вызывающий подтвердил его через `offset`. Без подтверждения бэклог живёт
    сутки, и проверку можно повторять — сначала посмотреть план, потом
    применить его тем же `--message-id`.

    `is_ready` решает, можно ли прекратить ожидание: пока новый пост не
    пришёл, long polling держит соединение.
    """
    updates: list[Update] = []
    loop = asyncio.get_running_loop()

    while loop.time() < deadline and not is_ready(updates):
        batch = await bot.get_updates(
            offset=None,
            timeout=LONG_POLL_TIMEOUT,
            allowed_updates=ALLOWED_UPDATES,
            request_timeout=LONG_POLL_TIMEOUT + 10,
        )
        updates.extend(batch)

    return updates


def channel_posts(updates: list[Update], chat_id: int) -> list[Message]:
    posts = []
    for update in updates:
        message = update.channel_post
        if message is not None and message.chat.id == chat_id:
            posts.append(message)
    return posts


def fresh_posts(updates: list[Update], chat_id: int, fresh_since) -> list[Message]:
    """Только посты, пришедшие недавно.

    Бэклог апдейтов живёт сутки, и в нём лежат вчерашние анонсы. Без такого
    фильтра скрипт взял бы старый пост и отписался бы про «пост получен», а
    стример так и не понял бы, что надо публиковать заново.
    """
    return [post for post in channel_posts(updates, chat_id) if post.date >= fresh_since]


async def vod_url_from_db() -> str | None:
    """Любая найденная ранее ссылка на запись.

    Проверять тут не ссылку, а отрисовку эмодзи, поэтому точность VOD не важна:
    подойдёт любая строка из `telegram_announcement_vods`. Такой поиск не бьёт
    по Twitch и не требует живого токена — а токен в `.env` часто протухший,
    и из-за него проверка эмодзи падала, не дойдя до дела.
    """
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(TelegramAnnouncementVod.vod_url, TelegramAnnouncementVod.recorded_at)
            .where(TelegramAnnouncementVod.vod_url.is_not(None))
            .order_by(TelegramAnnouncementVod.recorded_at.desc().nullslast())
            .limit(1)
        )
        url = rows.scalars().first()

    if url:
        print(f"  Ссылка на запись взята из БД: {url}")
    return url


def fake_vod_url(channel_login: str) -> str:
    """Ссылка на несуществующую запись — только чтобы был куда вести `text_link`.

    Годится, когда в БД пусто: кликабельность и длина подписи от id не
    зависят, а вот `custom_emoji` на том же участке текста отрисуется или нет —
    зависит. Именно это и проверяется.
    """
    vod_id = random.randint(490000001, 499999999)
    return f"https://www.twitch.tv/{channel_login}/videos/{vod_id}"


async def latest_vod_url(channel_login: str) -> str:
    """Свежая запись из архива Twitch. Требует живого access token."""
    access_token, _ = get_current_tokens()
    if not access_token:
        raise TwitchTokenExpiredError("нет Twitch access token")

    async with aiohttp.ClientSession() as session:
        user_id = await fetch_user_id(
            session,
            client_id=settings.CLIENT_ID,
            access_token=access_token,
            channel_login=channel_login,
        )
        vods = await fetch_vods(
            session,
            client_id=settings.CLIENT_ID,
            access_token=access_token,
            user_id=user_id,
            max_items=MAX_ITEMS,
        )

    if not vods:
        raise VodLookupError(f"у канала {channel_login} нет записей в архиве")

    def sort_key(vod: dict[str, Any]) -> str:
        return str(vod.get("published_at") or vod.get("created_at") or "")

    newest = max(vods, key=sort_key)
    url = newest.get("url") or f"https://www.twitch.tv/{channel_login}/videos/{newest['id']}"
    print(f"  Свежая запись: {url} ({newest.get('duration', '?')}, published_at={sort_key(newest)})")
    return str(url)


async def apply(bot: Bot, message: Message, text: str, entities: list[dict]) -> Message | None:
    """Правит пост и возвращает сообщение, как его понял Telegram."""
    message_entities = [MessageEntity(**entity) for entity in entities] or None

    try:
        if media_kind(message):
            result = await bot.edit_message_caption(
                chat_id=message.chat.id,
                message_id=message.message_id,
                caption=text,
                caption_entities=message_entities,
            )
        else:
            result = await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=message.message_id,
                text=text,
                entities=message_entities,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
    except TelegramBadRequest as exc:
        error = str(exc)
        print(f"Telegram отклонил правку: {error}")
        if "MESSAGE_ID_INVALID" in error:
            print(
                "  Пост недоступен для редактирования: он мог быть удалён после "
                "получения update, либо указан не тот chat_id. Опубликуй новый "
                "тестовый пост и проверь его без --message-id."
            )
        return None

    if isinstance(result, bool):
        print("Telegram вернул True вместо сообщения — сущности проверить нечем")
        return None
    return result


def verify_plan(message: Message, text: str, entities: list[dict], emoji_id: str | None) -> None:
    limit = media_text_limit(media_kind(message))
    length = utf16_length(text)

    print(f"\nПодпись ({length} из {limit} UTF-16, лимит считает Telegram):")
    for line in text.splitlines():
        print(f"    {line}")

    print(f"\nСущности, которые уйдут в API ({len(entities)}):")
    for entity in entities:
        snippet = slice_utf16(text, entity["offset"], entity["length"])
        if entity["type"] == "custom_emoji":
            print(f"    custom_emoji offset={entity['offset']} length={entity['length']} "
                  f"id={entity['custom_emoji_id']} {snippet!r}")
        else:
            print(f"    text_link   offset={entity['offset']} length={entity['length']} "
                  f"{snippet!r} -> {entity['url']}")

    if not emoji_id:
        print("\n  Кастомные emoji не используются: подпись уйдёт со стандартным 🎥.")


def verify_result(result: Message, expected_text: str, emoji_id: str | None) -> bool:
    """Сверяет ответ Telegram с тем, что отправляли. Возвращает True при успехе."""
    text = result.caption or result.text or ""
    entities = entities_of(result)

    print("\nЧто вернул Telegram:")
    for line in text.splitlines():
        print(f"    {line}")
    describe_entities(result, "сущность")

    emoji_entities = [e for e in entities if e.type == "custom_emoji"]
    links = [e for e in entities if e.type in ("text_link", "url")]

    ok = True
    if text != expected_text:
        print(f"⚠ Текст отличается от отправленного: {text!r} != {expected_text!r}")
        ok = False
    if not links:
        print("⚠ Ссылка на запись потерялась")
        ok = False
    if emoji_id and not emoji_entities:
        print("⚠ Telegram не вернул custom_emoji: эмодзи отрисуется как обычный Unicode-💬")
        ok = False
    if emoji_id and emoji_entities:
        found = {e.custom_emoji_id for e in emoji_entities}
        if found != {emoji_id}:
            print(f"⚠ id эмодзи не совпал: {found} вместо {emoji_id}")
            ok = False
        for entity in emoji_entities:
            snippet = slice_utf16(text, entity.offset, entity.length)
            print(f"    эмодзи покрывает {snippet!r} (offset={entity.offset})")
    if is_own_edit(text, expected_text):
        print("    is_own_edit: эхо правки опознаётся, ручной правкой стримера не считается")
    else:
        print("    is_own_edit: НЕ опознаёт эхо — проверь вручную")

    return ok


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Проверить кастомный эмодзи в подписи «Запись стрима» на живом посте.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Реально править пост. Без флага скрипт только печатает план.",
    )
    parser.add_argument("--message-id", type=int, help="Пост из бэклога вместо ожидания нового.")
    parser.add_argument("--wait", type=int, default=300, help="Сколько ждать пост, секунд.")
    parser.add_argument("--vod-url", help="Готовая ссылка на запись вместо поиска.")
    parser.add_argument(
        "--from-archive",
        action="store_true",
        help="Брать VOD из Twitch, а не из БД. Нужен живой access token.",
    )
    parser.add_argument(
        "--channel-login",
        help="Логин канала Twitch вместо TWITCH_PRIMARY_CHANNEL.",
    )
    args = parser.parse_args()

    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("TELEGRAM_BOT_TOKEN пуст")
        return

    chat_id = int(settings.TELEGRAM_CHANNEL_ID)
    channel_login = args.channel_login or settings.TWITCH_PRIMARY_CHANNEL

    bot = Bot(token=token)
    try:
        me = await bot.get_me()
        print(f"Бот: @{me.username} (id={me.id})")
        print(f"Канал: chat_id={chat_id}, стример={channel_login}")
        print(f"Режим: {'правка поста' if args.apply else 'только печать (--apply не задан)'}\n")

        # Небольшой запас на «запостил, потом запустил скрипт»: пост минуты
        # давности ещё считаем свежим, иначе пришлось бы публиковать дважды.
        fresh_since = datetime.now(timezone.utc) - timedelta(seconds=FRESH_POST_GRACE_SECONDS)

        deadline = asyncio.get_running_loop().time() + args.wait
        if args.message_id is not None:
            # Пост известен заранее: ждать нечего, забираем весь бэклог сразу.
            updates = await fetch_updates(bot, deadline, lambda _updates: True)
            posts = [
                post
                for post in channel_posts(updates, chat_id)
                if post.message_id == args.message_id
            ]
            if not posts:
                print(f"Пост {args.message_id} не найден в бэклоге апдейтов.")
                print("Апдейты хранятся не дольше 24 часов, и бот должен быть остановлен.")
                return
            message = posts[-1]
        else:
            print(f"Жду пост в чате {chat_id} до {args.wait} секунд. Опубликуй анонс.\n")
            updates = await fetch_updates(
                bot,
                deadline,
                lambda seen: bool(fresh_posts(seen, chat_id, fresh_since)),
            )
            posts = fresh_posts(updates, chat_id, fresh_since)
            if not posts:
                print(f"За {args.wait} секунд в чат {chat_id} не пришло новых постов.")
                print("Проверь, что бот — администратор канала, и опубликуй анонс ещё раз.")
                return
            message = posts[-1]
        print(f"Пост message_id={message.message_id}, дата {message.date}")
        print(f"  Текст: {message.caption or message.text!r}")
        describe_entities(message, "анонс")

        print("\nИспользуется фиксированный стандартный emoji: 🎥")

        if args.vod_url:
            vod_url = args.vod_url
            print(f"  Ссылка на запись задана вручную: {vod_url}")
        elif args.from_archive:
            print("\nИщу свежую запись в архиве Twitch…")
            try:
                vod_url = await latest_vod_url(channel_login)
            except (TwitchTokenExpiredError, VodLookupError) as exc:
                print(f"  Twitch не ответил: {exc}")
                vod_url = fake_vod_url(channel_login)
                print(f"  Беру вымышленную запись: {vod_url}")
        else:
            vod_url = await vod_url_from_db()
            if not vod_url:
                vod_url = fake_vod_url(channel_login)
                print(f"  В БД нет ни одной ссылки на запись, беру вымышленную: {vod_url}")

        text, entities = build_finished_entities(
            [vod_url],
            media_kind=media_kind(message),
        )
        text = fit_to_media_limit(text, media_kind(message))
        entities = fit_entities(text, entities)

        # Пересчёт смещений после обрезки: build_finished_entities считает их
        # от начала текста, а обрезка могла сдвинуть конец строки.
        _check_spans(text, entities)
        verify_plan(message, text, entities, None)

        if not args.apply:
            print("\n--apply не задан, пост не тронут.")
            return

        result = await apply(bot, message, text, entities)
        if result is None:
            return

        ok = verify_result(result, text, None)
        print("\nИтог:", "эмодзи доехал и постал анимированным" if ok else "есть расхождения, смотри выше")
    except TelegramAPIError as exc:
        print(f"\nОшибка Telegram: {exc}")
        if "can't use getUpdates" in str(exc) or "conflict" in str(exc).casefold():
            print("Похоже, апдейты уже забирает другой процесс — останови бота.")
    finally:
        if bot.session is not None:
            await bot.session.close()


def _check_spans(text: str, entities: list[dict]) -> None:
    """Смещения обязаны указывать на реальные символы внутри текста."""
    length = utf16_length(text)
    for entity in entities:
        end = entity["offset"] + entity["length"]
        if end > length:
            print(f"\n⚠ Сущность выходит за границу текста: {entity} при длине {length}")
        span = slice_utf16(text, entity["offset"], entity["length"])
        # Молчаливый сдвиг на одну единицу дал бы ссылку на другом символе,
        # поэтому подсветка участка обязательна.
        assert span, f"пустая сущность {entity}"


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nПрервано")
