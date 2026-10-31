"""Suivi des paris « value » : conserve chaque pari signale par au moins un des deux modeles, puis y
rattache le resultat reel pour savoir, avec le temps, si ces paris sont gagnants et quel modele
(ou quelle double validation) fait le mieux.

Un modele signale une « value » sur un joueur ayant une ligne PRA Winamax quand son estimation s'ecarte
de la ligne d'au moins VALUE_Z ecarts-types du joueur : au-dessus = Plus de, en dessous = Moins de. Le
seuil vient de nba_predictions.json (cle valueZ, definie dans build_estimates.py). Les deux modeles sont
le modele d'implication (« implication ») et sa variante par poste (« implicationPoste »).

Un pari enregistre contient donc, pour chaque modele, son cote (picks) :
- les deux modeles du meme cote : double validation ;
- un seul modele : pari « seul » ;
- les deux de cotes opposes : desaccord (chaque modele garde son cote).

A chaque lancement :
1. Detection : pour chaque match pas encore commence, les joueurs signales par au moins un modele
   et non encore enregistres sont ajoutes, avec la ligne, les cotes et les estimations du moment. Un
   pari enregistre n'est JAMAIS modifie ni retire (comme un pari reel : la ligne qui bouge ensuite ne
   change pas le pari, et un modele qui se range plus tard du meme avis ne le rend pas « double ») ; il
   n'y a qu'un enregistrement par joueur et par match, le premier detecte.
2. Resultats : pour les matchs termines (box-score disponible), le PRA reel est compare a la ligne,
   modele par modele. Gagne = reel du bon cote ; perdu sinon ; annule (mise rendue) si le joueur n'a
   pas joue ou si le reel est egal a la ligne. Gain pour une mise de 1 : cote - 1 si gagne, -1 si
   perdu, 0 si annule.

data/bets.json est irremplacable (les cotes passees ne se retrouvent pas) : ecriture atomique,
sauvegarde quotidienne dans data/backups/, arret sans rien ecraser si le fichier est illisible.
"""
import csv
import json
import shutil
import time
from datetime import date, datetime, timezone
from pathlib import Path

import track_history as th

BETS_PATH = th.APP_DATA_DIR / "bets.json"
BETS_VERSION = 1
DEFAULT_VALUE_Z = 0.5
MODELS = ("implication", "implicationPoste")


def pra(estimate: dict) -> int | float:
    return estimate["pts"] + estimate["reb"] + estimate["ast"]


def value_side(estimate: float, line: float, sd: float, threshold: float):
    """(z, cote) : z = ecart modele - ligne en ecarts-types du joueur ; cote = 'over'/'under' si |z| >= seuil."""
    z = (estimate - line) / sd
    if abs(z) < threshold:
        return z, None
    return z, "over" if z > 0 else "under"


def pick_odd(bet: dict, side: str):
    return bet["overOdd"] if side == "over" else bet["underOdd"]


# ------------------------------------------------------------------ detection

def detect_bets(bets: dict, odds: dict, predictions: dict, now: float) -> int:
    threshold = predictions.get("valueZ", DEFAULT_VALUE_Z)
    players = predictions["players"]
    key_by_norm = {th.norm_name(name): name for name in players}
    detected_at = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

    added = 0
    for match in odds["matches"]:
        if not match.get("matchStart") or match["matchStart"] <= now:
            continue  # commence ou en cours : on n'enregistre pas de pari apres le coup d'envoi
        for line in match.get("playerTotalPRA") or []:
            team, opponent = (match["team1"], match["team2"]) if line["team"] == 1 else (match["team2"], match["team1"])
            key = key_by_norm.get(th.norm_name(line["player"]))
            player = players.get(key) if key else None
            involvement = player.get("involvement") if player else None
            if not involvement or involvement["team"] != team or not player.get("praSpread"):
                continue  # joueur inconnu, ou equipe differente chez Winamax (echange recent)
            estimates = {
                "implication": involvement["predictions"].get(opponent),
                "implicationPoste": (involvement.get("positionAdjusted") or {}).get(opponent),
            }
            if not all(estimates.values()) or line["line"] is None:
                continue

            bet_id = f"{match['matchId']}|{th.norm_name(key)}"
            if bet_id in bets:
                continue  # deja enregistre : fige

            sd = player["praSpread"]["sd"]
            picks, z = {}, {}
            for model in MODELS:
                z[model], side = value_side(pra(estimates[model]), line["line"], sd, threshold)
                odd = line["overOdd"] if side == "over" else line["underOdd"]
                picks[model] = side if side and odd else None  # pas de cote = pas de pari possible
            if not any(picks.values()):
                continue

            bets[bet_id] = {
                "id": bet_id,
                "matchId": match["matchId"],
                "team1": match["team1"],
                "team2": match["team2"],
                "matchStart": match["matchStart"],
                "detectedAt": detected_at,
                "player": key,
                "winamaxName": line["player"],
                "team": team,
                "opponent": opponent,
                "line": line["line"],
                "overOdd": line["overOdd"],
                "underOdd": line["underOdd"],
                "estimates": estimates,
                "praSd": sd,
                "z": {m: round(v, 3) for m, v in z.items()},
                "valueZ": threshold,
                "picks": picks,
                "status": "pending",
                "actual": None,
                "results": None,
            }
            added += 1
    return added


