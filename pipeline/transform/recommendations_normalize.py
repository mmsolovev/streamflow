from __future__ import annotations

"""
Transform layer: normalization helpers for recommendations.
"""

import re


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


__all__ = ["normalize_name"]

