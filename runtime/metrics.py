from bisect import bisect_right
from datetime import datetime

from runtime.session import StreamSession
from runtime.utils import (
    parse_iso,
    REPORTING_TZ,
    TT_BUCKET_MINUTES,
    ceil_to_10min,
    floor_to_10min,
)


def recalculate_all_metrics(session: StreamSession):
    ensure_session_shape_for_metrics(session)
    metrics = session["metrics"]
    viewer_samples = metrics.get("viewer_samples", [])
    follower_samples = metrics.get("follower_samples", [])

    started_at = parse_iso(session.get("started_at"))
    ended_at = parse_iso(session.get("ended_at"))

    if started_at and ended_at and ended_at > started_at and viewer_samples:
        points = _viewer_points(viewer_samples)
        hours_watched = _integrate_viewers(points, started_at, ended_at) / 3600.0
        duration_hours = (ended_at - started_at).total_seconds() / 3600.0

        metrics["hours_watched"] = round(hours_watched, 2)
        metrics["avg_viewers"] = round(hours_watched / duration_hours, 2) if duration_hours > 0 else None
        metrics["max_viewers"] = _max_viewers_in_range(points, started_at, ended_at)

        buckets = _build_tt_buckets(points, started_at, ended_at)
        metrics["viewer_buckets_10m"] = buckets
        if buckets:
            hours_watched_10m = sum(b["hours_watched"] for b in buckets)
            duration_hours_10m = sum(b["duration_hours"] for b in buckets)
            metrics["hours_watched_10m"] = round(hours_watched_10m, 2)
            metrics["avg_viewers_10m"] = (
                round(hours_watched_10m / duration_hours_10m, 2) if duration_hours_10m > 0 else None
            )
            max_v = [b["max_viewers"] for b in buckets if b.get("max_viewers") is not None]
            metrics["max_viewers_10m"] = max(max_v) if max_v else None
    elif viewer_samples:
        viewer_counts = [sample["viewer_count"] for sample in viewer_samples]
        metrics["avg_viewers"] = round(sum(viewer_counts) / len(viewer_counts), 2)
        metrics["max_viewers"] = max(viewer_counts)

    if follower_samples:
        followers_totals = [sample["followers_total"] for sample in follower_samples]
        metrics["followers_start"] = followers_totals[0]
        metrics["followers_end"] = followers_totals[-1]
        metrics["followers_delta"] = followers_totals[-1] - followers_totals[0]

    follow_events = metrics.get("follow_events", [])
    metrics["followers_delta_exact"] = len(follow_events)
    if started_at and ended_at and ended_at > started_at:
        duration_hours = (ended_at - started_at).total_seconds() / 3600.0
        metrics["followers_per_hour_exact"] = (
            round(metrics["followers_delta_exact"] / duration_hours, 2) if duration_hours > 0 else None
        )

    _recalculate_segment_follow_metrics(session)
    if session["status"] == "completed":
        _populate_games_summary(session)


def _recalculate_segment_follow_metrics(session: StreamSession):
    segments = session.get("game_segments", [])
    follow_events = session.get("metrics", {}).get("follow_events", [])

    for segment in segments:
        segment["followers_gained"] = 0
        segment["followers_per_hour"] = 0.0

    if not segments:
        return

    for event in follow_events:
        followed_at = parse_iso(event.get("followed_at"))
        if followed_at is None:
            continue

        for segment in segments:
            started_at = parse_iso(segment.get("started_at"))
            ended_at = parse_iso(segment.get("ended_at"))
            if started_at is None or ended_at is None:
                continue

            if started_at <= followed_at <= ended_at:
                segment["followers_gained"] += 1
                break

    for segment in segments:
        started_at = parse_iso(segment.get("started_at"))
        ended_at = parse_iso(segment.get("ended_at"))
        if started_at is None or ended_at is None or ended_at <= started_at:
            continue

        duration_hours = (ended_at - started_at).total_seconds() / 3600
        if duration_hours > 0:
            segment["followers_per_hour"] = round(segment["followers_gained"] / duration_hours, 2)


def _populate_games_summary(session: StreamSession):
    started_at = parse_iso(session.get("started_at"))
    ended_at = parse_iso(session.get("ended_at"))
    if started_at is None or ended_at is None or ended_at <= started_at:
        return

    metrics = session["metrics"]
    points = _viewer_points(metrics.get("viewer_samples", []))
    follow_events = metrics.get("follow_events", []) or []
    segments = session.get("game_segments", []) or []

    order: list[str] = []
    per_game: dict[str, dict] = {}

    def game_key(seg: dict) -> str:
        cid = seg.get("category_id") or ""
        name = seg.get("category_name") or ""
        return f"{cid}::{name}"

    for seg in segments:
        seg_start = parse_iso(seg.get("started_at"))
        seg_end = parse_iso(seg.get("ended_at"))
        if seg_start is None or seg_end is None or seg_end <= seg_start:
            continue

        seg_start = max(seg_start, started_at)
        seg_end = min(seg_end, ended_at)
        if seg_end <= seg_start:
            continue

        k = game_key(seg)
        if k not in per_game:
            per_game[k] = {
                "category_id": seg.get("category_id"),
                "category_name": seg.get("category_name"),
                "duration_minutes": 0.0,
                "avg_viewers": None,
                "peak_viewers": None,
                "hours_watched": 0.0,
                "followers_gained": 0,
                "followers_per_hour": 0.0,
            }
            order.append(k)

        duration_minutes = (seg_end - seg_start).total_seconds() / 60.0
        hours_watched = _integrate_viewers(points, seg_start, seg_end) / 3600.0
        peak = _max_viewers_in_range(points, seg_start, seg_end)

        per_game[k]["duration_minutes"] += duration_minutes
        per_game[k]["hours_watched"] += hours_watched
        if peak is not None:
            cur_peak = per_game[k]["peak_viewers"]
            per_game[k]["peak_viewers"] = peak if cur_peak is None else max(cur_peak, peak)

        gained = 0
        for ev in follow_events:
            f_at = parse_iso(ev.get("followed_at"))
            if f_at is None:
                continue
            if seg_start <= f_at <= seg_end:
                gained += 1
        per_game[k]["followers_gained"] += gained

    summary: list[dict] = []
    unique_names: list[str] = []
    for k in order:
        g = per_game[k]
        dur_hours = (g["duration_minutes"] / 60.0) if g["duration_minutes"] else 0.0
        g["duration_minutes"] = round(g["duration_minutes"], 2)
        g["hours_watched"] = round(g["hours_watched"], 2)
        g["avg_viewers"] = round((g["hours_watched"] / dur_hours), 2) if dur_hours > 0 else None
        g["followers_per_hour"] = round((g["followers_gained"] / dur_hours), 2) if dur_hours > 0 else 0.0
        summary.append(g)

        nm = g.get("category_name")
        if nm and nm not in unique_names:
            unique_names.append(nm)

    session["games_summary"] = summary
    session["games_unique"] = unique_names


