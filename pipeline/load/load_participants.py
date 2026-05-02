from __future__ import annotations

"""
Load layer: writes targeting `participants` table (Participant) and its association with streams.
"""

from sqlalchemy.orm import Session
import re

from database.models import Participant, Stream
from pipeline.load.load_stream_games import unique_in_order


def get_or_create_participant(session: Session, name: str) -> Participant:
    participant = session.query(Participant).filter_by(name=name).first()
    if participant is None:
        participant = Participant(name=name, display_name=f"@{name}")
        session.add(participant)
        session.flush()
    return participant


def extract_participants_from_title(title: str | None) -> list[str]:
    title = title or ""
    # Legacy rule from import_json_to_db.py: @(\w+) -> lower() and unique in order
    return unique_in_order([name.lower() for name in re.findall(r"@(\w+)", title)])


def sync_stream_participants_from_title(session: Session, stream: Stream, title: str | None) -> bool:
    desired_names = extract_participants_from_title(title)
    desired_set = set(desired_names)
    changed = False

    existing_by_name = {p.name: p for p in stream.participants}
    for name, participant in list(existing_by_name.items()):
        if name not in desired_set:
            stream.participants.remove(participant)
            changed = True

    existing_names = {p.name for p in stream.participants}
    for name in desired_names:
        if name in existing_names:
            continue
        stream.participants.append(get_or_create_participant(session, name))
        existing_names.add(name)
        changed = True

    return changed


__all__ = [
    "extract_participants_from_title",
    "get_or_create_participant",
    "sync_stream_participants_from_title",
]

