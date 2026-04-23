from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class SyncStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0


def unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def extract_participants_from_title(title: str | None) -> list[str]:
    title = title or ""
    # Legacy rule from import_json_to_db.py: @(\w+) -> lower() and unique in order
    return unique_in_order([name.lower() for name in re.findall(r"@(\w+)", title)])


__all__ = [
    "SyncStats",
    "extract_participants_from_title",
    "unique_in_order",
]

