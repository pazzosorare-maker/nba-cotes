"""Suivi dans le temps : conserve cotes et estimations AVANT chaque match, puis y
rattache le resultat reel une fois le match joue, pour mesurer la precision du modele
d'implication (et sa variante « + poste ») face a la moyenne de saison et aux lignes Winamax.

A chaque lancement :
1. Instantane : pour chaque match Winamax pas encore commence, enregistre les cotes
   (vainqueur + lignes PRA), les estimations du modele d'implication et de sa variante par poste,
   et la moyenne de saison,
   pour tous les joueurs des deux equipes. L'instantane est remplace a chaque lancement
   tant que le match n'a pas commence, puis fige (aucune donnee posterieure au coup d'envoi).
2. Resultats : pour les matchs termines, recupere les stats reelles dans les box-scores
   (game_logs_<saison>.csv) ; un joueur absent du box-score est marque DNP.

Les cotes passees ne peuvent pas etre retrouvees apres coup : data/history.json est
irremplacable. Il est ecrit de maniere atomique et sauvegarde chaque jour dans
data/backups/. Si le fichier est illisible, le script s'arrete sans rien ecraser.
"""
import csv
import json
import shutil
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import matchup_factors as mf

APP_DATA_DIR = Path(__file__).parent.parent / "wnba-odds" / "data"
ODDS_PATH = APP_DATA_DIR / "nba_odds.json"
PREDICTIONS_PATH = APP_DATA_DIR / "nba_predictions.json"
HISTORY_PATH = APP_DATA_DIR / "history.json"
BACKUP_DIR = APP_DATA_DIR / "backups"
GAME_LOGS_PATH = Path(__file__).parent / f"game_logs_{mf.SEASON_END_YEAR}.csv"

HISTORY_VERSION = 1
RESULT_DELAY_SECONDS = 3 * 3600  # un match est considere termine 3 h apres le coup d'envoi
BACKUPS_TO_KEEP = 14
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
ABBR_BY_TEAM = {full: abbr for abbr, full in mf.TEAM_FULL_NAME.items()}


