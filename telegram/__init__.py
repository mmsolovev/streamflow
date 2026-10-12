"""Telegram: правка анонсов стримов при появлении записи.

Пакет лежит на верхнем уровне рядом с `runtime` и `pipeline`, потому что это
самостоятельный потребитель: свой long-poll через aiogram, своё состояние в
PostgreSQL, своя точка входа (хук на `RuntimeStreamCollector.finalize_active_session`).
На верхнем уровне он читается как отдельный слой, а не как ещё один сервис бота,
и его видно целиком при выделении в микросервис.

ВНИМАНИЕ, имя пакета: `telegram` перекрывает одноимённый сторонний пакет
(`python-telegram-bot`). В этом проекте он не используется, а весь доступ
к Bot API идёт через aiogram. Если зависимость появится — конфликт импортов.

Слои внутри пакета:

    matcher.py       чистые функции: текст, ссылки, окно времени. Без I/O
    templates.py     жёсткие тексты анонсов и лимиты Telegram
    service.py       жизненный цикл: aiogram Bot/Dispatcher, хендлеры, VOD-поллер
    handlers.py      aiogram-обработчики channel_post / edited_channel_post
    announcements.py работа с telegram_announcements
    vod_jobs.py      работа с telegram_announcement_vods
    vod_service.py   поиск VOD по Twitch stream_id

I/O-слой читает настройки через `config.settings`, как это делают `services/*`
и `runtime/*`; собственного `telegram.settings` нет.
"""