"""Tests for scripts/refresh_stats.py and names.py.

All stat values below are made up. Nothing here touches the network:
fetch() is replaced with a fake that returns small hand-written tables.
"""

import sqlite3
from datetime import date

import pandas as pd
import pytest

from names import normalize_name
from scripts import refresh_stats

SEASON = "2026-27"

STATIC_TEAMS = [
    {"id": 1610612743, "abbreviation": "DEN", "full_name": "Denver Nuggets", "city": "Denver", "nickname": "Nuggets"},
    {"id": 1610612760, "abbreviation": "OKC", "full_name": "Oklahoma City Thunder", "city": "Oklahoma City", "nickname": "Thunder"},
]


def players_df():
    return pd.DataFrame([
        {"PLAYER_ID": 203999, "PLAYER_NAME": "Nikola Jokić", "TEAM_ID": 1610612743, "GP": 10,
         "MIN": 35.0, "PTS": 28.0, "REB": 12.0, "AST": 10.0, "STL": 1.5, "BLK": 0.8, "TOV": 3.0,
         "FG_PCT": 0.58, "FG3_PCT": 0.40, "FT_PCT": 0.82},
        {"PLAYER_ID": 1628983, "PLAYER_NAME": "Shai Gilgeous-Alexander", "TEAM_ID": 1610612760, "GP": 11,
         "MIN": 34.0, "PTS": 31.0, "REB": 5.0, "AST": 6.0, "STL": 2.0, "BLK": 1.0, "TOV": 2.2,
         "FG_PCT": 0.53, "FG3_PCT": float("nan"), "FT_PCT": 0.90},
    ])


def team_stats_df():
    return pd.DataFrame([
        {"TEAM_ID": 1610612743, "GP": 12, "W": 8, "L": 4, "PTS": 118.0, "REB": 45.0, "AST": 30.0, "FG_PCT": 0.50, "FG3_PCT": 0.37},
        {"TEAM_ID": 1610612760, "GP": 12, "W": 10, "L": 2, "PTS": 120.0, "REB": 43.0, "AST": 26.0, "FG_PCT": 0.49, "FG3_PCT": 0.36},
    ])


def query(db_path, sql, *params):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# --- names.py -------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Nikola Jokić", "nikola jokic"),
    ("Shai Gilgeous-Alexander", "shai gilgeous alexander"),
    ("D'Angelo Russell", "d angelo russell"),
    ("  LeBron   James ", "lebron james"),
    ("Kristaps Porziņģis", "kristaps porzingis"),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


# --- season ---------------------------------------------------------------

@pytest.mark.parametrize("today, expected", [
    (date(2026, 11, 13), "2026-27"),  # early season
    (date(2027, 3, 1), "2026-27"),    # same season, next calendar year
    (date(2026, 10, 1), "2026-27"),   # first day of October
    (date(2026, 9, 30), "2025-26"),   # offseason: last completed season
])
def test_current_season(today, expected):
    assert refresh_stats.current_season(today) == expected


# --- transform ------------------------------------------------------------

def test_build_rows_maps_api_columns():
    rows = refresh_stats.build_rows(players_df(), team_stats_df(), STATIC_TEAMS, SEASON)

    assert (203999, "Nikola Jokić", "nikola jokic", 1610612743) in rows["players"]
    jokic = next(r for r in rows["player_stats"] if r[0] == 203999)
    assert jokic == (203999, SEASON, 10, 35.0, 28.0, 12.0, 10.0, 1.5, 0.8, 3.0, 0.58, 0.40, 0.82)

    assert (1610612760, "OKC", "Oklahoma City Thunder", "Oklahoma City", "Thunder") in rows["teams"]
    assert (1610612760, SEASON, 12, 10, 2, 120.0, 43.0, 26.0, 0.49, 0.36) in rows["team_stats"]


def test_build_rows_turns_nan_into_none():
    rows = refresh_stats.build_rows(players_df(), team_stats_df(), STATIC_TEAMS, SEASON)
    sga = next(r for r in rows["player_stats"] if r[0] == 1628983)
    fg3_pct = sga[11]
    assert fg3_pct is None  # stored as SQL NULL, not NaN


# --- database -------------------------------------------------------------

def test_write_db_round_trip(tmp_path):
    db = tmp_path / "data" / "stats.sqlite"
    rows = refresh_stats.build_rows(players_df(), team_stats_df(), STATIC_TEAMS, SEASON)

    refresh_stats.write_db(rows, db, SEASON, "2026-11-13T12:00:00+00:00")

    assert query(db, "SELECT full_name FROM players WHERE name_normalized = ?", "nikola jokic") == [("Nikola Jokić",)]
    assert query(db, "SELECT pts, ast FROM player_season_stats WHERE player_id = ?", 203999) == [(28.0, 10.0)]
    assert query(db, "SELECT w, l FROM team_season_stats WHERE team_id = ?", 1610612760) == [(10, 2)]
    assert dict(query(db, "SELECT key, value FROM meta")) == {
        "season": SEASON,
        "last_refreshed": "2026-11-13T12:00:00+00:00",
        "source": "nba_api (stats.nba.com)",
    }


def test_write_db_replaces_old_data_and_leaves_no_temp_files(tmp_path):
    db = tmp_path / "stats.sqlite"
    rows = refresh_stats.build_rows(players_df(), team_stats_df(), STATIC_TEAMS, SEASON)
    refresh_stats.write_db(rows, db, SEASON, "old")
    refresh_stats.write_db(rows, db, SEASON, "new")

    assert query(db, "SELECT value FROM meta WHERE key = 'last_refreshed'") == [("new",)]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["stats.sqlite"]


# --- main -----------------------------------------------------------------

def test_main_writes_database(tmp_path, monkeypatch, capsys):
    db = tmp_path / "stats.sqlite"
    monkeypatch.setattr(refresh_stats, "fetch", lambda season: (players_df(), team_stats_df(), STATIC_TEAMS))

    refresh_stats.main(["--season", SEASON, "--db", str(db)])

    assert query(db, "SELECT COUNT(*) FROM players") == [(2,)]
    assert "Wrote 2 players and 2 teams" in capsys.readouterr().out


def test_main_keeps_existing_database_when_api_returns_nothing(tmp_path, monkeypatch):
    db = tmp_path / "stats.sqlite"
    good = refresh_stats.build_rows(players_df(), team_stats_df(), STATIC_TEAMS, SEASON)
    refresh_stats.write_db(good, db, SEASON, "good")

    empty = pd.DataFrame(columns=players_df().columns)
    monkeypatch.setattr(refresh_stats, "fetch", lambda season: (empty, team_stats_df(), STATIC_TEAMS))

    with pytest.raises(SystemExit, match="keeping the existing database"):
        refresh_stats.main(["--season", SEASON, "--db", str(db)])

    assert query(db, "SELECT value FROM meta WHERE key = 'last_refreshed'") == [("good",)]
