"""Prepare data/position_matchups.json pour l'onglet « Estimateur NBA » : pour chaque equipe,
ses 5 derniers matchs, et pour chacun les joueurs ADVERSES (avec leur poste principal) :
leur ligne du match (points, rebonds, passes) et leur niveau habituel.

Niveau habituel d'un joueur face a l'equipe T = sa moyenne sur ses matchs HORS ceux contre T
(sinon le match que l'on cherche a juger contaminerait sa propre reference).

Poste principal = poste ou le joueur passe le plus de temps selon le play-by-play
(PG%..C%, voir matchup_factors.py) ; repli sur le poste liste par basketball-reference.

Aucune requete reseau : lit les fichiers deja telecharges.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import matchup_factors as mf

OUTPUT_PATH = Path(__file__).parent.parent / "wnba-odds" / "data" / "position_matchups.json"
RECENT_GAMES = 5
MIN_MINUTES = mf.POSITION_MIN_MINUTES


def build() -> dict:
    positions = mf.main_positions()
    logs = mf.load_game_logs()

    by_player = {}
    by_game_team = {}
    team_games = {}
    for r in logs:
        by_player.setdefault(r["player"], []).append(r)
        by_game_team.setdefault((r["game_id"], r["team"]), []).append(r)
        team_games.setdefault(r["team"], {})[r["game_id"]] = r["date"]

    def usual(player: str, excluded_opponent: str):
        others = [r for r in by_player[player] if r["opponent"] != excluded_opponent]
        if not others:
            return None
        n = len(others)
        return {
            "n": n,
            "pts": round(sum(r["pts"] for r in others) / n, 1),
            "reb": round(sum(r["trb"] for r in others) / n, 1),
            "ast": round(sum(r["ast"] for r in others) / n, 1),
        }

    teams = {}
    for abbr, games in team_games.items():
        recent = sorted(games.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)[:RECENT_GAMES]
        entries = []
        for game_id, date in recent:
            own_rows = by_game_team[(game_id, abbr)]
            opponent_abbr = own_rows[0]["opponent"]
            opponent_rows = by_game_team.get((game_id, opponent_abbr), [])
            players = []
            for r in sorted(opponent_rows, key=lambda r: -r["mp"]):
                if r["mp"] < MIN_MINUTES:
                    continue
                players.append({
                    "name": r["player"],
                    "position": positions.get(r["player"]),
                    "mp": round(r["mp"], 1),
                    "pts": r["pts"], "reb": r["trb"], "ast": r["ast"],
                    "usual": usual(r["player"], abbr),
                })
            entries.append({
                "date": date,
                "opponent": mf.TEAM_FULL_NAME[opponent_abbr],
                "home": own_rows[0]["home"],  # l'equipe T jouait-elle a domicile ?
                "score": {
                    "team": sum(r["pts"] for r in own_rows),
                    "opponent": sum(r["pts"] for r in opponent_rows),
                },
                "players": players,
            })
        teams[mf.TEAM_FULL_NAME[abbr]] = {"games": entries}
    return {"teams": teams, "positions": positions}


def main():
    built = build()
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "minMinutes": MIN_MINUTES,
        "recentGames": RECENT_GAMES,
        **built,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n_games = sum(len(t["games"]) for t in built["teams"].values())
    print(f"{len(built['teams'])} equipes, {n_games} matchs recents, {len(built['positions'])} joueurs avec poste -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
