"""Запись чата: фильтр канала и построение событий.

Логируется только основной канал (Tabula). Сообщения остальных каналов из
`TWITCH_CHANNELS` нужны боту для проверок команд, но в БД не попадают.

Тесты не трогают PostgreSQL: проверяются чистые функции и очередь
`ChatLogService`.

Запуск:
    .venv\\Scripts\\python.exe -m unittest tests.test_chat_log -v
"""

import unittest
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


class PrimaryChannelTests(unittest.TestCase):
    def test_primary_channel_is_case_insensitive(self):
        with patch.object(settings, "TWITCH_PRIMARY_CHANNEL", "Tabula"):
            self.assertTrue(is_primary_channel("tabula"))
            self.assertTrue(is_primary_channel("  TABULA "))
            self.assertFalse(is_primary_channel("other"))
            self.assertFalse(is_primary_channel(None))

    def test_empty_primary_channel_matches_nothing(self):
        with patch.object(settings, "TWITCH_PRIMARY_CHANNEL", ""):
            self.assertFalse(is_primary_channel("tabula"))


class BuildMessageEventTests(unittest.TestCase):
    def test_message_event_is_built_from_payload(self):
        event = build_message_event(
            _message(text="!time", message_id="m1", reply_parent="p1"),
            is_command=True,
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "message")
        self.assertEqual(event.login, "viewer")
        self.assertEqual(event.display_name, "VIEWER")
        self.assertEqual(event.twitch_user_id, "123")
        self.assertEqual(event.message, "!time")
        self.assertEqual(event.twitch_message_id, "m1")
        self.assertTrue(event.is_command)
        self.assertEqual(event.reply_parent_message_id, "p1")
        self.assertEqual(event.created_at, datetime(2026, 1, 1, 0, 0))
        self.assertIsNone(event.created_at.tzinfo)

    def test_message_without_chatter_or_login_is_skipped(self):
        no_chatter = SimpleNamespace(
            chatter=None, broadcaster=SimpleNamespace(name="tabula")
        )
        no_login = _message()
        no_login.chatter.name = ""

        self.assertIsNone(build_message_event(no_chatter, is_command=False))
        self.assertIsNone(build_message_event(no_login, is_command=False))

    def test_twitchio_message_without_channel_field_is_built(self):
        """Регрессия: у ChatMessage есть только `broadcaster`.

        Раньше чтение `payload.channel` возвращало None, сообщение
        отбрасывалось и `chat_messages` оставался пустым.
        """
        payload = _message(channel="tabula")
        self.assertFalse(hasattr(payload, "channel"))

        event = build_message_event(payload, is_command=False)

        self.assertIsNotNone(event)
        self.assertEqual(event.channel_login, "tabula")

    def test_channel_fallback_still_supported(self):
        payload = SimpleNamespace(
            chatter=SimpleNamespace(name="viewer", display_name="Viewer", id=1),
            channel=SimpleNamespace(name="tabula"),
            text="hi",
            id="m2",
            timestamp=datetime(2026, 1, 1, 0, 0),
            reply=None,
        )

        event = build_message_event(payload, is_command=False)

        self.assertIsNotNone(event)
        self.assertEqual(event.channel_login, "tabula")


class BuildCommandEventTests(unittest.TestCase):
    def test_command_event_keeps_invoked_alias(self):
        event = build_command_event(_command())

        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "command")
        self.assertEqual(event.login, "moder")
        self.assertEqual(event.twitch_user_id, "456")
        self.assertEqual(event.command_name, "time")
        self.assertEqual(event.invoked_name, "!время")
        self.assertEqual(event.twitch_message_id, "cmd-msg")
        self.assertEqual(event.created_at, datetime(2026, 1, 1, 0, 0))

    def test_command_falls_back_to_first_word_of_message(self):
        context = _command()
        context.invoked_with = None

        event = build_command_event(context)

        self.assertEqual(event.invoked_name, "!время")

    def test_command_without_author_is_skipped(self):
        context = _command()
        context.author = None

        self.assertIsNone(build_command_event(context))


class ChatLogServiceFilterTests(unittest.TestCase):
    def test_messages_only_from_primary_channel_reach_queue(self):
        service = ChatLogService()

        with patch.object(settings, "CHAT_LOG_ENABLED", True), patch.object(
            settings, "TWITCH_PRIMARY_CHANNEL", "tabula"
        ):
            service.enqueue_message(_message(channel="other"), is_command=False)
            self.assertEqual(service._queue.qsize(), 0)

            service.enqueue_message(_message(channel="tabula"), is_command=False)
            self.assertEqual(service._queue.qsize(), 1)

    def test_commands_from_all_channels_are_logged(self):
        service = ChatLogService()

        with patch.object(settings, "CHAT_LOG_ENABLED", True), patch.object(
            settings, "TWITCH_PRIMARY_CHANNEL", "tabula"
        ):
            service.enqueue_command(_command(channel="other"))
            service.enqueue_command(_command(channel="tabula"))

        self.assertEqual(service._queue.qsize(), 2)
        other = service._queue.get_nowait()
        primary = service._queue.get_nowait()
        self.assertEqual(other.channel_login, "other")
        self.assertEqual(primary.channel_login, "tabula")

    def test_disabled_log_ignores_everything(self):
        service = ChatLogService()

        with patch.object(settings, "CHAT_LOG_ENABLED", False), patch.object(
            settings, "TWITCH_PRIMARY_CHANNEL", "tabula"
        ):
            service.enqueue_message(_message(), is_command=False)
            service.enqueue_command(_command())

        self.assertEqual(service._queue.qsize(), 0)


class CleanupRetentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_retention_keeps_messages_forever(self):
        class NoDatabase:
            async def execute(self, *_args, **_kwargs):
                raise AssertionError("retention=0 must not touch the database")

        deleted = await cleanup_old_messages(NoDatabase(), retention_days=0)

        self.assertEqual(deleted, 0)


if __name__ == "__main__":
    unittest.main()
