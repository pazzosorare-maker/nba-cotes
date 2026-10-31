"""Telecharge les stats joueur x match (box-scores) de la saison NBA en cours
depuis basketball-reference.com : tous les matchs deja joues cette saison.

Source : les pages de box-score par match (/boxscores/...), autorisees par le
robots.txt de basketball-reference. Les pages "game log" par joueur, elles, sont
interdites (Disallow: */gamelog/). Le Crawl-delay de 3s est respecte.

Le script est reprenable : les matchs deja presents dans le CSV sont ignores, il
suffit donc de le relancer pour ajouter les nouveaux matchs. Duree : ~3 s par
nouveau match (une dizaine de minutes apres un mois de saison).
"""
import csv
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

from matchup_factors import SEASON_END_YEAR

BASE_URL = "https://www.basketball-reference.com"
DELAY_BETWEEN_REQUESTS_SECONDS = 3  # Crawl-delay impose par robots.txt

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}

OUTPUT_PATH = Path(__file__).parent / f"game_logs_{SEASON_END_YEAR}.csv"

BOX_SCORE_URL_RE = re.compile(r"/boxscores/(\d{8})0([A-Z]{3})\.html")
STAT_COLUMNS = [
    "fg", "fga", "fg_pct", "fg3", "fg3a", "fg3_pct", "ft", "fta", "ft_pct",
    "orb", "drb", "trb", "ast", "stl", "blk", "tov", "pf", "pts", "plus_minus",
]
FIELDNAMES = ["game_id", "date", "team", "opponent", "home", "player", "mp"] + STAT_COLUMNS


def fetch_soup(url: str, attempts: int = 4) -> BeautifulSoup:
    """Un scrape de plusieurs minutes peut subir des coupures : tentatives avec attente."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return BeautifulSoup(resp.read(), "lxml")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < attempts:
                wait = 10 * attempt
                print(f"    ...erreur reseau ({exc}), nouvelle tentative dans {wait}s")
                time.sleep(wait)
    raise last_error


def collect_played_box_score_urls() -> list[str]:
    """Liste les box-scores de tous les matchs deja joues, mois par mois."""
    hub = fetch_soup(f"{BASE_URL}/leagues/NBA_{SEASON_END_YEAR}_games.html")
    month_pages = [a["href"] for a in hub.find("div", class_="filter").find_all("a")]

    urls = []
    for href in month_pages:
        time.sleep(DELAY_BETWEEN_REQUESTS_SECONDS)
        soup = fetch_soup(BASE_URL + href)
        table = soup.find("table", id="schedule")
        if table is None:
            continue
        for tr in table.find("tbody").find_all("tr"):
            if "thead" in (tr.get("class") or []):
                continue
            box_cell = tr.find("td", {"data-stat": "box_score_text"})
            link = box_cell.find("a") if box_cell else None
            if link is not None:  # pas de lien = match pas encore joue
                urls.append(BASE_URL + link["href"])
    return urls


def game_id_from_url(url: str) -> str:
    game_date, home_abbr = BOX_SCORE_URL_RE.search(url).groups()
    return f"{game_date}0{home_abbr}"


def parse_box_score(url: str) -> list[dict]:
    game_date, home_abbr = BOX_SCORE_URL_RE.search(url).groups()
    game_date_iso = f"{game_date[0:4]}-{game_date[4:6]}-{game_date[6:8]}"
    game_id = game_id_from_url(url)

    soup = fetch_soup(url)
    tables = [t for t in soup.find_all("table") if t.get("id", "").endswith("-game-basic")]

    rows = []
    for table in tables:
        team_abbr = table["id"].split("-")[1]
        for tr in table.find("tbody").find_all("tr"):
            if "thead" in (tr.get("class") or []):
                continue  # sous-en-tete "Reserves"
            cells = {c.get("data-stat"): c for c in tr.find_all(["th", "td"])}
            if "reason" in cells:
                continue  # Did Not Play / Did Not Dress

            mp_text = cells["mp"].get_text(strip=True) if "mp" in cells else ""
            if ":" not in mp_text:
                continue
            minutes, seconds = mp_text.split(":")

            row = {
                "game_id": game_id,
                "date": game_date_iso,
                "team": team_abbr,
                "home": 1 if team_abbr == home_abbr else 0,
                "player": cells["player"].get_text(strip=True),
                "mp": round(int(minutes) + int(seconds) / 60, 2),
            }
            for stat in STAT_COLUMNS:
                row[stat] = cells[stat].get_text(strip=True) if stat in cells else ""
            rows.append(row)

    team_abbrs = {r["team"] for r in rows}
    for row in rows:
        row["opponent"] = next(iter(team_abbrs - {row["team"]}))
    return rows


def already_scraped_game_ids() -> set:
    if not OUTPUT_PATH.exists():
        return set()
    with OUTPUT_PATH.open(encoding="utf-8") as f:
        return {r["game_id"] for r in csv.DictReader(f)}


def main():
    print(f"Recuperation du calendrier de la saison {SEASON_END_YEAR - 1}-{str(SEASON_END_YEAR)[2:]}...")
    urls = collect_played_box_score_urls()
    print(f"{len(urls)} matchs deja joues.")

    done = already_scraped_game_ids()
    remaining = [u for u in urls if game_id_from_url(u) not in done]
    if done:
        print(f"{len(urls) - len(remaining)} matchs deja recuperes, {len(remaining)} nouveaux.")

    file_exists = OUTPUT_PATH.exists()
    with OUTPUT_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        for i, url in enumerate(remaining, start=1):
            time.sleep(DELAY_BETWEEN_REQUESTS_SECONDS)
            writer.writerows(parse_box_score(url))
            f.flush()
            if i % 10 == 0 or i == len(remaining):
                print(f"  {i}/{len(remaining)} matchs traites...")

    print(f"Termine -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
