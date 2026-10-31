"""Telecharge les tableaux de stats joueurs et equipes NBA depuis basketball-reference.com."""
import csv
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

from matchup_factors import SEASON_END_YEAR, season_file

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}

OUTPUT_DIR = Path(__file__).parent
BREF_LEAGUES = "https://www.basketball-reference.com/leagues"

TABLES = [
    {
        "url": f"{BREF_LEAGUES}/NBA_{SEASON_END_YEAR}_per_game.html",
        "table_id": "per_game_stats",
        "output": OUTPUT_DIR / season_file("per_game"),
    },
    {
        "url": f"{BREF_LEAGUES}/NBA_{SEASON_END_YEAR}_play-by-play.html",
        "table_id": "pbp_stats",
        "output": OUTPUT_DIR / season_file("play_by_play"),
        "column_renames": {
            "pct_1": "PG%",
            "pct_2": "SG%",
            "pct_3": "SF%",
            "pct_4": "PF%",
            "pct_5": "C%",
        },
    },
    {
        "url": f"{BREF_LEAGUES}/NBA_{SEASON_END_YEAR}.html",
        "table_id": "per_game-opponent",
        "output": OUTPUT_DIR / season_file("team_opponent_stats"),
    },
    {
        "url": f"{BREF_LEAGUES}/NBA_{SEASON_END_YEAR}.html",
        "table_id": "shooting-opponent",
        "output": OUTPUT_DIR / season_file("team_opponent_shooting"),
    },
    {
        "url": f"{BREF_LEAGUES}/NBA_{SEASON_END_YEAR}.html",
        "table_id": "per_game-team",
        "output": OUTPUT_DIR / season_file("team_stats"),
    },
    {
        "url": f"{BREF_LEAGUES}/NBA_{SEASON_END_YEAR}.html",
        "table_id": "advanced-team",
        "output": OUTPUT_DIR / season_file("team_advanced"),
    },
    {
        "url": f"{BREF_LEAGUES}/NBA_{SEASON_END_YEAR}_shooting.html",
        "table_id": "shooting",
        "output": OUTPUT_DIR / season_file("player_shooting"),
    },
]


def fetch_soup(url: str) -> BeautifulSoup:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read()
    return BeautifulSoup(html, "lxml")


def extract_table_rows(soup: BeautifulSoup, table_id: str) -> tuple[list[str], list[list[str]]]:
    table = soup.find("table", id=table_id)
    if table is None:
        raise RuntimeError(
            f"Tableau '{table_id}' introuvable : la page a peut-etre change de structure."
        )

    header_cells = table.find("thead").find_all("tr")[-1].find_all("th")
    columns = [th.get("data-stat") for th in header_cells]

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        if "thead" in (tr.get("class") or []):
            continue
        cells = tr.find_all(["th", "td"])
        rows.append([c.get_text(strip=True) for c in cells])

    return columns, rows


def main():
    soup_by_url = {}
    for table in TABLES:
        if table["url"] not in soup_by_url:
            soup_by_url[table["url"]] = fetch_soup(table["url"])

        columns, rows = extract_table_rows(soup_by_url[table["url"]], table["table_id"])

        renames = table.get("column_renames", {})
        columns = [renames.get(c, c) for c in columns]

        with table["output"].open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)

        print(f"{len(rows)} lignes recuperees -> {table['output']}")


if __name__ == "__main__":
    main()