# ------------------------------------------------------------------ resultats

def settle(bet: dict, row: dict | None) -> None:
    """Rattache le resultat a un pari (row = ligne du box-score du joueur, None si DNP)."""
    results = {}
    if row is None:
        bet["actual"] = {"dnp": True}
        for model, side in bet["picks"].items():
            if side:
                results[model] = {"status": "void", "profit": 0.0}
    else:
        actual = {
            "pts": int(row["pts"]), "reb": int(row["trb"]), "ast": int(row["ast"]),
            "mp": round(float(row["mp"]), 1),
        }
        actual["pra"] = actual["pts"] + actual["reb"] + actual["ast"]
        bet["actual"] = actual
        for model, side in bet["picks"].items():
            if not side:
                continue
            if actual["pra"] == bet["line"]:
                results[model] = {"status": "void", "profit": 0.0}
            elif (actual["pra"] > bet["line"]) == (side == "over"):
                results[model] = {"status": "won", "profit": round(pick_odd(bet, side) - 1, 4)}
            else:
                results[model] = {"status": "lost", "profit": -1.0}
    bet["results"] = results
    bet["status"] = "final"


def fill_results(bets: dict, logs_index: dict, now: float) -> int:
    filled = 0
    for bet in bets.values():
        if bet["status"] != "pending" or bet["matchStart"] + th.RESULT_DELAY_SECONDS > now:
            continue
        game = th.find_game(bet, logs_index)
        if game is None:
            continue  # box-score pas encore disponible
        _, rows_a, rows_b = game
        rows = rows_a if bet["team"] == bet["team1"] else rows_b
        row = next((r for r in rows if th.norm_name(r["player"]) == th.norm_name(bet["player"])), None)
        settle(bet, row)
        filled += 1
    return filled


# ------------------------------------------------------------------- fichiers

def upgrade_bet(bet: dict) -> dict:
    """Premiere version du fichier : un pari = un cote, valide par les DEUX modeles (double validation)."""
    if "picks" in bet:
        return bet
    side, odd, status = bet.pop("side"), bet.pop("odd"), bet.pop("status")
    profit = bet.pop("profit")
    bet["estimates"] = {"implication": bet.pop("implication"), "implicationPoste": bet.pop("implicationPoste")}
    bet["picks"] = {model: side for model in MODELS}
    if status == "pending":
        bet["status"], bet["results"] = "pending", None
    else:
        bet["status"] = "final"
        bet["results"] = {model: {"status": status, "profit": profit} for model in MODELS}
    return bet


def load_bets(path: Path = BETS_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{path} est illisible ({exc}). Rien n'a ete ecrase : restaurez une "
            f"sauvegarde depuis {th.BACKUP_DIR} avant de relancer."
        ) from exc
    if data.get("version") != BETS_VERSION:
        raise RuntimeError(f"Version du fichier de paris inconnue : {data.get('version')!r}")
    return {bet_id: upgrade_bet(bet) for bet_id, bet in data["bets"].items()}


def backup_bets(path: Path = BETS_PATH) -> None:
    if not path.exists():
        return
    th.BACKUP_DIR.mkdir(exist_ok=True)
    target = th.BACKUP_DIR / f"bets-{date.today().isoformat()}.json"
    if not target.exists():  # une sauvegarde par jour, prise avant toute ecriture
        shutil.copy2(path, target)
    for old in sorted(th.BACKUP_DIR.glob("bets-*.json"))[:-th.BACKUPS_TO_KEEP]:
        old.unlink()


def save_bets(bets: dict, path: Path = BETS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    payload = {"version": BETS_VERSION, "bets": bets}
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)  # remplacement atomique


def group_of(bet: dict) -> str:
    a, b = (bet["picks"][m] for m in MODELS)
    if a and b:
        return "double" if a == b else "desaccord"
    return "implication seule" if a else "poste seul"


def main():
    bets = load_bets()
    backup_bets()

    odds = json.loads(th.ODDS_PATH.read_text(encoding="utf-8"))
    predictions = json.loads(th.PREDICTIONS_PATH.read_text(encoding="utf-8"))
    log_rows = []
    if th.GAME_LOGS_PATH.exists():
        with th.GAME_LOGS_PATH.open(encoding="utf-8") as f:
            log_rows = list(csv.DictReader(f))

    now = time.time()
    added = detect_bets(bets, odds, predictions, now)
    filled = fill_results(bets, th.index_game_logs(log_rows), now)
    save_bets(bets)

    groups = [group_of(b) for b in bets.values()]
    pending = sum(1 for b in bets.values() if b["status"] == "pending")
    print(
        f"{added} nouveau(x) pari(s) value, {filled} resultat(s) ajoute(s) - {len(bets)} pari(s) "
        f"({pending} en attente) : {groups.count('double')} double(s), {groups.count('implication seule')} "
        f"implication seule, {groups.count('poste seul')} poste seul, {groups.count('desaccord')} desaccord(s) "
        f"-> {BETS_PATH}"
    )


if __name__ == "__main__":
    main()
