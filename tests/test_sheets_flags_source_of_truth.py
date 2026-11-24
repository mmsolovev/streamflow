"""Флаги «Понравилось/Пройдено/Интересует»: источник истины — только БД.

Google Sheets — витрина. Синхронизация не должна считывать эти флаги из листа
и не должна принимать «ручные» колонки из таблицы.
"""
import inspect

from pipeline.delivery import sheets_games, sheets_releases
from pipeline.delivery.sheets_utils import protect_columns
from pipeline.transform import sheets_transform


def _game_data(**overrides):
    data = {
        "last_stream": None,
        "streams_count": 0,
        "name": "Game",
        "rank": 1,
        "duration_minutes": 0,
        "hltb_all_styles": None,
        "steam_url": None,
        "liked": False,
        "completed": False,
        "tags": "PC",
    }
    data.update(overrides)
    return data


def test_expected_row_matches_sheet_rendering_of_db_flags():
    data = _game_data(liked=True, completed=False)
    # Так строка выглядит в Google Sheets: чекбоксы + результат формул I/K.
    sheet_row = ["", "0", "Game", "1", "0.0", "", "", "TRUE", "❤️", "FALSE", "", "PC"]

    assert sheets_games._game_expected_row(data) == sheets_games._game_comparable_row(
        sheet_row
    )


def test_sheet_flag_mismatch_is_detected_for_overwrite():
    data = _game_data(liked=False, completed=False)
    # В таблице кто-то отметил чекбоксы вручную — синхронизация должна
    # увидеть расхождение и перезаписать лист значением из БД.
    sheet_row = ["", "0", "Game", "1", "0.0", "", "", "TRUE", "❤️", "TRUE", "✅", "PC"]

    assert sheets_games._game_expected_row(data) != sheets_games._game_comparable_row(
        sheet_row
    )


def test_release_expected_row_matches_sheet_rendering_of_db_flags():
    data = {
        "name": "Upcoming",
        "release_date": None,
        "steam_url": None,
        "description_ru": None,
        "streamer_interested": True,
        "platforms_text": "PC",
        "genres_text": "RPG",
        "recommenders": [],
    }
    sheet_row = ["", "", "Upcoming", "", "", "TRUE", "👍", "", "", "", "PC | RPG", ""]

    assert sheets_releases._release_expected_row(
        data
    ) == sheets_releases._release_comparable_row(sheet_row)


def test_rows_do_not_accept_manual_columns():
    assert (
        "manual_columns"
        not in inspect.signature(sheets_games._build_game_row).parameters
    )
    assert (
        "manual_columns"
        not in inspect.signature(sheets_releases._build_release_row).parameters
    )


def test_reverse_sync_helpers_are_gone():
    assert not hasattr(sheets_games, "_sync_game_manual_fields_from_sheet")
    assert not hasattr(sheets_transform, "parse_sheet_bool")


class _FakeSpreadsheet:
    def __init__(self, metadata):
        self.metadata = metadata
        self.batch_updates = []
        self.fail = False

    def fetch_sheet_metadata(self):
        return self.metadata

    def batch_update(self, body):
        if self.fail:
            raise RuntimeError("boom")
        self.batch_updates.append(body)


class _FakeSheet:
    id = 42

    def __init__(self, spreadsheet):
        self.spreadsheet = spreadsheet


def test_protects_each_flag_column():
    spreadsheet = _FakeSpreadsheet({"sheets": [{"properties": {"sheetId": 42}}]})
    protect_columns(_FakeSheet(spreadsheet), (7, 9), description="flags")

    requests = spreadsheet.batch_updates[0]["requests"]
    assert len(requests) == 2
    ranges = [
        request["addProtectedRange"]["protectedRange"] for request in requests
    ]
    assert [item["range"]["startColumnIndex"] for item in ranges] == [7, 9]
    assert [item["range"]["endColumnIndex"] for item in ranges] == [8, 10]
    assert all(item["warningOnly"] is False for item in ranges)


def test_existing_protection_is_not_duplicated():
    spreadsheet = _FakeSpreadsheet(
        {
            "sheets": [
                {
                    "properties": {"sheetId": 42},
                    "protectedRanges": [
                        {
                            "range": {
                                "startRowIndex": 8,
                                "endRowIndex": 1000,
                                "startColumnIndex": 7,
                                "endColumnIndex": 8,
                            }
                        }
                    ],
                }
            ]
        }
    )
    protect_columns(_FakeSheet(spreadsheet), (7,), description="flags")

    assert spreadsheet.batch_updates == []


def test_protection_failure_does_not_break_sync():
    spreadsheet = _FakeSpreadsheet({"sheets": [{"properties": {"sheetId": 42}}]})
    spreadsheet.fail = True

    protect_columns(_FakeSheet(spreadsheet), (5,), description="flags")
