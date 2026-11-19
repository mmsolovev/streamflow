"""Tests for web repository shared helpers (pure functions)."""
from datetime import datetime, timedelta

from backend.repositories._shared import (
    build_recommenders_text,
    build_tags_text,
    format_duration_hours,
    release_delta_days,
)


def test_build_tags_text_joins_parts():
    assert build_tags_text("PC", "Action") == "PC | Action"
    assert build_tags_text("PC", "") == "PC"
    assert build_tags_text(None, None) == ""


def test_build_recommenders_text_special_users():
    data = [
        {"user_login": "tabula", "display_name": "Tabula"},
        {"user_login": "twitch", "display_name": "IGDB"},
        {"user_login": "someone", "display_name": "Someone"},
    ]
    assert build_recommenders_text(data) == "Tabula, Twitch, Someone"


def test_build_recommenders_text_empty():
    assert build_recommenders_text([]) == ""
    assert build_recommenders_text(None) == ""


def test_release_delta_days():
    assert release_delta_days(None) is None
    future = datetime.utcnow() + timedelta(days=5)
    assert release_delta_days(future) == 5
    past = datetime.utcnow() - timedelta(days=1)
    assert release_delta_days(past) is None


def test_format_duration_hours():
    assert format_duration_hours(None) == 0.0
    assert format_duration_hours(0) == 0.0
    assert format_duration_hours(90) == 1.5