def _viewer_points(viewer_samples: list[dict]) -> list[tuple[datetime, int]]:
    points: list[tuple[datetime, int]] = []
    for sample in viewer_samples:
        ts = parse_iso(sample.get("sampled_at"))
        if ts is None:
            continue
        try:
            val = int(sample.get("viewer_count"))
        except (TypeError, ValueError):
            continue
        points.append((ts, val))
    points.sort(key=lambda p: p[0])
    return points


def _integrate_viewers(points: list[tuple[datetime, int]], start: datetime, end: datetime) -> float:
    if not points or end <= start:
        return 0.0

    times = [t for t, _ in points]
    values = [v for _, v in points]
    i = bisect_right(times, start) - 1
    current_value = values[i] if i >= 0 else values[0]
    current_time = start

    total = 0.0
    while current_time < end:
        next_time = end
        if i + 1 < len(times) and times[i + 1] < end:
            next_time = times[i + 1]

        if next_time > current_time:
            total += float(current_value) * (next_time - current_time).total_seconds()

        current_time = next_time
        if current_time >= end:
            break

        i += 1
        if i < len(values):
            current_value = values[i]
        else:
            break

    return total


def _value_at(points: list[tuple[datetime, int]], at: datetime) -> int | None:
    if not points:
        return None
    times = [t for t, _ in points]
    idx = bisect_right(times, at) - 1
    if idx >= 0:
        return points[idx][1]
    return points[0][1]


def _max_viewers_in_range(points: list[tuple[datetime, int]], start: datetime, end: datetime) -> int | None:
    if not points or end <= start:
        return None
    m = _value_at(points, start)
    for ts, val in points:
        if ts < start:
            continue
        if ts > end:
            break
        if m is None or val > m:
            m = val
    return m


def _build_tt_buckets(
    points: list[tuple[datetime, int]],
    started_at: datetime,
    ended_at: datetime,
) -> list[dict]:
    if ended_at <= started_at:
        return []

    start_local = started_at.astimezone(REPORTING_TZ)
    end_local = ended_at.astimezone(REPORTING_TZ)

    label0 = start_local.replace(second=0, microsecond=0)
    next_boundary = ceil_to_10min(label0)
    if next_boundary <= label0:
        next_boundary = next_boundary + datetime.timedelta(minutes=TT_BUCKET_MINUTES)

    boundaries: list[datetime] = [next_boundary]
    last_boundary = floor_to_10min(end_local)
    t = next_boundary
    while t < last_boundary:
        t = t + datetime.timedelta(minutes=TT_BUCKET_MINUTES)
        boundaries.append(t)

    intervals: list[tuple[datetime, datetime, datetime]] = []
    first_end = min(boundaries[0], end_local) if boundaries else end_local
    intervals.append((label0, start_local, first_end))

    for i in range(len(boundaries)):
        b_start = boundaries[i]
        if b_start >= end_local:
            break
        b_end = end_local
        if i + 1 < len(boundaries):
            b_end = min(boundaries[i + 1], end_local)
        intervals.append((b_start, b_start, b_end))

    buckets: list[dict] = []
    for label_start, interval_start_local, interval_end_local in intervals:
        if interval_end_local <= interval_start_local:
            continue
        interval_start = interval_start_local.astimezone(datetime.timezone.utc)
        interval_end = interval_end_local.astimezone(datetime.timezone.utc)
        duration_hours = (interval_end - interval_start).total_seconds() / 3600.0
        if duration_hours <= 0:
            continue
        hours_watched = _integrate_viewers(points, interval_start, interval_end) / 3600.0
        max_viewers = _max_viewers_in_range(points, interval_start, interval_end)
        avg_viewers = (hours_watched / duration_hours) if duration_hours > 0 else None
        buckets.append(
            {
                "bucket_at": label_start.isoformat(),
                "duration_hours": round(duration_hours, 4),
                "avg_viewers": round(avg_viewers, 2) if avg_viewers is not None else None,
                "max_viewers": max_viewers,
                "hours_watched": round(hours_watched, 2),
            }
        )
    return buckets


def ensure_session_shape_for_metrics(session: StreamSession):
    # Simplified version of ensure_session_shape, only for metrics
    metrics = session.setdefault("metrics", {})
    metrics.setdefault("viewer_samples", [])
    metrics.setdefault("follower_samples", [])
    metrics.setdefault("follow_events", [])
    metrics.setdefault("viewer_buckets_10m", [])
    session.setdefault("game_segments", [])
