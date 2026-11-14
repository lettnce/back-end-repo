"""Find the players and teams a question mentions and look up their stats.

Reads the SQLite file written by scripts/refresh_stats.py. Never calls the network.

    context = get_context("How is Jokic shooting from three?")
    # -> a text block of stat rows for the prompt, or None if nothing matched
"""

import os
import re
import sqlite3
from pathlib import Path

from names import normalize_name

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "stats.sqlite"

MAX_PLAYERS = 5            # cap on player rows sent to the model
MAX_TEAMS = 4              # cap on team rows sent to the model
MIN_SINGLE_NAME_LEN = 3    # ignore one-word matches shorter than this ("ii", "aj")
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def stats_db_path() -> Path:
    return Path(os.getenv("STATS_DB_PATH", str(DEFAULT_DB_PATH)))


def _connect_read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _position(phrase: str, padded_question: str) -> int:
    """Where `phrase` appears as whole words in the padded question, or -1."""
    return padded_question.find(f" {phrase} ")


def _blank_out(padded_question: str, phrase: str) -> str:
    """Replace every whole-word occurrence of `phrase` with spaces (positions are kept)."""
    target = f" {phrase} "
    return padded_question.replace(target, " " * len(target))


def find_players(question: str, conn: sqlite3.Connection) -> list:
    """Player ids mentioned in the question, capped at MAX_PLAYERS.

    Ordered by where each name appears in the question. Several players matched by
    the same name (an ambiguous last name) are ordered by games played, most first,
    so the cap keeps the regulars.
    """
    q = f" {normalize_name(question)} "
    rows = conn.execute(
        """
        SELECT p.player_id, p.name_normalized, COALESCE(s.gp, 0) AS gp
        FROM players p
        LEFT JOIN player_season_stats s
            ON s.player_id = p.player_id
            AND s.season = (SELECT value FROM meta WHERE key = 'season')
        """
    ).fetchall()
    games = {r["player_id"]: r["gp"] for r in rows}
    hits = {}  # player_id -> position in the question

    # 1. Full names. Blank them out so "Jalen Williams" doesn't also match every Williams.
    remaining = q
    for r in rows:
        pos = _position(r["name_normalized"], q)
        if pos >= 0:
            hits[r["player_id"]] = pos
            remaining = _blank_out(remaining, r["name_normalized"])

    # 2. One-name mentions in what's left of the question.
    last_names, first_names = {}, {}
    for r in rows:
        tokens = [t for t in r["name_normalized"].split() if t not in NAME_SUFFIXES]
        if len(tokens) < 2:
            continue
        first_names.setdefault(tokens[0], set()).add(r["player_id"])
        # "karl anthony towns" -> keys "anthony towns" and "towns"
        for key in {" ".join(tokens[1:]), tokens[-1]}:
            last_names.setdefault(key, set()).add(r["player_id"])

    # Last names: an ambiguous one returns every candidate, so the model can ask which.
    for key, ids in last_names.items():
        pos = _position(key, remaining) if len(key) >= MIN_SINGLE_NAME_LEN else -1
        if pos >= 0:
            for pid in ids:
                hits.setdefault(pid, pos)

    # First names count only when exactly one player has it ("LeBron" yes, "Jalen" no).
    for key, ids in first_names.items():
        if len(ids) == 1 and len(key) >= MIN_SINGLE_NAME_LEN:
            pos = _position(key, remaining)
            if pos >= 0:
                hits.setdefault(next(iter(ids)), pos)

    ordered = sorted(hits, key=lambda pid: (hits[pid], -games[pid], pid))
    return ordered[:MAX_PLAYERS]


def find_teams(question: str, conn: sqlite3.Connection) -> list:
    """Team ids mentioned in the question, in order of appearance, capped at MAX_TEAMS."""
    q = f" {normalize_name(question)} "
    hits = {}
    for r in conn.execute("SELECT team_id, abbreviation, full_name, nickname FROM teams"):
        positions = [
            _position(normalize_name(r["full_name"]), q),
            _position(normalize_name(r["nickname"]), q),
        ]
        # Abbreviations must be uppercase in the original question: "WAS" is the
        # Wizards, but "who was" is not.
        if re.search(rf"\b{re.escape(r['abbreviation'])}\b", question):
            positions.append(_position(r["abbreviation"].lower(), q))
        found = [p for p in positions if p >= 0]
        if found:
            hits[r["team_id"]] = min(found)
    ordered = sorted(hits, key=lambda tid: (hits[tid], tid))
    return ordered[:MAX_TEAMS]


def lookup(conn: sqlite3.Connection, player_ids: list, team_ids: list):
    """Stat rows for the given ids, in the same order, plus the database's meta values."""
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    season = meta.get("season")

    players = []
    for pid in player_ids:
        row = conn.execute(
            """
            SELECT p.full_name, t.abbreviation AS team, s.*
            FROM players p
            JOIN player_season_stats s ON s.player_id = p.player_id AND s.season = ?
            LEFT JOIN teams t ON t.team_id = p.team_id
            WHERE p.player_id = ?
            """,
            (season, pid),
        ).fetchone()
        if row:
            players.append(row)

    teams = []
    for tid in team_ids:
        row = conn.execute(
            """
            SELECT t.full_name, s.*
            FROM teams t
            JOIN team_season_stats s ON s.team_id = t.team_id AND s.season = ?
            WHERE t.team_id = ?
            """,
            (season, tid),
        ).fetchone()
        if row:
            teams.append(row)

    return meta, players, teams


def _num(value) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def _pct(value) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def format_context(meta: dict, players: list, teams: list) -> str:
    """Plain-text block of stats for the prompt."""
    lines = [
        f"NBA stats for the {meta.get('season', 'current')} season, per game "
        f"(data refreshed {meta.get('last_refreshed', 'unknown')}):"
    ]
    if players:
        lines.append("Players:")
        for p in players:
            team = f" ({p['team']})" if p["team"] else ""
            lines.append(
                f"- {p['full_name']}{team}: {p['gp']} GP, {_num(p['min'])} MIN, "
                f"{_num(p['pts'])} PTS, {_num(p['reb'])} REB, {_num(p['ast'])} AST, "
                f"{_num(p['stl'])} STL, {_num(p['blk'])} BLK, {_num(p['tov'])} TOV, "
                f"FG {_pct(p['fg_pct'])}, 3P {_pct(p['fg3_pct'])}, FT {_pct(p['ft_pct'])}"
            )
    if teams:
        lines.append("Teams:")
        for t in teams:
            lines.append(
                f"- {t['full_name']}: {t['w']}-{t['l']} ({t['gp']} GP), {_num(t['pts'])} PTS, "
                f"{_num(t['reb'])} REB, {_num(t['ast'])} AST, "
                f"FG {_pct(t['fg_pct'])}, 3P {_pct(t['fg3_pct'])}"
            )
    return "\n".join(lines)


def get_context(question: str, db_path=None):
    """Stats text for the players and teams in `question`, or None.

    None means "answer without stats": nothing matched, or there is no database yet.
    """
    path = Path(db_path) if db_path else stats_db_path()
    if not path.exists():
        print(f"[Retrieval] No stats database at {path}; answering without stats.")
        return None

    conn = _connect_read_only(path)
    try:
        player_ids = find_players(question, conn)
        team_ids = find_teams(question, conn)
        if not player_ids and not team_ids:
            return None
        meta, players, teams = lookup(conn, player_ids, team_ids)
        if not players and not teams:
            return None
        return format_context(meta, players, teams)
    finally:
        conn.close()
