"""Диагностика Telegram-канала: узнать numeric chat_id и проверить токен.

Зачем: TELEGRAM_CHANNEL_ID для публичного канала известен как @username, но
надёжнее numeric id — он не меняется при переименовании канала и не зависит от
того, публичный канал или нет. Узнать его можно только через Bot API: читать
его из сообщений вручную неудобно, а для приватного канала @username вообще
не существует.

Запуск:
    .venv\\Scripts\\python.exe utils\\telegram_channel_info.py

    # или сразу с каналом, если он публичный и @username известен:
    .venv\\Scripts\\python.exe utils\\telegram_channel_info.py --channel @tabula_streams

Скрипт делает три вещи:
  1. getMe         — проверяет токен и печатает id/username самого бота;
  2. getChat       — по --channel либо getUpdates печатает chat_id канала;
  3. getChatMember — с --check-admin проверяет, что бот администратор и какие
                     именно права у него. Это единственный достоверный ответ на
                     вопрос «является ли бот админом»: в интерфейсе Telegram
                     ботов нет в списке участников, а анонимный администратор
                     показывается как «Анонимный администратор», а не как @username.

Примеры:
    # узнать id канала и сразу проверить права бота
    python utils\\telegram_channel_info.py --channel "@tabula_russia" --check-admin

    # кто ещё администраторы канала (ботов в выводе не будет — см. get_admins)
    python utils\\telegram_channel_info.py --channel "@tabula_russia" --admins

Важно: не запускать одновременно с ботом на том же токене. Long polling один,
второй процесс получит 409 Conflict и заберёт апдейты вместо основного.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

API_ROOT = "https://api.telegram.org"

# channel_post нужен, чтобы увидеть собственные публикации канала.
# Без allowed_updates бот получает только message из личных чатов.
ALLOWED_UPDATES = ["channel_post", "edited_channel_post", "my_chat_member"]

# Единственное право, на котором держится вся интеграция: бот ничего не
# публикует, а только редактирует уже существующий анонс.
#
# can_post_messages НЕ требуется. Это подтверждено на тестовом канале:
# бот работает как администратор с can_post_messages = нет, потому что
# публиковать посты ему не требуется. Проверять его как обязательное —
# значит показывать ложное «НЕ ГОТОВО» на заведомо рабочем канале.
CRITICAL_RIGHTS = ("can_edit_messages",)

# Человекочитаемые подписи к полям ChatMember. Ключи те же, что в Bot API,
# порядок — от самого важного к менее важному.
ADMIN_RIGHTS_LABELS = (
    ("can_post_messages", "публикация сообщений"),
    ("can_edit_messages", "редактирование сообщений"),
    ("can_delete_messages", "удаление сообщений"),
    ("can_manage_chat", "управление чатом"),
    ("can_invite_users", "приглашение пользователей"),
    ("can_restrict_members", "ограничение участников"),
    ("can_promote_members", "повышение прав"),
    ("can_change_info", "изменение информации о канале"),
    ("can_pin_messages", "закрепление сообщений"),
)

# Человекочитаемые подписи к статусам ChatMember.
MEMBER_STATUS_LABELS = {
    "creator": "владелец канала",
    "administrator": "администратор",
    "member": "участник (не администратор)",
    "restricted": "ограничен",
    "left": "покинул чат",
    "kicked": "исключён из чата",
}


def load_bot_token() -> str:
    """Токен из окружения, иначе из .env.

    Отдельная функция, а не config.settings: этот скрипт должен запускаться
    до того, как бот в бою поднимет long polling, и не тянуть за собой
    импорты всего приложения.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break

    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Добавь токен в .env, например:\n"
            "    TELEGRAM_BOT_TOKEN=1234567890:AAExxxxxxxxxxxxxxxxxxxxxxxxx"
        )
    return token


async def call_api(
    session: aiohttp.ClientSession, token: str, method: str, **params
) -> dict:
    """Один вызов Bot API с внятной ошибкой вместо сырого traceback."""
    url = f"{API_ROOT}/bot{token}/{method}"
    async with session.post(url, params=params) as response:
        payload = await response.json()

    if not payload.get("ok"):
        description = payload.get("description", "unknown error")
        if "conflict" in description.casefold():
            raise RuntimeError(
                f"{method}: 409 Conflict — на этом токене уже работает другой "
                "процесс long polling. Останови бот и запусти скрипт заново."
            )
        raise RuntimeError(f"{method}: {description} ({payload.get('error_code')})")

    return payload["result"]


