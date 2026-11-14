"""Refresh data/stats.sqlite with current-season NBA stats from nba_api.

Run from the repo root, on a machine that can reach NBA.com (your Mac, not a cloud server):

    python -m scripts.refresh_stats
    python -m scripts.refresh_stats --season 2026-27
"""

import argparse
import math
import os
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from names import normalize_name

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "stats.sqlite"

SCHEMA = """
CREATE TABLE teams (
    team_id      INTEGER PRIMARY KEY,
    abbreviation TEXT NOT NULL,
    full_name    TEXT NOT NULL,
    city         TEXT NOT NULL,
    nickname     TEXT NOT NULL
);
CREATE TABLE players (
    player_id       INTEGER PRIMARY KEY,
    full_name       TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    team_id         INTEGER
);
CREATE INDEX idx_players_name ON players (name_normalized);
CREATE TABLE player_season_stats (
    player_id INTEGER NOT NULL REFERENCES players (player_id),
    season    TEXT    NOT NULL,
    gp INTEGER, min REAL, pts REAL, reb REAL, ast REAL, stl REAL, blk REAL, tov REAL,
    fg_pct REAL, fg3_pct REAL, ft_pct REAL,
    PRIMARY KEY (player_id, season)
);
CREATE TABLE team_season_stats (
    team_id INTEGER NOT NULL REFERENCES teams (team_id),
    season  TEXT    NOT NULL,
    gp INTEGER, w INTEGER, l INTEGER, pts REAL, reb REAL, ast REAL, fg_pct REAL, fg3_pct REAL,
    PRIMARY KEY (team_id, season)
);
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def current_season(today: date) -> str:
    """NBA seasons start in October: Nov 2026 -> "2026-27", Mar 2027 -> "2026-27"."""
    start = today.year if today.month >= 10 else today.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def fetch(season: str):
    """Network step: download stats from NBA.com. Never run in tests or CI.

    nba_api is imported here, not at the top, so the server and the tests
    never need it to be importable or reachable.
    """
    from nba_api.stats.endpoints import leaguedashplayerstats, leaguedashteamstats
    from nba_api.stats.static import teams

    players = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season, per_mode_detailed="PerGame", timeout=60
    ).get_data_frames()[0]
    team_stats = leaguedashteamstats.LeagueDashTeamStats(
        season=season, per_mode_detailed="PerGame", timeout=60
    ).get_data_frames()[0]
    return players, team_stats, teams.get_teams()


def _num(value):
    """Convert to float, turning missing values (None or NaN) into None (SQL NULL)."""
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else value


def build_rows(players_df, team_stats_df, static_teams, season):
    """Pure transform from API data to table rows. Tested without the network."""
    teams = [
        (t["id"], t["abbreviation"], t["full_name"], t["city"], t["nickname"])
        for t in static_teams
    ]

    players, player_stats = [], []
    for r in players_df.to_dict("records"):
        pid = int(r["PLAYER_ID"])
        players.append((pid, r["PLAYER_NAME"], normalize_name(r["PLAYER_NAME"]), int(r["TEAM_ID"])))
        player_stats.append((
            pid, season, int(r["GP"]),
            _num(r["MIN"]), _num(r["PTS"]), _num(r["REB"]), _num(r["AST"]),
            _num(r["STL"]), _num(r["BLK"]), _num(r["TOV"]),
            _num(r["FG_PCT"]), _num(r["FG3_PCT"]), _num(r["FT_PCT"]),
        ))

    team_stats = [
        (
            int(r["TEAM_ID"]), season, int(r["GP"]), int(r["W"]), int(r["L"]),
            _num(r["PTS"]), _num(r["REB"]), _num(r["AST"]),
            _num(r["FG_PCT"]), _num(r["FG3_PCT"]),
        )
        for r in team_stats_df.to_dict("records")
    ]

    return {"teams": teams, "players": players, "player_stats": player_stats, "team_stats": team_stats}


def write_db(rows, db_path, season, refreshed_at):
    """Build the database in a temp file, then swap it in.

    The swap (os.replace) is atomic, so the server never reads a half-written
    file, and a failed refresh leaves the previous database untouched.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".sqlite.tmp", dir=db_path.parent)
    os.close(fd)
    try:
        conn = sqlite3.connect(tmp)
        try:
            with conn:  # one transaction: commits on success, rolls back on error
                conn.executescript(SCHEMA)
                conn.executemany("INSERT INTO teams VALUES (?, ?, ?, ?, ?)", rows["teams"])
                conn.executemany("INSERT INTO players VALUES (?, ?, ?, ?)", rows["players"])
                conn.executemany(
                    "INSERT INTO player_season_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows["player_stats"],
                )
                conn.executemany(
                    "INSERT INTO team_season_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows["team_stats"],
                )
                conn.executemany(
                    "INSERT INTO meta VALUES (?, ?)",
                    [
                        ("season", season),
                        ("last_refreshed", refreshed_at),
                        ("source", "nba_api (stats.nba.com)"),
                    ],
                )
        finally:
            conn.close()
        os.replace(tmp, db_path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Refresh the local NBA stats database.")
    parser.add_argument("--season", default=current_season(date.today()), help='e.g. "2026-27"')
    parser.add_argument("--db", default=os.getenv("STATS_DB_PATH", str(DEFAULT_DB_PATH)))
    args = parser.parse_args(argv)

    players_df, team_stats_df, static_teams = fetch(args.season)
    rows = build_rows(players_df, team_stats_df, static_teams, args.season)

    if not rows["players"] or not rows["team_stats"]:
        raise SystemExit(f"No stats returned for {args.season}; keeping the existing database.")

    refreshed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_db(rows, args.db, args.season, refreshed_at)
    print(
        f"Wrote {len(rows['players'])} players and {len(rows['team_stats'])} teams "
        f"for {args.season} to {args.db} (refreshed {refreshed_at})"
    )


if __name__ == "__main__":
    main()