def norm_name(name: str) -> str:
    """Meme normalisation que la page web : accents, ponctuation et suffixes (Jr., III...)."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    tokens = "".join(c if c.isalnum() or c == " " else "" for c in text).split()
    while len(tokens) > 2 and tokens[-1] in NAME_SUFFIXES:
        tokens.pop()
    return "".join(tokens)


# ---------------------------------------------------------------- instantanes

def make_record(name: str, player: dict | None, team: str, opponent: str) -> dict:
    involvement = player.get("involvement") if player else None
    baseline = player["baseline"] if player else None
    return {
        "player": name,
        "team": team,
        "opponent": opponent,
        "line": None,
        "overOdd": None,
        "underOdd": None,
        "baseline": {k: round(baseline[k], 1) for k in ("pts", "reb", "ast")} if baseline else None,
        "implication": involvement["predictions"].get(opponent) if involvement else None,
        "implicationPoste": (involvement.get("positionAdjusted") or {}).get(opponent) if involvement else None,
        "actual": None,
    }


def snapshot_match(match: dict, predictions: dict, snapshot_at: str) -> dict:
    team1, team2 = match["team1"], match["team2"]
    players = predictions["players"]
    key_by_norm = {norm_name(n): n for n in players}

    records = {}
    for name, player in players.items():
        involvement = player.get("involvement")
        team = involvement["team"] if involvement else None
        if team == team1:
            records[name] = make_record(name, player, team, team2)
        elif team == team2:
            records[name] = make_record(name, player, team, team1)

    for line in match.get("playerTotalPRA") or []:
        team, opponent = (team1, team2) if line["team"] == 1 else (team2, team1)
        key = key_by_norm.get(norm_name(line["player"]))
        record = records.get(key) if key else None
        if record is None or record["team"] != team:
            # Joueur inconnu du modele, ou equipe differente chez Winamax (echange recent).
            record = make_record(key or line["player"], players.get(key), team, opponent)
            records[record["player"]] = record
        record["winamaxName"] = line["player"]
        record["line"] = line["line"]
        record["overOdd"] = line["overOdd"]
        record["underOdd"] = line["underOdd"]

    return {
        "matchId": match["matchId"],
        "team1": team1,
        "team2": team2,
        "matchStart": match["matchStart"],
        "snapshotAt": snapshot_at,
        "odd1": match.get("odd1"),
        "odd2": match.get("odd2"),
        "status": "pending",
        "score": None,
        "players": sorted(records.values(), key=lambda r: (r["team"], r["player"])),
    }


def update_snapshots(history: dict, odds: dict, predictions: dict, now: float) -> int:
    snapshot_at = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    updated = 0
    for match in odds["matches"]:
        if not match.get("matchStart") or match["matchStart"] <= now:
            continue  # commence ou en cours : on ne fige jamais de donnees posterieures au coup d'envoi
        history["matches"][str(match["matchId"])] = snapshot_match(match, predictions, snapshot_at)
        updated += 1
    return updated


# ------------------------------------------------------------------ resultats

def index_game_logs(rows: list[dict]) -> dict:
    index = {}
    for row in rows:
        index.setdefault((row["date"], row["team"]), []).append(row)
    return index


def find_game(match: dict, logs_index: dict):
    team_a, team_b = ABBR_BY_TEAM[match["team1"]], ABBR_BY_TEAM[match["team2"]]
    utc_day = datetime.fromtimestamp(match["matchStart"], tz=timezone.utc).date()
    # Un match en soiree americaine tombe le lendemain en UTC : on teste les deux jours.
    for day in (utc_day - timedelta(days=1), utc_day):
        rows_a = logs_index.get((day.isoformat(), team_a))
        rows_b = logs_index.get((day.isoformat(), team_b))
        if rows_a and rows_b and rows_a[0]["opponent"] == team_b:
            return day.isoformat(), rows_a, rows_b
    return None


def fill_results(history: dict, logs_index: dict, now: float) -> int:
    filled = 0
    for match in history["matches"].values():
        if match["status"] == "final" or match["matchStart"] + RESULT_DELAY_SECONDS > now:
            continue
        game = find_game(match, logs_index)
        if game is None:
            continue  # box-score pas encore disponible
        game_date, rows_a, rows_b = game

        by_team = {match["team1"]: rows_a, match["team2"]: rows_b}
        played = {team: {norm_name(r["player"]): r for r in rows} for team, rows in by_team.items()}
        for record in match["players"]:
            row = played[record["team"]].get(norm_name(record["player"]))
            record["actual"] = (
                {
                    "pts": int(mf.safe_float(row["pts"])),
                    "reb": int(mf.safe_float(row["trb"])),
                    "ast": int(mf.safe_float(row["ast"])),
                    "mp": round(mf.safe_float(row["mp"]), 1),
                }
                if row
                else {"dnp": True}
            )

        match["score"] = {
            match["team1"]: int(sum(mf.safe_float(r["pts"]) for r in rows_a)),
            match["team2"]: int(sum(mf.safe_float(r["pts"]) for r in rows_b)),
        }
        match["gameDate"] = game_date
        match["status"] = "final"
        filled += 1
    return filled


# ------------------------------------------------------------------- fichiers

def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"version": HISTORY_VERSION, "matches": {}}
    try:
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{HISTORY_PATH} est illisible ({exc}). Rien n'a ete ecrase : restaurez une "
            f"sauvegarde depuis {BACKUP_DIR} avant de relancer."
        ) from exc
    if history.get("version") != HISTORY_VERSION:
        raise RuntimeError(f"Version d'historique inconnue : {history.get('version')!r}")
    return history


def backup_history() -> None:
    if not HISTORY_PATH.exists():
        return
    BACKUP_DIR.mkdir(exist_ok=True)
    target = BACKUP_DIR / f"history-{date.today().isoformat()}.json"
    if not target.exists():  # une sauvegarde par jour, prise avant toute ecriture
        shutil.copy2(HISTORY_PATH, target)
    for old in sorted(BACKUP_DIR.glob("history-*.json"))[:-BACKUPS_TO_KEEP]:
        old.unlink()


def save_history(history: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = HISTORY_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(HISTORY_PATH)  # remplacement atomique


def main():
    history = load_history()
    backup_history()

    odds = json.loads(ODDS_PATH.read_text(encoding="utf-8"))
    predictions = json.loads(PREDICTIONS_PATH.read_text(encoding="utf-8"))
    log_rows = []
    if GAME_LOGS_PATH.exists():
        with GAME_LOGS_PATH.open(encoding="utf-8") as f:
            log_rows = list(csv.DictReader(f))

    now = time.time()
    snapshots = update_snapshots(history, odds, predictions, now)
    filled = fill_results(history, index_game_logs(log_rows), now)
    save_history(history)

    statuses = [m["status"] for m in history["matches"].values()]
    print(
        f"{snapshots} instantane(s) enregistre(s), {filled} resultat(s) ajoute(s) - "
        f"historique : {statuses.count('final')} match(s) termine(s), "
        f"{statuses.count('pending')} en attente -> {HISTORY_PATH}"
    )


if __name__ == "__main__":
    main()