def normalize_chat_ref(raw: str) -> str:
    """Приводит ссылку на публичный канал к тому, что понимает Bot API.

    Bot API гарантированно принимает только числовой id и `@username`.
    Ссылки вида `https://t.me/tabula_russia` и `t.me/tabula_russia` в
    документации не описаны: иногда проходят, иногда нет, поэтому
    переписываем их в `@username`. Если канал приватный, у него нет
    username — тогда останется исходная строка и ответит сам Telegram.
    """
    value = raw.strip()
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    for prefix in ("t.me/", "telegram.me/", "telegram.dog/"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    # В ссылках бывает хвост вида /tabula_russia/1234 — сообщение по номеру.
    value = value.strip("/").split("/")[0]
    # @ мог прийти от пользователя или из ссылки — иначе получилось бы @@name,
    # и Bot API отвечал бы «chat not found» на заведомо верном канале.
    value = value.lstrip("@")
    return f"@{value}" if value and not value.lstrip("-").isdigit() else value


async def show_admins(
    session: aiohttp.ClientSession, token: str, chat: dict, me: dict
) -> None:
    """Печатает администраторов канала.

    Сразу предупреждаем про ограничение метода, иначе вывод вводит в
    заблуждение: getChatAdministrators по документации возвращает
    администраторов, «которые не являются ботами». Бота в списке не будет —
    даже если он админ.
    """
    print(f"\n  Администраторы канала ({chat.get('title', chat['id'])}):")
    try:
        admins = await call_api(session, token, "getChatAdministrators", chat_id=chat["id"])
    except RuntimeError as error:
        print(f"  не удалось получить: {error}")
        print("  Метод требует, чтобы бот сам был администратором канала.")
        return

    for index, admin in enumerate(admins, start=1):
        user = admin.get("user") or {}
        name = user.get("username") or user.get("first_name") or "?"
        label = MEMBER_STATUS_LABELS.get(admin.get("status", ""), admin.get("status", "?"))
        title = admin.get("custom_title") or ""
        marker = " ← это мы" if user.get("id") == me["id"] else ""
        print(f"    {index}. @{name} — {label}" + (f", «{title}»" if title else "") + marker)

    print("    Ботов в этом списке нет по design Bot API — состояние бота")
    print(f"    (@{me.get('username', '?')}) проверяйте флагом --check-admin.")


def print_chat_member(member: dict, bot_username: str) -> bool:
    """Печатает права бота в чате. Возвращает True, если права достаточны.

    Проверяется именно `ChatMember` самого бота, а не список админов канала:
    getChatAdministrators по документации не возвращает ботов, а анонимный
    админ отображается как «Анонимный администратор», поэтому в интерфейсе
    и в списке админов бота не найти.
    """
    user = member.get("user") or {}
    status = member.get("status", "unknown")
    status_label = MEMBER_STATUS_LABELS.get(status, status)
    username = user.get("username") or bot_username
    is_anonymous = member.get("is_anonymous", False)

    print(f"\n  Права бота @{username} (id {user.get('id', '?')}):")
    print(f"    status       : {status} — {status_label}")
    if status == "administrator":
        print(
            "    анонимный    : "
            + ("да (публикует от имени канала)" if is_anonymous else "нет (виден как @username)")
        )

    granted: dict[str, bool] = {}
    for field, label in ADMIN_RIGHTS_LABELS:
        value = member.get(field)
        if value is None:
            # У не-администратора этих полей нет вовсе.
            continue
        granted[field] = bool(value)
        critical = "  ← обязательно" if field in CRITICAL_RIGHTS else ""
        print(f"    {field:<24}: {'да' if value else 'нет'}  ({label}){critical}")

    if status != "administrator":
        print("\n  Вердикт: НЕ ГОТОВО. Бот должен быть администратором канала.")
        print("  Добавь бота в канал → Управление каналом → Администраторы.")
        return False

    missing = [field for field in CRITICAL_RIGHTS if not granted.get(field)]
    if missing:
        print(f"\n  Вердикт: НЕ ГОТОВО. Не хватает прав: {', '.join(missing)}.")
        print("  У бота-администратора включите «Редактирование сообщений».")
        return False

    print("\n  Вердикт: ГОТОВО. Бот — администратор с правом редактирования,")
    print("  этого достаточно для автоподстановки ссылки на VOD.")
    if not granted.get("can_post_messages"):
        print("  can_post_messages = нет — норма: бот не публикует посты сам.")
    return True


def print_chat(chat: dict, source: str) -> None:
    """Печатает то, что нужно скопировать в .env."""
    print(f"\n  chat_id     : {chat.get('id')}")
    print(f"  type        : {chat.get('type')}")
    print(f"  title       : {chat.get('title', '-')}")
    print(f"  username    : @{chat['username']}" if chat.get("username") else "  username    : -")
    print(f"  источник    : {source}")

    channel_id = chat.get("id")
    if isinstance(channel_id, int) and str(channel_id).startswith("-100"):
        print(f"\n  В .env:  TELEGRAM_CHANNEL_ID={channel_id}")
    elif chat.get("username"):
        print(f"\n  В .env:  TELEGRAM_CHANNEL_ID=@{chat['username']}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Показать chat_id канала и проверить токен бота.",
    )
    parser.add_argument(
        "--channel",
        help="@username, -100... или ссылка t.me/имя. Без него chat_id берётся из getUpdates.",
    )
    parser.add_argument(
        "--check-admin",
        action="store_true",
        help="Проверить статус и права бота в канале (getChatMember). Рекомендуется вместе с --channel.",
    )
    parser.add_argument(
        "--admins",
        action="store_true",
        help="Показать список администраторов канала. Ботов в нём не будет — см. print_chat_member.",
    )
    parser.add_argument(
        "--watch",
        type=int,
        default=0,
        help="Сколько секунд слушать getUpdates. 0 = один недолгий запрос.",
    )
    args = parser.parse_args()

    token = load_bot_token()

    async with aiohttp.ClientSession() as session:
        me = await call_api(session, token, "getMe")
        print("Бот:")
        print(f"  id       : {me['id']}")
        print(f"  username : @{me.get('username', '-')}")

        if args.channel:
            chat_ref = normalize_chat_ref(args.channel)
            chat = await call_api(session, token, "getChat", chat_id=chat_ref)
            print_chat(chat, "getChat")

            if args.admins:
                await show_admins(session, token, chat, me)

            if args.check_admin:
                member = await call_api(
                    session, token, "getChatMember", chat_id=chat["id"], user_id=me["id"]
                )
                print_chat_member(member, me.get("username", "?"))
            else:
                print("\n  Проверить права бота: добавьте --check-admin")
            return

        # Канал не указан: узнаём id из апдейтов. Нужен хотя бы один пост в канале,
        # сделанный после добавления бота админом, — иначе getUpdates вернёт пусто.
        print("\nСлушаю getUpdates…")
        if args.watch:
            print("  Опубликуйте что-нибудь в канале прямо сейчас (Ctrl+C — выход).")

        updates = await call_api(
            session,
            token,
            "getUpdates",
            timeout=max(args.watch, 0) or 1,
            allowed_updates=json.dumps(ALLOWED_UPDATES),
        )

        seen: dict[int, dict] = {}
        for update in updates:
            for key in ("channel_post", "edited_channel_post", "my_chat_member"):
                payload = update.get(key)
                if not payload:
                    continue
                chat = payload.get("chat")
                if chat and chat.get("type") in ("channel", "supergroup", "group"):
                    seen[chat["id"]] = chat

        if not seen:
            print("\n  Апдейтов с чатами не пришло.")
            print("  Что проверить:")
            print("   1. бот добавлен в канал администратором;")
            print("   2. после этого в канал опубликован хотя бы один пост;")
            print("   3. у бота включено право «Доступ к сообщениям канала»;")
            print("   4. если запущено с --watch, публикуйте пост во время ожидания.")
            print("\n  Или узнайте id сразу: запустите с --channel @username")
            return

        print(f"\nНайдено чатов: {len(seen)}")
        for chat_id, chat in seen.items():
            print_chat(chat, "getUpdates")
            print(f"  {'-' * 40}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nПрервано.")
    except RuntimeError as error:
        print(f"\nОшибка: {error}", file=sys.stderr)
        sys.exit(1)
