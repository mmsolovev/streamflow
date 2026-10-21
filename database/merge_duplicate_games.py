"""
Merge duplicate game rows into their canonical keeper.

Repoints every FK that references games.id onto the keeper row, drops the
duplicate, and optionally adopts a canonical name/slug. The merge logic mirrors
alembic revision 0007 (_merge_game_pair) and is destructive for the duplicate.

Usage:
    python database/merge_duplicate_games.py                 # report + dry run (rollback)
    python database/merge_duplicate_games.py --apply         # perform the merge
    python database/merge_duplicate_games.py --pair 402:72:Sekiro-Name --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa

from database.db import engine

# keeper, dup, canonical name (None -> keep keeper's current name/slug)
DEFAULT_PAIRS: list[tuple[int, int, str | None]] = [
    (72, 402, "Sekiro: Shadows Die Twice"),
    (322, 445, None),
    (173, 479, None),
    (462, 493, None),
]

_GAME_STATS_COLS = [
    "duration_minutes", "avg_viewers", "max_viewers", "followers_per_hour",
    "streams_count", "last_stream", "synced_at",
]
_IGDB_COLS = [
    "igdb_id", "is_primary", "release_date", "igdb_name", "steam_url",
    "igdb_score", "steam_score", "description_en", "description_ru",
    "cover_url", "raw_payload", "synced_at",
]
_HLTB_COLS = [
    "hltb_id", "hltb_name", "hltb_main_story", "hltb_main_extra",
    "hltb_completionist", "hltb_all_styles", "hltb_coop", "hltb_multiplayer",
    "hltb_review_score", "review_count", "synced_at",
]

# table -> column used to detect the duplicate's dangling references
_REF_TABLES = [
    ("game_aliases", "game_id"),
    ("stream_games", "game_id"),
    ("clips", "game_id"),
    ("streamer_games", "game_id"),
    ("game_recommendations", "game_id"),
    ("game_genres", "game_id"),
    ("game_platforms", "game_id"),
    ("game_metadata_igdb", "game_id"),
    ("game_metadata_hltb", "game_id"),
    ("game_stats", "game_id"),
]


def _fetch_row(conn, table: str, game_id: int) -> dict | None:
    rows = conn.execute(
        sa.text(f"SELECT * FROM {table} WHERE game_id = :g"), {"g": game_id}
    ).mappings().all()
    return dict(rows[0]) if rows else None


def _fill_count(row: dict | None, cols: list[str]) -> int:
    if row is None:
        return -1
    return sum(1 for col in cols if row.get(col) is not None)


def _merge_one_cell_table(conn, table: str, keeper: int, dup: int, cols: list[str]) -> str:
    keep = _fetch_row(conn, table, keeper)
    other = _fetch_row(conn, table, dup)
    if keep is None and other is None:
        return "none"
    if keep is not None and other is None:
        return "keep-only"
    if keep is None and other is not None:
        conn.execute(
            sa.text(f"UPDATE {table} SET game_id = :k WHERE game_id = :d"),
            {"k": keeper, "d": dup},
        )
        return "moved"
    if _fill_count(other, cols) > _fill_count(keep, cols):
        conn.execute(sa.text(f"DELETE FROM {table} WHERE game_id = :k"), {"k": keeper})
        conn.execute(
            sa.text(f"UPDATE {table} SET game_id = :k WHERE game_id = :d"),
            {"k": keeper, "d": dup},
        )
        return "adopted-dup"
    conn.execute(sa.text(f"DELETE FROM {table} WHERE game_id = :d"), {"d": dup})
    return "dropped-dup"


def report_references(conn, dup: int) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for table, col in _REF_TABLES:
        count = conn.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE {col} = :g"), {"g": dup}
        ).scalar()
        count = int(count or 0)
        if count:
            out.append((table, count))
    return out


def _merge_game_pair(conn, keeper: int, dup: int, canonical_name: str | None) -> dict:
    keeper_row = conn.execute(
        sa.text("SELECT id, name, slug FROM games WHERE id = :k"), {"k": keeper}
    ).mappings().first()
    dup_row = conn.execute(
        sa.text("SELECT id, name, slug FROM games WHERE id = :d"), {"d": dup}
    ).mappings().first()
    if keeper_row is None or dup_row is None:
        raise RuntimeError(f"Merge pair missing: keeper={keeper} dup={dup}")

    summary: dict = {
        "keeper": keeper,
        "dup": dup,
        "keeper_name": keeper_row["name"],
        "dup_name": dup_row["name"],
        "moved": report_references(conn, dup),
        "actions": {},
    }

    summary["actions"]["game_stats"] = _merge_one_cell_table(
        conn, "game_stats", keeper, dup, _GAME_STATS_COLS
    )
    summary["actions"]["game_metadata_igdb"] = _merge_one_cell_table(
        conn, "game_metadata_igdb", keeper, dup, _IGDB_COLS
    )
    summary["actions"]["game_metadata_hltb"] = _merge_one_cell_table(
        conn, "game_metadata_hltb", keeper, dup, _HLTB_COLS
    )

    for table in ("stream_games", "clips"):
        conn.execute(
            sa.text(f"UPDATE {table} SET game_id = :k WHERE game_id = :d"),
            {"k": keeper, "d": dup},
        )

    for table, partner_col in (
        ("streamer_games", "streamer_id"),
        ("game_recommendations", "user_id"),
        ("game_genres", "genre_id"),
        ("game_platforms", "platform_id"),
    ):
        conn.execute(
            sa.text(
                f"DELETE FROM {table} d USING {table} k "
                f"WHERE d.game_id = :dup AND k.game_id = :keeper "
                f"AND d.{partner_col} = k.{partner_col}"
            ),
            {"dup": dup, "keeper": keeper},
        )
        conn.execute(
            sa.text(f"UPDATE {table} SET game_id = :k WHERE game_id = :d"),
            {"k": keeper, "d": dup},
        )

    conn.execute(
        sa.text(
            "DELETE FROM game_aliases d USING game_aliases k "
            "WHERE d.game_id = :dup AND k.game_id = :keeper "
            "AND d.normalized_alias = k.normalized_alias"
        ),
        {"dup": dup, "keeper": keeper},
    )
    conn.execute(
        sa.text(
            "UPDATE game_aliases SET game_id = :k, is_primary = FALSE WHERE game_id = :d"
        ),
        {"k": keeper, "d": dup},
    )

    conn.execute(
        sa.text("UPDATE games SET parent_game_id = :k WHERE parent_game_id = :d"),
        {"k": keeper, "d": dup},
    )

    remaining = 0
    for table, col in _REF_TABLES:
        remaining += int(
            conn.execute(
                sa.text(f"SELECT count(*) FROM {table} WHERE {col} = :d"), {"d": dup}
            ).scalar()
            or 0
        )
    if remaining != 0:
        raise RuntimeError(f"Merge of game id={dup}: {remaining} dangling references")

    conn.execute(sa.text("DELETE FROM games WHERE id = :d"), {"d": dup})

    if canonical_name:
        canonical_slug = canonical_name.lower().replace(" ", "-")
        slug_in_use = conn.execute(
            sa.text("SELECT count(*) FROM games WHERE slug = :s AND id != :k"),
            {"s": canonical_slug, "k": keeper},
        ).scalar()
        if int(slug_in_use) == 0:
            conn.execute(
                sa.text(
                    "UPDATE games SET name = :name, slug = :slug, updated_at = now() "
                    "WHERE id = :k"
                ),
                {"name": canonical_name, "slug": canonical_slug, "k": keeper},
            )
            conn.execute(
                sa.text(
                    "UPDATE game_aliases SET alias = :name WHERE game_id = :k "
                    "AND is_primary = TRUE AND lower(alias) = lower(:name)"
                ),
                {"name": canonical_name, "k": keeper},
            )
            summary["actions"]["renamed"] = canonical_name
        else:
            summary["actions"]["renamed"] = f"SKIPPED slug in use: {canonical_slug}"
    return summary


def _parse_pairs(raw: list[str]) -> list[tuple[int, int, str | None]]:
    pairs: list[tuple[int, int, str | None]] = []
    for item in raw:
        parts = item.split(":", 2)
        if len(parts) < 2:
            raise SystemExit(f"Bad --pair value: {item!r} (expected keeper:dup[:name])")
        keeper, dup = int(parts[0]), int(parts[1])
        name = parts[2].replace("-", " ") if len(parts) == 3 and parts[2] else None
        pairs.append((keeper, dup, name))
    return pairs


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Merge duplicate game rows.")
    parser.add_argument("--apply", action="store_true", help="Commit changes (default: dry run).")
    parser.add_argument(
        "--pair",
        action="append",
        default=[],
        help="Override pairs: keeper:dup[:canonical-name], repeatable.",
    )
    args = parser.parse_args(argv)

    pairs = _parse_pairs(args.pair) if args.pair else DEFAULT_PAIRS

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            for keeper, dup, name in pairs:
                summary = _merge_game_pair(conn, keeper, dup, name)
                moved = ", ".join(f"{t}:{c}" for t, c in summary["moved"]) or "no refs"
                print(
                    f"MERGE {dup} -> {keeper}  ({summary['dup_name']!r} -> {summary['keeper_name']!r})\n"
                    f"   refs: {moved}\n"
                    f"   one-cell: {summary['actions'].get('game_stats')}/"
                    f"{summary['actions'].get('game_metadata_igdb')}/"
                    f"{summary['actions'].get('game_metadata_hltb')}"
                    + (f"\n   renamed: {summary['actions']['renamed']}" if "renamed" in summary["actions"] else "")
                )
        except Exception:
            trans.rollback()
            raise

        if args.apply:
            trans.commit()
            print(f"APPLIED: merged {len(pairs)} duplicate pair(s).")
        else:
            trans.rollback()
            print(f"DRY RUN: {len(pairs)} pair(s) would be merged (rolled back). Use --apply to commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
