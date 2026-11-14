"""Tests for retrieval.py.

The fixture database is built with the real writer from scripts/refresh_stats.py,
so these tests also check that retrieval reads the schema the refresh script writes.
All stat values are made up.
"""

import sqlite3

import pytest

import retrieval
from names import normalize_name
from scripts.refresh_stats import write_db

SEASON = "2026-27"
REFRESHED = "2026-11-13T12:00:00+00:00"

DEN, OKC, LAL, WAS, NYK = 1, 2, 3, 4, 5
TEAMS = [
    (DEN, "DEN", "Denver Nuggets", "Denver", "Nuggets"),
    (OKC, "OKC", "Oklahoma City Thunder", "Oklahoma City", "Thunder"),
    (LAL, "LAL", "Los Angeles Lakers", "Los Angeles", "Lakers"),
    (WAS, "WAS", "Washington Wizards", "Washington", "Wizards"),
    (NYK, "NYK", "New York Knicks", "New York", "Knicks"),
]

(JOKIC, SGA, JALEN_W, JAYLIN_W, LEBRON, JJJ, KAT, BRUNSON, MARK_W,
 GRANT_W, ROBERT_W, PATRICK_W) = range(101, 113)
PLAYERS = [
    (JOKIC, "Nikola Jokić", DEN),
    (SGA, "Shai Gilgeous-Alexander", OKC),
    (JALEN_W, "Jalen Williams", OKC),
    (JAYLIN_W, "Jaylin Williams", OKC),
    (LEBRON, "LeBron James", LAL),
    (JJJ, "Jaren Jackson Jr.", WAS),
    (KAT, "Karl-Anthony Towns", NYK),
    (BRUNSON, "Jalen Brunson", NYK),
    (MARK_W, "Mark Williams", LAL),
    (GRANT_W, "Grant Williams", DEN),
    (ROBERT_W, "Robert Williams", WAS),
    (PATRICK_W, "Patrick Williams", NYK),
]
# Games played. Everyone not listed has 10. Six Williamses, so one is over the cap of 5.
GAMES_PLAYED = {JALEN_W: 12, MARK_W: 11, GRANT_W: 9, ROBERT_W: 6, PATRICK_W: 4, JAYLIN_W: 3}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "stats.sqlite"
    rows = {
        "teams": TEAMS,
        "players": [(pid, name, normalize_name(name), team) for pid, name, team in PLAYERS],
        "player_stats": [
            (pid, SEASON, GAMES_PLAYED.get(pid, 10), 34.0, 20.0, 5.0, 5.0, 1.0, 0.5, 2.0, 0.50, 0.35, 0.80)
            for pid, _, _ in PLAYERS
        ],
        "team_stats": [(tid, SEASON, 12, 8, 4, 115.0, 44.0, 27.0, 0.48, 0.36) for tid, *_ in TEAMS],
    }
    # Distinctive numbers for the rows the formatting tests check.
    rows["player_stats"][0] = (JOKIC, SEASON, 10, 35.0, 28.0, 12.0, 10.0, 1.5, 0.8, 3.0, 0.58, None, 0.82)
    rows["team_stats"][1] = (OKC, SEASON, 12, 10, 2, 120.0, 43.0, 26.0, 0.49, 0.36)
    write_db(rows, path, SEASON, REFRESHED)
    return path


