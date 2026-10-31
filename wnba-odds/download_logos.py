"""Telecharge les logos des 30 clubs NBA dans logos/ (une seule fois : les fichiers
deja presents sont ignores) et ecrit logos/teams.json (nom complet -> fichier).

Source : CDN d'images d'ESPN (a.espncdn.com), dont le robots.txt n'exclut pas ce chemin.
"""
import json
import urllib.request
from pathlib import Path

LOGOS_DIR = Path(__file__).parent / "logos"
LOGO_URL_TEMPLATE = "https://a.espncdn.com/i/teamlogos/nba/500/{code}.png"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}

# Nom complet de l'equipe (comme sur Winamax) -> code de logo ESPN.
TEAM_LOGO_CODE = {
    "Atlanta Hawks": "atl",
    "Boston Celtics": "bos",
    "Brooklyn Nets": "bkn",
    "Charlotte Hornets": "cha",
    "Chicago Bulls": "chi",
    "Cleveland Cavaliers": "cle",
    "Dallas Mavericks": "dal",
    "Denver Nuggets": "den",
    "Detroit Pistons": "det",
    "Golden State Warriors": "gs",
    "Houston Rockets": "hou",
    "Indiana Pacers": "ind",
    "Los Angeles Clippers": "lac",
    "Los Angeles Lakers": "lal",
    "Memphis Grizzlies": "mem",
    "Miami Heat": "mia",
    "Milwaukee Bucks": "mil",
    "Minnesota Timberwolves": "min",
    "New Orleans Pelicans": "no",
    "New York Knicks": "ny",
    "Oklahoma City Thunder": "okc",
    "Orlando Magic": "orl",
    "Philadelphia 76ers": "phi",
    "Phoenix Suns": "phx",
    "Portland Trail Blazers": "por",
    "Sacramento Kings": "sac",
    "San Antonio Spurs": "sa",
    "Toronto Raptors": "tor",
    "Utah Jazz": "utah",
    "Washington Wizards": "wsh",
}


def main():
    LOGOS_DIR.mkdir(exist_ok=True)

    downloaded = 0
    mapping = {}
    for team, code in TEAM_LOGO_CODE.items():
        path = LOGOS_DIR / f"{code}.png"
        if not path.exists():
            req = urllib.request.Request(LOGO_URL_TEMPLATE.format(code=code), headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                path.write_bytes(resp.read())
            downloaded += 1
        mapping[team] = f"logos/{code}.png"

    (LOGOS_DIR / "teams.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    print(f"{len(mapping)} logos prets ({downloaded} telecharges, {len(mapping) - downloaded} deja en cache).")


if __name__ == "__main__":
    main()
