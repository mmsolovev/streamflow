from database.models import Game, GameAlias
from pipeline.ingest.twitchtracker_parser import StreamGameEntry
from pipeline.orchestrator.import_twitchtracker_stream_pages import (
    _build_indexes,
    _merge_duplicate_entries,
    _resolve_game,
)


def test_twitchtracker_category_name_resolves_through_alias():
    game = Game(id=1, name="Senua's Saga: Hellblade II")
    alias = GameAlias(
        id=1,
        game_id=1,
        alias="Hellblade II: Senua's Saga",
        normalized_alias="hellblade ii senuas saga",
    )
    indexes = _build_indexes([game], [alias])

    resolved, error = _resolve_game(
        indexes,
        name="Hellblade II: Senua's Saga",
        twitch_game_id="515482",
        manual_map={},
    )

    assert error is None
    assert resolved is game


def test_category_id_and_name_conflict_is_not_guessed():
    canonical = Game(id=1, name="Senua's Saga: Hellblade II")
    id_owner = Game(id=2, name="Different game", twitch_category_id="515482")
    alias = GameAlias(
        id=1,
        game_id=1,
        alias="Hellblade II: Senua's Saga",
        normalized_alias="hellblade ii senuas saga",
    )
    indexes = _build_indexes([canonical, id_owner], [alias])

    resolved, error = _resolve_game(
        indexes,
        name="Hellblade II: Senua's Saga",
        twitch_game_id="515482",
        manual_map={},
    )

    assert resolved is None
    assert error is not None
    assert "points to game" in error


def test_repeated_category_cards_are_combined_by_duration():
    entries = [
        StreamGameEntry("Game", "42", 100, 180, 30, 2),
        StreamGameEntry("Game", "42", 200, 240, 90, 3),
    ]

    result = _merge_duplicate_entries(entries)

    assert len(result) == 1
    assert result[0].duration_minutes == 120
    assert result[0].avg_viewers == 175
    assert result[0].peak_viewers == 240
    assert result[0].followers_gained == 5
