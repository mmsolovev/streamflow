"""Запись чата: фильтр канала и построение событий.

Логируется только основной канал (Tabula). Сообщения остальных каналов из
`TWITCH_CHANNELS` нужны боту для проверок команд, но в БД не попадают.

Тесты не трогают PostgreSQL: проверяются чистые функции и очередь
`ChatLogService`.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_chat_log.py -q
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import config.settings as settings
from services.chat_log_service import (
    ChatLogService,
    build_command_event,
    build_message_event,
    cleanup_old_messages,
    is_primary_channel,
)

TZ_PLUS_3 = timezone(timedelta(hours=3))


def _message(
    *,
    login="viewer",
    text="hello",
    message_id="msg-1",
    channel="tabula",
    timestamp=None,
    reply_parent=None,
):
    reply = (
        SimpleNamespace(parent_message_id=reply_parent)
        if reply_parent is not None
        else None
    )
    # TwitchIO 3: у ChatMessage канал — `broadcaster`, поля `channel` нет.
    return SimpleNamespace(
        chatter=SimpleNamespace(name=login, display_name=login.upper(), id=123),
        broadcaster=SimpleNamespace(name=channel),
        text=text,
        id=message_id,
        timestamp=timestamp or datetime(2026, 1, 1, 3, 0, tzinfo=TZ_PLUS_3),
        reply=reply,
    )


def _command(*, login="moder", invoked_with="!время", channel="tabula"):
    return SimpleNamespace(
        author=SimpleNamespace(name=login, display_name=login.upper(), id=456),
        channel=SimpleNamespace(name=channel),
        message=SimpleNamespace(
            text=f"{invoked_with} extra",
            id="cmd-msg",
            timestamp=datetime(2026, 1, 1, 3, 0, tzinfo=TZ_PLUS_3),
        ),
        invoked_with=invoked_with,
        command=SimpleNamespace(name="time"),
    )


def test_primary_channel_is_case_insensitive():
    with patch.object(settings, "TWITCH_PRIMARY_CHANNEL", "Tabula"):
        assert is_primary_channel("tabula")
        assert is_primary_channel("  TABULA ")
        assert not is_primary_channel("other")
        assert not is_primary_channel(None)


def test_empty_primary_channel_matches_nothing():
    with patch.object(settings, "TWITCH_PRIMARY_CHANNEL", ""):
        assert not is_primary_channel("tabula")


def test_message_event_is_built_from_payload():
    event = build_message_event(
        _message(text="!time", message_id="m1", reply_parent="p1"),
        is_command=True,
    )

    assert event is not None
    assert event.kind == "message"
    assert event.login == "viewer"
    assert event.display_name == "VIEWER"
    assert event.twitch_user_id == "123"
    assert event.message == "!time"
    assert event.twitch_message_id == "m1"
    assert event.is_command
    assert event.reply_parent_message_id == "p1"
    assert event.created_at == datetime(2026, 1, 1, 0, 0)
    assert event.created_at.tzinfo is None


def test_message_without_chatter_or_login_is_skipped():
    no_chatter = SimpleNamespace(
        chatter=None, broadcaster=SimpleNamespace(name="tabula")
    )
    no_login = _message()
    no_login.chatter.name = ""

    assert build_message_event(no_chatter, is_command=False) is None
    assert build_message_event(no_login, is_command=False) is None


def test_twitchio_message_without_channel_field_is_built():
    """Регрессия: у ChatMessage есть только `broadcaster`.

    Раньше чтение `payload.channel` возвращало None, сообщение
    отбрасывалось и `chat_messages` оставался пустым.
    """
    payload = _message(channel="tabula")
    assert not hasattr(payload, "channel")

    event = build_message_event(payload, is_command=False)

    assert event is not None
    assert event.channel_login == "tabula"


def test_channel_fallback_still_supported():
    payload = SimpleNamespace(
        chatter=SimpleNamespace(name="viewer", display_name="Viewer", id=1),
        channel=SimpleNamespace(name="tabula"),
        text="hi",
        id="m2",
        timestamp=datetime(2026, 1, 1, 0, 0),
        reply=None,
    )

    event = build_message_event(payload, is_command=False)

    assert event is not None
    assert event.channel_login == "tabula"


def test_command_event_keeps_invoked_alias():
    event = build_command_event(_command())

    assert event is not None
    assert event.kind == "command"
    assert event.login == "moder"
    assert event.twitch_user_id == "456"
    assert event.command_name == "time"
    assert event.invoked_name == "!время"
    assert event.twitch_message_id == "cmd-msg"
    assert event.created_at == datetime(2026, 1, 1, 0, 0)


def test_command_falls_back_to_first_word_of_message():
    context = _command()
    context.invoked_with = None

    event = build_command_event(context)

    assert event.invoked_name == "!время"


def test_command_without_author_is_skipped():
    context = _command()
    context.author = None

    assert build_command_event(context) is None


def test_messages_only_from_primary_channel_reach_queue():
    service = ChatLogService()

    with patch.object(settings, "CHAT_LOG_ENABLED", True), patch.object(
        settings, "TWITCH_PRIMARY_CHANNEL", "tabula"
    ):
        service.enqueue_message(_message(channel="other"), is_command=False)
        assert service._queue.qsize() == 0

        service.enqueue_message(_message(channel="tabula"), is_command=False)
        assert service._queue.qsize() == 1


def test_commands_from_all_channels_are_logged():
    service = ChatLogService()

    with patch.object(settings, "CHAT_LOG_ENABLED", True), patch.object(
        settings, "TWITCH_PRIMARY_CHANNEL", "tabula"
    ):
        service.enqueue_command(_command(channel="other"))
        service.enqueue_command(_command(channel="tabula"))

    assert service._queue.qsize() == 2
    other = service._queue.get_nowait()
    primary = service._queue.get_nowait()
    assert other.channel_login == "other"
    assert primary.channel_login == "tabula"


def test_disabled_log_ignores_everything():
    service = ChatLogService()

    with patch.object(settings, "CHAT_LOG_ENABLED", False), patch.object(
        settings, "TWITCH_PRIMARY_CHANNEL", "tabula"
    ):
        service.enqueue_message(_message(), is_command=False)
        service.enqueue_command(_command())

    assert service._queue.qsize() == 0


async def test_zero_retention_keeps_messages_forever():
    class NoDatabase:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("retention=0 must not touch the database")

    deleted = await cleanup_old_messages(NoDatabase(), retention_days=0)

    assert deleted == 0