@pytest.fixture
def conn(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


# --- players ---------------------------------------------------------------

@pytest.mark.parametrize("question, expected", [
    ("How is Nikola Jokic playing?", [JOKIC]),                         # full name, no accent typed
    ("Is Jokić the MVP favorite?", [JOKIC]),                           # unique last name, accent typed
    ("How many points does Gilgeous-Alexander average?", [SGA]),       # hyphenated last name
    ("shai gilgeous alexander stats", [SGA]),                          # lowercase, hyphen as space
    ("How many boards is Towns grabbing?", [KAT]),                     # last word of a two-word last name
    ("Jaren Jackson Jr. blocks per game", [JJJ]),                      # suffix in the full name
    ("Is Jackson healthy?", [JJJ]),                                    # suffix ignored for last name
    ("How is LeBron doing?", [LEBRON]),                                # unique first name
])
def test_find_players_single_match(conn, question, expected):
    assert retrieval.find_players(question, conn) == expected


def test_ambiguous_last_name_sorted_by_games_played_and_capped(conn):
    # Six Williamses: most games first, and the one with the fewest (Jaylin, 3 GP) is cut.
    found = retrieval.find_players("How is Williams shooting?", conn)
    assert found == [JALEN_W, MARK_W, GRANT_W, ROBERT_W, PATRICK_W]


def test_games_played_only_reorders_within_one_name(conn):
    # Separate names keep question order even when the later one has more games.
    found = retrieval.find_players("Patrick Williams or Mark Williams?", conn)
    assert found == [PATRICK_W, MARK_W]


def test_get_context_lists_ambiguous_candidates_by_games_played(db):
    text = retrieval.get_context("How is Williams shooting?", db)
    names = [line.split(" (")[0] for line in text.splitlines() if line.startswith("- ")]
    assert names == ["- Jalen Williams", "- Mark Williams", "- Grant Williams",
                     "- Robert Williams", "- Patrick Williams"]


def test_full_name_does_not_pull_in_namesakes(conn):
    assert retrieval.find_players("Jalen Williams stats", conn) == [JALEN_W]


def test_shared_first_name_matches_nobody(conn):
    assert retrieval.find_players("How is Jalen doing?", conn) == []


def test_players_keep_question_order_and_are_capped(conn):
    question = ("Compare Jalen Brunson, LeBron James, Nikola Jokic, Karl-Anthony Towns, "
                "Shai Gilgeous-Alexander and Jaren Jackson Jr.")
    assert retrieval.find_players(question, conn) == [BRUNSON, LEBRON, JOKIC, KAT, SGA]


def test_name_inside_a_longer_word_does_not_match(conn):
    assert retrieval.find_players("The Jokicverse is wild", conn) == []


# --- teams -----------------------------------------------------------------

@pytest.mark.parametrize("question, expected", [
    ("How are the Thunder doing?", [OKC]),                # nickname
    ("Denver Nuggets record", [DEN]),                     # full name
    ("Is OKC the best defense?", [OKC]),                  # uppercase abbreviation
    ("Knicks vs Lakers", [NYK, LAL]),                     # order of appearance
])
def test_find_teams(conn, question, expected):
    assert retrieval.find_teams(question, conn) == expected


def test_lowercase_word_is_not_an_abbreviation(conn):
    assert retrieval.find_teams("Who was the best scorer last night?", conn) == []
    assert retrieval.find_teams("Who has the best record, WAS or DEN?", conn) == [WAS, DEN]


# --- get_context -----------------------------------------------------------

def test_get_context_formats_player_rows(db):
    text = retrieval.get_context("How is Jokic shooting?", db)
    assert f"{SEASON} season" in text
    assert REFRESHED in text
    assert "- Nikola Jokić (DEN): 10 GP, 35.0 MIN, 28.0 PTS, 12.0 REB, 10.0 AST" in text
    assert "FG 58.0%, 3P n/a, FT 82.0%" in text   # missing 3P% shows as n/a


def test_get_context_formats_team_rows(db):
    text = retrieval.get_context("How are the Thunder doing?", db)
    assert "- Oklahoma City Thunder: 10-2 (12 GP), 120.0 PTS" in text
    assert "Players:" not in text


def test_get_context_returns_none_when_nothing_matches(db):
    assert retrieval.get_context("Who invented basketball?", db) is None


def test_get_context_returns_none_without_database(tmp_path, capsys):
    assert retrieval.get_context("How is Jokic?", tmp_path / "missing.sqlite") is None
    assert "No stats database" in capsys.readouterr().out


def test_get_context_reads_path_from_env(db, monkeypatch):
    monkeypatch.setenv("STATS_DB_PATH", str(db))
    assert "Nikola Jokić" in retrieval.get_context("Jokic?")


def test_get_context_opens_database_read_only(db, monkeypatch):
    conn = retrieval._connect_read_only(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM players")
    finally:
        conn.close()
