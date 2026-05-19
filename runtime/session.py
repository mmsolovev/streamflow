from typing import TypedDict, NotRequired

from config.settings import STREAM_RUNTIME_SAMPLE_SECONDS

COLLECTOR_STATE_VERSION = 2


class Event(TypedDict):
    type: str
    timestamp: str
    payload: dict


class TitleHistory(TypedDict):
    title: str
    changed_at: str
    source: str


class CategoryHistory(TypedDict):
    category_id: str
    category_name: str
    changed_at: str
    source: str


class GameSegment(TypedDict):
    category_id: str
    category_name: str
    started_at: str
    ended_at: str | None
    source: str
    followers_gained: NotRequired[int]
    followers_per_hour: NotRequired[float]


class ViewerSample(TypedDict):
    viewer_count: int
    sampled_at: str
    source: str


class FollowerSample(TypedDict):
    followers_total: int
    sampled_at: str
    source: str


class FollowEvent(TypedDict):
    user_id: str
    user_login: str
    followed_at: str
    source: str


class ViewerBucket(TypedDict):
    bucket_at: str
    duration_hours: float
    avg_viewers: float | None
    max_viewers: int | None
    hours_watched: float


class GameSummary(TypedDict):
    category_id: str
    category_name: str
    duration_minutes: float
    avg_viewers: float | None
    peak_viewers: int | None
    hours_watched: float
    followers_gained: int
    followers_per_hour: float


class TTCompat(TypedDict):
    avg_viewers_tt: int | None
    max_viewers_tt: int | None
    hours_watched_tt: float | None


class Metrics(TypedDict):
    sample_interval_seconds: int
    viewer_samples: list[ViewerSample]
    follower_samples: list[FollowerSample]
    follow_events: list[FollowEvent]
    avg_viewers: float | None
    max_viewers: int | None
    hours_watched: float | None
    viewer_buckets_10m: list[ViewerBucket]
    avg_viewers_10m: float | None
    max_viewers_10m: int | None
    hours_watched_10m: float | None
    followers_start: int | None
    followers_end: int | None
    followers_delta: int | None
    followers_delta_exact: int | None
    followers_per_hour_exact: float | None
    tt_compat: NotRequired[TTCompat]


class CollectorInfo(TypedDict):
    created_at: str
    updated_at: str
    source: str
    completed_at: NotRequired[str]
    completion_reason: NotRequired[str]


class StreamSession(TypedDict):
    version: int
    status: str
    channel_login: str
    broadcaster_id: str | None
    stream_id: str
    started_at: str
    ended_at: str | None
    duration_minutes: float | None
    title: str | None
    title_start: str | None
    title_current: str | None
    category_name: str | None
    category_id: str | None
    title_history: list[TitleHistory]
    category_history: list[CategoryHistory]
    game_segments: list[GameSegment]
    events: list[Event]
    games_unique: list[str]
    games_summary: list[GameSummary]
    metrics: Metrics
    collector: CollectorInfo


def create_new_session(
    *,
    stream_id: str,
    started_at: str,
    title: str | None,
    category_name: str | None,
    category_id: str | None,
    source: str,
    broadcaster_id: str | None,
) -> StreamSession:
    from runtime.utils import now_iso

    now = now_iso()
    session: StreamSession = {
        "version": COLLECTOR_STATE_VERSION,
        "status": "active",
        "channel_login": "mishgan",  # Assuming TWITCH_PRIMARY_CHANNEL
        "broadcaster_id": broadcaster_id,
        "stream_id": stream_id,
        "started_at": started_at,
        "ended_at": None,
        "duration_minutes": None,
        "title": title,
        "title_start": title,
        "title_current": title,
        "category_name": category_name,
        "category_id": category_id,
        "title_history": [],
        "category_history": [],
        "game_segments": [],
        "events": [],
        "games_unique": [],
        "games_summary": [],
        "metrics": {
            "sample_interval_seconds": STREAM_RUNTIME_SAMPLE_SECONDS,
            "viewer_samples": [],
            "follower_samples": [],
            "follow_events": [],
            "avg_viewers": None,
            "max_viewers": None,
            "hours_watched": None,
            "viewer_buckets_10m": [],
            "avg_viewers_10m": None,
            "max_viewers_10m": None,
            "hours_watched_10m": None,
            "followers_start": None,
            "followers_end": None,
            "followers_delta": None,
            "followers_delta_exact": None,
            "followers_per_hour_exact": None,
            "tt_compat": {},
        },
        "collector": {
            "created_at": now,
            "updated_at": now,
            "source": source,
        },
    }

    if title:
        session["title_history"].append(
            {"title": title, "changed_at": started_at, "source": source}
        )

    if category_name:
        session["category_history"].append(
            {
                "category_id": category_id,
                "category_name": category_name,
                "changed_at": started_at,
                "source": source,
            }
        )
        session["game_segments"].append(
            {
                "category_id": category_id,
                "category_name": category_name,
                "started_at": started_at,
                "ended_at": None,
                "source": source,
            }
        )
    return session


def ensure_session_shape(session: StreamSession | None):
    from runtime.utils import now_iso
    if not session:
        return

    session.setdefault("version", COLLECTOR_STATE_VERSION)
    session.setdefault("events", [])
    session.setdefault("title_history", [])
    session.setdefault("category_history", [])
    session.setdefault("game_segments", [])
    session.setdefault("title_start", session.get("title"))
    session.setdefault("title_current", session.get("title"))
    session.setdefault("games_unique", [])
    session.setdefault("games_summary", [])
    session.setdefault("collector", {"created_at": now_iso(), "updated_at": now_iso(), "source": "unknown"})
    session["collector"].setdefault("created_at", now_iso())
    session["collector"].setdefault("updated_at", now_iso())
    session["collector"].setdefault("source", "unknown")

    metrics = session.setdefault("metrics", {
        "sample_interval_seconds": STREAM_RUNTIME_SAMPLE_SECONDS,
        "viewer_samples": [], "follower_samples": [], "follow_events": [],
        "avg_viewers": None, "max_viewers": None, "hours_watched": None,
        "viewer_buckets_10m": [], "avg_viewers_10m": None, "max_viewers_10m": None, "hours_watched_10m": None,
        "followers_start": None, "followers_end": None, "followers_delta": None,
        "followers_delta_exact": None, "followers_per_hour_exact": None,
        "tt_compat": {},
    })
    metrics.setdefault("sample_interval_seconds", STREAM_RUNTIME_SAMPLE_SECONDS)
    metrics.setdefault("viewer_samples", [])
    metrics.setdefault("follower_samples", [])
    metrics.setdefault("follow_events", [])
    metrics.setdefault("viewer_buckets_10m", [])
    metrics.setdefault("tt_compat", {})
