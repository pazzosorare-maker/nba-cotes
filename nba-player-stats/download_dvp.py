"""Telecharge 'Defense vs Position' (FanDuel) depuis fantasypros.com, position par position."""
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup
from openpyxl import Workbook

URL = "https://www.fantasypros.com/daily-fantasy/nba/fanduel-defense-vs-position.php"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}

POSITIONS = ["PG", "SG", "SF", "PF", "C"]
GAME_RANGE = "GC-0"  # saison complete (vs GC-7/15/30 pour les derniers matchs)

OUTPUT_PATH = Path(__file__).parent / "fanduel_defense_vs_position.xlsx"


def fetch_soup(url: str) -> BeautifulSoup:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read()
    return BeautifulSoup(html, "lxml")


def extract_position_rows(soup: BeautifulSoup, position: str) -> tuple[list[str], list[list]]:
    table = soup.find(id="data-table")
    columns = ["Team Abbr", "Team"] + [
        th.get_text(strip=True) for th in table.find("thead").find_all("th")[1:]
    ]

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        classes = tr.get("class") or []
        if GAME_RANGE not in classes or position not in classes:
            continue

        team_cell = tr.find("td", class_="team-cell")
        abbr = team_cell.find("span").get_text(strip=True)
        team_name = team_cell.get_text(strip=True).replace(abbr, "", 1).strip()

        stats = [td.get_text(strip=True) for td in tr.find_all("td")[1:]]
        rows.append([abbr, team_name] + stats)

    return columns, rows


def main():
    soup = fetch_soup(URL)

    wb = Workbook()
    wb.remove(wb.active)

    for position in POSITIONS:
        columns, rows = extract_position_rows(soup, position)
        if not rows:
            raise RuntimeError(
                f"Aucune ligne trouvee pour la position '{position}' : la page a peut-etre change de structure."
            )

        ws = wb.create_sheet(title=position)
        ws.append(columns)
        for row in rows:
            ws.append(row)

        print(f"{len(rows)} equipes recuperees pour {position}")

    wb.save(OUTPUT_PATH)
    print(f"Fichier Excel cree -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
