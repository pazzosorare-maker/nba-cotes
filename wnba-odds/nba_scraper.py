"""Recupere les cotes NBA (vainqueur + total du joueur PRA) depuis Winamax.

Les pages Winamax embarquent leur etat dans un objet JSON (PRELOADED_STATE) qui
contient matchs, paris, issues et cotes. Ecrit data/nba_odds.json.
"""
import json
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TOURNAMENT_URL = "https://www.winamax.fr/paris-sportifs/sports/2/15/177"
MATCH_URL_TEMPLATE = "https://www.winamax.fr/paris-sportifs/match/{match_id}"
PRA_BET_PREFIX = "Total du joueur (points + rebonds + passes)"
DELAY_BETWEEN_REQUESTS_SECONDS = 0.4

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

OUTPUT_PATH = Path(__file__).parent / "data" / "nba_odds.json"


def fetch_preloaded_state(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    marker = "var PRELOADED_STATE = "
    start = html.find(marker)
    if start == -1:
        raise RuntimeError(
            "PRELOADED_STATE introuvable : Winamax a peut-etre change la structure de sa page."
        )
    start += len(marker)
    line_end = html.find("\n", start)
    raw = html[start:line_end].rstrip()
    if raw.endswith(";"):
        raw = raw[:-1]
    return json.loads(raw)


def find_nba_tournament_id(state: dict) -> int:
    for tid, tinfo in state.get("tournaments", {}).items():
        if tinfo.get("tournamentName", "").upper() == "NBA":
            return int(tid)
    raise RuntimeError("Tournoi NBA introuvable dans les donnees Winamax.")


def extract_nba_matches(state: dict) -> list:
    nba_id = find_nba_tournament_id(state)
    bets = state.get("bets", {})
    outcomes = state.get("outcomes", {})
    odds = state.get("odds", {})

    results = []
    for match in state.get("matches", {}).values():
        if match.get("tournamentId") != nba_id:
            continue
        if not match.get("competitor1Name") or not match.get("competitor2Name"):
            continue

        bet = bets.get(str(match.get("mainBetId"))) if match.get("mainBetId") else None
        odd1 = odd2 = None
        if bet and bet.get("template") == "2way":
            for outcome_id in bet.get("outcomes", []):
                code = outcomes.get(str(outcome_id), {}).get("code")
                if code == "1":
                    odd1 = odds.get(str(outcome_id))
                elif code == "2":
                    odd2 = odds.get(str(outcome_id))

        results.append(
            {
                "matchId": match.get("matchId"),
                "status": match.get("status"),
                "matchStart": match.get("matchStart"),
                "team1": match.get("competitor1Name"),
                "team2": match.get("competitor2Name"),
                "odd1": odd1,
                "odd2": odd2,
            }
        )

    results.sort(key=lambda m: m["matchStart"] or 0)
    return results


def keep_today_and_tomorrow(matches: list) -> list:
    """Ne garde que les matchs du jour et du lendemain (dates locales de la machine,
    donc l'heure francaise affichee par Winamax). Lance le 30 octobre : matchs du 30 et du 31."""
    today = date.today()
    wanted = {today, today + timedelta(days=1)}
    return [
        m for m in matches
        if m["matchStart"] and date.fromtimestamp(m["matchStart"]) in wanted
    ]


def pra_line(bet: dict):
    """marketTotal n'est pas toujours present (ex: matchs a venir) ; la ligne est
    toujours dans specialBetValue, sous la forme 'player=...|total=37.5'."""
    if bet.get("marketTotal") is not None:
        return bet["marketTotal"]
    for part in (bet.get("specialBetValue") or "").split("|"):
        if part.startswith("total="):
            return float(part[len("total="):])
    return None


def extract_player_pra(state: dict, match_id: int) -> list:
    """Marche 'Total du joueur (points + rebonds + passes)', hors variantes a paliers."""
    bets = state.get("bets", {})
    outcomes = state.get("outcomes", {})
    odds = state.get("odds", {})

    players = {}
    for bet in bets.values():
        if bet.get("matchId") != match_id:
            continue
        title = bet.get("betTitle", "")
        if not title.startswith(PRA_BET_PREFIX) or "paliers" in title:
            continue
        if bet.get("template") != "OverUnder":
            continue

        player_name = title.split(" - ", 1)[-1].strip()
        entry = players.setdefault(
            player_name,
            {"player": player_name, "team": None, "line": pra_line(bet), "overOdd": None, "underOdd": None},
        )

        for outcome_id in bet.get("outcomes", []):
            outcome = outcomes.get(str(outcome_id), {})
            price = odds.get(str(outcome_id))
            if outcome.get("code") == "over":
                entry["overOdd"] = price
                entry["team"] = outcome.get("team")
            elif outcome.get("code") == "under":
                entry["underOdd"] = price

    return sorted(players.values(), key=lambda p: (p["team"] or 0, -(p["line"] or 0)))


def main():
    state = fetch_preloaded_state(TOURNAMENT_URL)
    all_matches = extract_nba_matches(state)
    matches = keep_today_and_tomorrow(all_matches)

    for match in matches:
        time.sleep(DELAY_BETWEEN_REQUESTS_SECONDS)
        try:
            match_state = fetch_preloaded_state(
                MATCH_URL_TEMPLATE.format(match_id=match["matchId"])
            )
            match["playerTotalPRA"] = extract_player_pra(match_state, match["matchId"])
        except Exception as exc:
            match["playerTotalPRA"] = []
            match["playerTotalPRAError"] = str(exc)

    payload = {
        "scrapedAt": datetime.now(timezone.utc).isoformat(),
        "source": TOURNAMENT_URL,
        "matches": matches,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with_pra = sum(1 for m in matches if m["playerTotalPRA"])
    print(
        f"{len(matches)} match(s) NBA aujourd'hui/demain (sur {len(all_matches)} listes), "
        f"dont {with_pra} avec marche PRA -> {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
