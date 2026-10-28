# Telegram: анонсы и правка после стрима

Модуль `telegram/` на aiogram следит за постами канала, находит анонс
завершившегося стрима и дописывает в него ссылку на запись (VOD). Управление
из веб-интерфейса — раздел `/admin/telegram`.

## Включение

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHANNEL_ID=-100xxxxxxxxxx
```

- `TELEGRAM_ENABLED=false` — сервис не запускает polling и не правит посты.
- `TELEGRAM_CHANNEL_ID` должен быть **числовым** id канала (`-100…`).
  `@username` Bot API принимает, но фильтр по `chat_id` в БД вернёт пусто.
  Узнать id: `python utils/telegram_channel_info.py --channel @name`.
- Ссылка на канал для матчинга выводится из `TWITCH_PRIMARY_CHANNEL`;
  отдельная переменная не нужна.

Основные настройки (`config/settings.py`):

| Переменная | По умолчанию | Смысл |
|---|---:|---|
| `TELEGRAM_VOD_CHECK_DELAY_SECONDS` | 660 | пауза после конца стрима перед проверкой VOD |
| `TELEGRAM_VOD_POLL_INTERVAL_SECONDS` | 60 | частота опроса очереди задач |
| `TELEGRAM_VOD_MAX_ATTEMPTS` | 5 | попыток при инфраструктурных ошибках |
| `TELEGRAM_MATCH_WINDOW_BEFORE_HOURS` | 12 | окно поиска анонса до начала стрима |
| `TELEGRAM_MATCH_WINDOW_AFTER_MINUTES` | 60 | окно после конца стрима |
| `TELEGRAM_REBIND_WINDOW_MINUTES` | 180 | переиспользование поста после рестарта трансляции |
| `TELEGRAM_LINK_DOMAINS` | `twitch.tv` | домены ссылок, по которым ищется анонс |

## Поток

1. **Наблюдение.** `telegram/handlers.py` слушает `channel_post` и сохраняет
   пост в `telegram_announcements` (текст/подпись, entities, media kind, link
   URLs). Ссылка на Twitch-канал проверяется позже, при выборе кандидата; бот
   ничего не правит на этом этапе.
2. **Ручная правка.** `edited_channel_post` обновляет снапшоты. Если пост уже
   был отредактирован ботом и новый текст не совпадает с эхом его правки,
   анонс помечается `skipped` и больше не трогается. Эхо собственной правки
   бота отличается по `edited_text`.
3. **Конец стрима.** Runtime-сессия при финализации вызывает
   `TelegramService.on_stream_ended(stream_session)`:
   - ищет анонс в окне `[started_at - before_hours; ended_at + after_minutes]`,
     исключая уже привязанные и `skipped` посты;
   - если не нашёл — пробует переиспользовать пост предыдущего стрима в
     пределах `TELEGRAM_REBIND_WINDOW_MINUTES` (после краша трансляции);
   - создаёт задачу в `telegram_announcement_vods` со `status=waiting` и
     `check_at = now + delay` (задержка из настроек, по умолчанию 660 с);
   - если анонс не найден, задача получает `pending_selection` и ждёт выбора
     админа в веб-интерфейсе.
4. **Поиск VOD.** Поллер (`process_due_jobs`) забирает задачи `claim_due` и
   вызывает Twitch Helix для VOD по `stream_id`.
   - VOD найден → `mark_resolved`, затем правка поста;
   - VOD ещё нет → `no_vod`, пост не меняется;
   - сетевая/5xx ошибка → `mark_failed`, экспоненциальный retry до
     `TELEGRAM_VOD_MAX_ATTEMPTS`.
5. **Правка.** `telegram/post_edit.py` собирает текст/entities по шаблону из
   `telegram_post_edit_settings`; для медиа-поста используется
   `edit_message_caption`, для текстового — `edit_message_text` с отключённым
   preview. Перед правкой сохраняется операция в
   `telegram_post_edit_operations` (`kind=publish`), чтобы можно было сделать
   undo/restore.

Повторный VOD для того же поста (вторая трансляция после падения) добавляется
к уже собранным ссылкам: `vod_jobs.resolved_urls(...)`.

## Шаблон правки

Настройки хранятся в `telegram_post_edit_settings`:

- `header`, `item`, `separator`, `footer`, `link_label`, `delay_seconds`;
- обязательный токен `{{link}}` в `item`;
- в `header`/`separator`/`footer` токены запрещены;
- `delay_seconds` пересчитывает `check_at` у задач в статусе `waiting`.

По умолчанию:

```
header    = "Запись стрима:\n\n"
item      = "🎥{{link}}~"
separator = "\n"
label     = "TWITCH"
delay     = 660
```

Длина текста подгоняется под лимит медиа/текста Telegram
(`fit_to_media_limit`), entities обрезаются согласованно.

## Undo / restore

- `undo` возвращает текст, который был до правки бота, и помечает операцию
  `undone`;
- `restore` возвращает исходный текст анонса (снапшот до всех правок);
- обе операции не выполняются, если пост изменён вручную или `skipped`;
- история — `telegram_post_edit_operations`, состояние задачи —
  `telegram_announcement_vods`.

## API

Префикс `/api/v1/admin/telegram/post-stream`, доступ `EDIT_TABLES`:

- `GET` — состояние, список запусков и анонсов, preview;
- `PUT /target` — выбрать стрим/анонс вручную;
- `PATCH /settings`, `POST /settings/reset` — шаблон;
- `POST /publish`, `/undo`, `/restore` — действия;
- `POST /check-vod` — принудительная проверка VOD.

Подробный контракт — `docs/API.md` и `/docs`.

## Код

| Файл | Роль |
|---|---|
| `telegram/service.py` | lifecycle, привязка анонса, очередь, правка/undo/restore |
| `telegram/handlers.py` | приём постов и их правок |
| `telegram/announcements.py` | CRUD и снапшоты анонсов |
| `telegram/matcher.py` | окна времени, ссылки, выбор кандидата |
| `telegram/post_edit.py` | шаблон и рендер текста/entities |
| `telegram/post_edit_store.py` | настройки шаблона из БД |
| `telegram/vod_jobs.py` | очередь `telegram_announcement_vods` |
| `telegram/vod_service.py` | поиск VOD в Twitch Helix |
| `telegram/entities.py` | UTF-16 offsets, text_link, custom_emoji |
| `telegram/templates.py` | старый формат «Запись стрима» |
