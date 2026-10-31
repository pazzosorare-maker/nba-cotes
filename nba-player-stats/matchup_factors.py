"""Briques partagees : saison courante, noms d'equipes, lecture des CSV et profils joueurs
(moyennes de saison + repartition du temps de jeu par poste).

Utilise 2 fichiers locaux (aucune requete reseau) :
- nba_<saison>_per_game.csv          -> moyennes de saison du joueur
- nba_<saison>_play_by_play.csv      -> poids de poste du joueur (PG%..C%)
"""
import csv
from pathlib import Path

DATA_DIR = Path(__file__).parent

# Saison courante, au format basketball-reference (annee de fin : 2027 = saison 2026-27).
# Seul endroit a changer a la saison suivante.
SEASON_END_YEAR = 2027


def season_file(stem: str) -> str:
    return f"nba_{SEASON_END_YEAR}_{stem}.csv"


POSITIONS = ["PG", "SG", "SF", "PF", "C"]
PCT_COLUMNS = {"PG": "PG%", "SG": "SG%", "SF": "SF%", "PF": "PF%", "C": "C%"}

# Abreviation basketball-reference -> nom complet (cle canonique pour joindre les sources).
TEAM_FULL_NAME = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BRK": "Brooklyn Nets",
    "CHO": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHO": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}


def safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load_csv_rows(filename: str) -> list[dict]:
    with (DATA_DIR / filename).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def dedupe_by_player(rows: list[dict]) -> dict:
    """Garde, pour chaque joueur, la ligne agregee (2TM/3TM/4TM) si elle existe, sinon l'unique ligne."""
    by_name = {}
    for row in rows:
        name = row["name_display"]
        by_name.setdefault(name, []).append(row)

    result = {}
    for name, player_rows in by_name.items():
        aggregate = next(
            (r for r in player_rows if r.get("team_name_abbr") in ("2TM", "3TM", "4TM")),
            None,
        )
        result[name] = aggregate or player_rows[0]
    return result


def build_player_profiles() -> dict:
    per_game = dedupe_by_player(load_csv_rows(season_file("per_game")))
    pbp = dedupe_by_player(load_csv_rows(season_file("play_by_play")))

    common_names = (set(per_game) & set(pbp)) - {"League Average"}

    players = {}
    for name in common_names:
        pg_row = per_game[name]
        pbp_row = pbp[name]

        weights = {pos: safe_float(pbp_row.get(PCT_COLUMNS[pos])) for pos in POSITIONS}
        total_weight = sum(weights.values())
        if total_weight > 0:
            weights = {pos: w / total_weight for pos, w in weights.items()}
        else:
            # Repli : pas de donnees play-by-play exploitables -> 100% sur le poste principal.
            primary = (pg_row.get("pos") or "").split("-")[0]
            weights = {pos: (1.0 if pos == primary else 0.0) for pos in POSITIONS}

        players[name] = {
            "team": pg_row.get("team_name_abbr"),
            "baseline": {
                "pts": safe_float(pg_row.get("pts_per_g")),
                "reb": safe_float(pg_row.get("trb_per_g")),
                "ast": safe_float(pg_row.get("ast_per_g")),
                "mp": safe_float(pg_row.get("mp_per_g")),
            },
            "positionWeights": weights,
        }

    return players


# --------------------------------------------------------------- matchs joues (box-scores)
GAME_LOGS_PATH = DATA_DIR / f"game_logs_{SEASON_END_YEAR}.csv"
LOG_INT_COLUMNS = ["fg", "fga", "fg3", "fg3a", "ft", "fta", "orb", "drb", "trb", "ast", "stl", "blk", "tov", "pf", "pts"]
POSITION_MIN_MINUTES = 10  # en dessous, un joueur n'est pas retenu pour les analyses par poste (temps de jeu anecdotique)


def load_game_logs() -> list[dict]:
    """Une ligne par joueur et par match joue cette saison (game_logs_<saison>.csv)."""
    if not GAME_LOGS_PATH.exists():
        return []
    rows = []
    with GAME_LOGS_PATH.open(encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            row = {
                "game_id": raw["game_id"],
                "date": raw["date"],
                "team": raw["team"],
                "opponent": raw["opponent"],
                "home": raw["home"] == "1",
                "player": raw["player"],
                "mp": safe_float(raw["mp"]),
            }
            for col in LOG_INT_COLUMNS:
                row[col] = int(safe_float(raw[col]))
            plus_minus = raw.get("plus_minus", "")
            row["plus_minus"] = int(plus_minus) if plus_minus.lstrip("+-").isdigit() else None
            rows.append(row)
    return rows


def main_positions() -> dict:
    """Poste principal de chaque joueur = poste ou il passe le plus de temps (play-by-play) ;
    repli sur le poste liste par basketball-reference."""
    positions = {}
    for name, profile in build_player_profiles().items():
        weights = profile["positionWeights"]
        # max() garde le premier en cas d'egalite : ordre PG, SG, SF, PF, C
        positions[name] = max(POSITIONS, key=lambda pos: weights.get(pos, 0.0))
    for row in load_csv_rows(season_file("per_game")):
        name = row["name_display"]
        first = (row.get("pos") or "").split("-")[0]
        if name not in positions and first in POSITIONS:
            positions[name] = first
    return positions
