"""Telecharge les photos des joueurs NBA dans photos/ (une seule fois : les fichiers deja
presents sont ignores) et ecrit photos/players.json (nom normalise -> fichier).

Source : fantasypros.com. La page des projections NBA donne l'identifiant FantasyPros de
chaque joueur (~260 joueurs, les plus utilises) ; la photo est servie en 70x70 par leur
serveur d'images (les tailles superieures sont refusees). Les autres joueurs s'affichent
avec un avatar a initiales cote application.

L'index des identifiants n'est rafraichi que s'il a plus de 3 jours : le script est quasi
instantane aux lancements suivants.
"""
import hashlib
import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

PHOTOS_DIR = Path(__file__).parent / "photos"
PLAYERS_PAGE = "https://www.fantasypros.com/nba/projections/overall.php"
PHOTO_URL_TEMPLATE = "https://images.fantasypros.com/images/players/nba/{fp_id}/headshot/70x70.png"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}
DELAY_BETWEEN_PHOTOS_SECONDS = 0.3
INDEX_MAX_AGE_SECONDS = 3 * 24 * 3600
PLACEHOLDER_MIN_COPIES = 4   # une meme image pour 4 joueurs ou plus = silhouette generique, pas une photo
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def norm_name(name: str) -> str:
    """Meme normalisation que les pages web (accents, ponctuation, suffixes Jr./III...)."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    tokens = "".join(c if c.isalnum() or c == " " else "" for c in text).split()
    while len(tokens) > 2 and tokens[-1] in NAME_SUFFIXES:
        tokens.pop()
    return "".join(tokens)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fantasypros_ids() -> dict:
    """{nom normalise: (identifiant FantasyPros, nom affiche)}"""
    soup = BeautifulSoup(fetch(PLAYERS_PAGE), "lxml")
    players = {}
    for link in soup.select("td.player-label a.player-name"):
        match = re.search(r"fp-id-(\d+)", " ".join(link.get("class", [])))
        if match:
            players[norm_name(link.get_text(strip=True))] = (match.group(1), link.get_text(strip=True))
    if len(players) < 100:
        raise RuntimeError("Page FantasyPros inattendue : moins de 100 joueurs trouves.")
    return players


def main():
    PHOTOS_DIR.mkdir(exist_ok=True)
    index_path = PHOTOS_DIR / "players.json"
    ids_path = PHOTOS_DIR / "fantasypros_ids.json"

    if ids_path.exists() and time.time() - ids_path.stat().st_mtime < INDEX_MAX_AGE_SECONDS:
        ids = json.loads(ids_path.read_text(encoding="utf-8"))
        ids = {k: tuple(v) for k, v in ids.items()}
    else:
        ids = fantasypros_ids()
        ids_path.write_text(json.dumps(ids, ensure_ascii=False), encoding="utf-8")

    downloaded = failed = 0
    digests = {}
    for key, (fp_id, _display_name) in ids.items():
        path = PHOTOS_DIR / f"{fp_id}.png"
        if not path.exists():
            try:
                path.write_bytes(fetch(PHOTO_URL_TEMPLATE.format(fp_id=fp_id)))
                downloaded += 1
                time.sleep(DELAY_BETWEEN_PHOTOS_SECONDS)
            except Exception:
                failed += 1
                continue
        digests.setdefault(hashlib.md5(path.read_bytes()).hexdigest(), []).append(key)

    placeholder_keys = {k for keys in digests.values() if len(keys) >= PLACEHOLDER_MIN_COPIES for k in keys}
    index = {
        key: f"photos/{fp_id}.png"
        for key, (fp_id, _name) in ids.items()
        if key not in placeholder_keys and (PHOTOS_DIR / f"{fp_id}.png").exists()
    }
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")
    print(
        f"{len(index)} photos pretes ({downloaded} telechargees, {failed} echec(s), "
        f"{len(placeholder_keys)} silhouette(s) generique(s) ignoree(s))."
    )


if __name__ == "__main__":
    main()
