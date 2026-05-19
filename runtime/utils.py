from datetime import datetime, timedelta, timezone


# TwitchTracker выглядит как "таблица каждые 10 минут" в локальном времени канала.
# Фиксированный MSK (UTC+03:00).
REPORTING_TZ = timezone(timedelta(hours=3))
TT_BUCKET_MINUTES = 10


def calculate_duration_minutes(started_at: str | None, ended_at: str | None) -> float | None:
    if not started_at or not ended_at:
        return None

    start_dt = parse_iso(started_at)
    end_dt = parse_iso(ended_at)
    if not start_dt or not end_dt:
        return None
    duration = end_dt - start_dt
    return round(duration.total_seconds() / 60, 2)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def infer_session_end_time(session: dict) -> str:
    """
    При восстановлении после рестарта нельзя ставить ended_at=now: это ломает вычисление средних значений.
    Берём последнюю известную активность сессии.
    """
    candidates: list[datetime] = []

    metrics = session.get("metrics", {}) if isinstance(session, dict) else {}
    for sample in (metrics.get("viewer_samples") or []):
        ts = parse_iso(sample.get("sampled_at"))
        if ts is not None:
            candidates.append(ts)
    for sample in (metrics.get("follower_samples") or []):
        ts = parse_iso(sample.get("sampled_at"))
        if ts is not None:
            candidates.append(ts)
    for event in (session.get("events") or []):
        ts = parse_iso(event.get("timestamp"))
        if ts is not None:
            candidates.append(ts)
    collector = session.get("collector", {}) if isinstance(session, dict) else {}
    for key in ("updated_at", "created_at"):
        ts = parse_iso(collector.get(key))
        if ts is not None:
            candidates.append(ts)

    if candidates:
        return max(candidates).astimezone(timezone.utc).isoformat()
    return now_iso()


def ceil_to_10min(dt: datetime) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    add = (TT_BUCKET_MINUTES - (dt.minute % TT_BUCKET_MINUTES)) % TT_BUCKET_MINUTES
    if add == 0:
        return dt
    return dt + timedelta(minutes=add)


def floor_to_10min(dt: datetime) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    minute = dt.minute - (dt.minute % TT_BUCKET_MINUTES)
    return dt.replace(minute=minute)


def floor_to_10min_utc(dt: datetime) -> datetime:
    """Округляет время до ближайшей 10-минутной границы UTC вниз."""
    dt_utc = dt.astimezone(timezone.utc)
    dt_utc = dt_utc.replace(second=0, microsecond=0)
    minute = dt_utc.minute - (dt_utc.minute % 10)
    return dt_utc.replace(minute=minute)


def ceil_to_10min_utc(dt: datetime) -> datetime:
    """Округляет время до ближайшей 10-минутной границы UTC вверх."""
    dt_utc = dt.astimezone(timezone.utc)
    dt_utc = dt_utc.replace(second=0, microsecond=0)
    add = (10 - (dt_utc.minute % 10)) % 10
    if add == 0:
        return dt_utc
    return dt_utc + timedelta(minutes=add)
