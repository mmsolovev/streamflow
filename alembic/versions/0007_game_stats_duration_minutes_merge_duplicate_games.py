"""game_stats in minutes; merge duplicate games by case

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-16

Summary:
1. Renames game_stats.streamed_hours (Float, hours) -> duration_minutes (Integer, minutes),
   converting existing values via round(hours * 60).
2. Merges 4 duplicate game pairs (same game under differing case) into a single row,
   repointing all FK references; the canonical casing/register is owned by the keeper row.

Note on merge choices:
- For game_stats / game_metadata_igdb / game_metadata_hltb the most filled row wins
  (max non-NULL metric columns); on tie the keeper row is kept. Data is never summed.
- The merge is destructive (downgrade restores only the column rename).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# canonical keeper = row whose current name matches the canonical register
GAME_PAIRS = [
    {"keeper": 452, "dup": 624, "name": "MATRESHKA"},
    {"keeper": 1196, "dup": 57, "name": "INSIDE"},
    {"keeper": 325, "dup": 600, "name": "SLEEP AWAKE"},
    {"keeper": 472, "dup": 465, "name": "DIRECTIVE 8020"},
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


def _fetch_row(conn, table: str, game_id: int) -> dict | None:
    rows = conn.execute(
        sa.text(f"SELECT * FROM {table} WHERE game_id = :g"), {"g": game_id}
    ).mappings().all()
    return dict(rows[0]) if rows else None


def _fill_count(row: dict | None, cols: list[str]) -> int:
    if row is None:
        return -1
    return sum(1 for col in cols if row.get(col) is not None)


def _merge_one_cell_table(conn, table: str, keeper: int, dup: int, cols: list[str]) -> None:
    keep = _fetch_row(conn, table, keeper)
    other = _fetch_row(conn, table, dup)
    if keep is None and other is None:
        return
    if keep is not None and other is None:
        return
    if keep is None and other is not None:
        conn.execute(
            sa.text(f"UPDATE {table} SET game_id = :k WHERE game_id = :d"),
            {"k": keeper, "d": dup},
        )
        return
    # both exist: keep the most filled; tie -> keeper.
    # When the dup is more filled we drop the keeper's row first and adopt the
    # dup's row under the keeper id, which also avoids unique-column clashes.
    if _fill_count(other, cols) > _fill_count(keep, cols):
        conn.execute(sa.text(f"DELETE FROM {table} WHERE game_id = :k"), {"k": keeper})
        conn.execute(
            sa.text(f"UPDATE {table} SET game_id = :k WHERE game_id = :d"),
            {"k": keeper, "d": dup},
        )
    else:
        conn.execute(sa.text(f"DELETE FROM {table} WHERE game_id = :d"), {"d": dup})


def _merge_game_pair(conn, keeper: int, dup: int, canonical_name: str) -> None:
    keeper_exists = conn.execute(
        sa.text("SELECT 1 FROM games WHERE id = :k"), {"k": keeper}
    ).scalar()
    dup_exists = conn.execute(
        sa.text("SELECT 1 FROM games WHERE id = :d"), {"d": dup}
    ).scalar()
    if not keeper_exists or not dup_exists:
        raise RuntimeError(f"Merge pair missing: keeper={keeper} dup={dup}")

    # 1. game_stats / game_metadata: keep the most filled row (tie -> keeper)
    _merge_one_cell_table(conn, "game_stats", keeper, dup, _GAME_STATS_COLS)
    _merge_one_cell_table(conn, "game_metadata_igdb", keeper, dup, _IGDB_COLS)
    _merge_one_cell_table(conn, "game_metadata_hltb", keeper, dup, _HLTB_COLS)

    # 2. plain FK tables
    for table in ("stream_games", "clips"):
        conn.execute(
            sa.text(f"UPDATE {table} SET game_id = :k WHERE game_id = :d"),
            {"k": keeper, "d": dup},
        )

    # 3. composite-PK tables: drop conflicts (same partner under keeper), then repoint
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

    # 4. aliases: drop duplicates by normalized_alias, repoint the rest, drop is_primary
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
        sa.text(
            "UPDATE game_aliases SET alias = :name "
            "WHERE game_id = :k AND is_primary = TRUE "
            "AND lower(alias) = lower(:name)"
        ),
        {"name": canonical_name, "k": keeper},
    )

    # 5. self-reference safety, then delete duplicate game row
    conn.execute(
        sa.text("UPDATE games SET parent_game_id = :k WHERE parent_game_id = :d"),
        {"k": keeper, "d": dup},
    )
    remaining = conn.execute(
        sa.text(
            "SELECT count(*) AS c FROM ("
            " SELECT game_id FROM game_aliases WHERE game_id = :d"
            " UNION ALL SELECT game_id FROM stream_games WHERE game_id = :d"
            " UNION ALL SELECT game_id FROM clips WHERE game_id = :d"
            " UNION ALL SELECT game_id FROM streamer_games WHERE game_id = :d"
            " UNION ALL SELECT game_id FROM game_recommendations WHERE game_id = :d"
            " UNION ALL SELECT game_id FROM game_genres WHERE game_id = :d"
            " UNION ALL SELECT game_id FROM game_platforms WHERE game_id = :d"
            " UNION ALL SELECT game_id FROM game_metadata_igdb WHERE game_id = :d"
            " UNION ALL SELECT game_id FROM game_metadata_hltb WHERE game_id = :d"
            " UNION ALL SELECT game_id FROM game_stats WHERE game_id = :d) t"
        ),
        {"d": dup},
    ).scalar()
    if int(remaining) != 0:
        raise RuntimeError(f"Merge of game id={dup}: {remaining} dangling references")

    conn.execute(sa.text("DELETE FROM games WHERE id = :d"), {"d": dup})

    # 6. adopt canonical name/slug on the keeper (dup is gone, so slug is free)
    canonical_slug = canonical_name.lower().replace(" ", "-")
    slug_in_use = conn.execute(
        sa.text("SELECT count(*) FROM games WHERE slug = :s AND id != :k"),
        {"s": canonical_slug, "k": keeper},
    ).scalar()
    if int(slug_in_use) == 0:
        conn.execute(
            sa.text(
                "UPDATE games SET name = :name, slug = :slug, "
                "updated_at = now() WHERE id = :k"
            ),
            {"name": canonical_name, "slug": canonical_slug, "k": keeper},
        )


def upgrade() -> None:
    # --- 2a. game_stats: hours -> minutes ---
    op.alter_column(
        "game_stats",
        "streamed_hours",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        postgresql_using="round(streamed_hours * 60)::int",
    )
    op.alter_column(
        "game_stats",
        "streamed_hours",
        new_column_name="duration_minutes",
        existing_type=sa.Integer(),
    )

    conn = op.get_bind()
    for pair in GAME_PAIRS:
        _merge_game_pair(
            conn,
            keeper=int(pair["keeper"]),
            dup=int(pair["dup"]),
            canonical_name=str(pair["name"]),
        )


def downgrade() -> None:
    # Column conversion is reversible; the duplicate-game merge is not.
    op.alter_column(
        "game_stats",
        "duration_minutes",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        postgresql_using="duration_minutes::float / 60",
    )
    op.alter_column(
        "game_stats",
        "duration_minutes",
        new_column_name="streamed_hours",
        existing_type=sa.Float(),
    )