"""Prepare data/player_stats.json pour l'onglet « Stat du joueur » : pour chaque joueur,
ses moyennes de saison, son implication dans son equipe (saison et 5 derniers matchs)
et le detail de ses 5 derniers matchs.

Sources locales (aucune requete reseau) : nba_<saison>_per_game.csv, game_logs_<saison>.csv
et le calcul d'implication du modele (involvement_model.py).

Implication = part du joueur dans la production de son equipe :
- saison : exactement celle du modele d'implication (moyenne par match du joueur / moyenne
  par match de l'equipe), donc coherente avec l'onglet Estimateur ;
- 5 derniers matchs : somme du joueur / somme de l'equipe, sur ces memes matchs.
"""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import involvement_model as im
import matchup_factors as mf

OUTPUT_PATH = Path(__file__).parent.parent / "wnba-odds" / "data" / "player_stats.json"
RECENT_GAMES = 5


def optional_float(value, digits=3):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def team_game_totals(rows: list[dict]) -> dict:
    totals = {}
    for r in rows:
        t = totals.setdefault((r["game_id"], r["team"]), {"pts": 0, "reb": 0, "ast": 0})
        t["pts"] += r["pts"]
        t["reb"] += r["trb"]
        t["ast"] += r["ast"]
    return totals


def game_line(r: dict) -> dict:
    return {
        "date": r["date"],
        "opponent": mf.TEAM_FULL_NAME[r["opponent"]],
        "home": r["home"],
        "mp": round(r["mp"], 1),
        "pts": r["pts"], "reb": r["trb"], "ast": r["ast"],
        "stl": r["stl"], "blk": r["blk"], "tov": r["tov"], "pf": r["pf"],
        "fg": r["fg"], "fga": r["fga"], "fg3": r["fg3"], "fg3a": r["fg3a"], "ft": r["ft"], "fta": r["fta"],
        "plusMinus": r["plus_minus"],
    }


def build() -> dict:
    # Moyennes de saison : ligne agregee pour un joueur echange (saison complete), equipe = equipe actuelle.
    season_rows = mf.dedupe_by_player(mf.load_csv_rows(mf.season_file("per_game")))
    current_team_rows = im.current_team_rows()
    involvement, _ = im.build_involvement()

    logs = mf.load_game_logs()
    team_totals = team_game_totals(logs)
    logs_by_player = {}
    for r in logs:
        logs_by_player.setdefault(r["player"], []).append(r)

    players = {}
    for name, row in season_rows.items():
        if name == "League Average":
            continue
        current = current_team_rows.get(name)
        team_abbr = current["team_name_abbr"] if current else None

        games = sorted(logs_by_player.get(name, []), key=lambda r: (r["date"], r["game_id"]), reverse=True)
        last = games[:RECENT_GAMES]

        last_avg = None
        last_share = None
        if last:
            n = len(last)
            last_avg = {k: round(sum(r[c] for r in last) / n, 1) for k, c in (("pts", "pts"), ("reb", "trb"), ("ast", "ast"), ("stl", "stl"), ("blk", "blk"), ("tov", "tov"))}
            last_avg["mp"] = round(sum(r["mp"] for r in last) / n, 1)
            team_sum = {"pts": 0, "reb": 0, "ast": 0}
            for r in last:
                for k in team_sum:
                    team_sum[k] += team_totals[(r["game_id"], r["team"])][k]
            last_share = {
                k: round(sum(r[c] for r in last) / team_sum[k], 4) if team_sum[k] else None
                for k, c in (("pts", "pts"), ("reb", "trb"), ("ast", "ast"))
            }

        players[name] = {
            "team": mf.TEAM_FULL_NAME.get(team_abbr),
            "teamAbbr": team_abbr,
            "pos": row.get("pos"),
            "season": {
                "games": int(mf.safe_float(row["games"])),
                "gamesStarted": int(mf.safe_float(row["games_started"])),
                "mp": optional_float(row["mp_per_g"], 1),
                "pts": optional_float(row["pts_per_g"], 1),
                "reb": optional_float(row["trb_per_g"], 1),
                "ast": optional_float(row["ast_per_g"], 1),
                "stl": optional_float(row["stl_per_g"], 1),
                "blk": optional_float(row["blk_per_g"], 1),
                "tov": optional_float(row["tov_per_g"], 1),
                "pf": optional_float(row["pf_per_g"], 1),
                "fgPct": optional_float(row["fg_pct"]),
                "fg3Pct": optional_float(row["fg3_pct"]),
                "ftPct": optional_float(row["ft_pct"]),
                "efgPct": optional_float(row["efg_pct"]),
            },
            "shares": {
                "season": involvement[name]["shares"] if name in involvement else None,
                "last5": last_share,
            },
            "last5": [game_line(r) for r in last],
            "last5Avg": last_avg,
        }
    return players


def main():
    players = build()
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "season": f"{mf.SEASON_END_YEAR - 1}-{str(mf.SEASON_END_YEAR)[2:]}",
        "players": players,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    with_games = sum(1 for p in players.values() if p["last5"])
    print(f"{len(players)} joueurs ({with_games} avec des matchs recents) -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
