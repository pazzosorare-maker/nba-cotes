"""Genere data/nba_predictions.json : pour chaque joueur, ses moyennes de saison, sa repartition
par poste et l'estimation du modele d'implication contre chacune des 29 autres equipes, et sa variante
corrigee par poste (« implication + poste »).

Le modele d'implication (voir involvement_model.py) n'a aucun parametre appris : c'est un
calcul direct a partir des fichiers deja telecharges. Aucune requete reseau.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import involvement_model as im
import matchup_factors as mf

OUTPUT_PATH = Path(__file__).parent.parent / "wnba-odds" / "data" / "nba_predictions.json"

# Seuil de « value » : ecart |estimation - ligne| d'au moins VALUE_Z ecarts-types du joueur (voir praSpread).
# Seul endroit a changer : la page des cotes et le suivi des paris le lisent dans nba_predictions.json.
VALUE_Z = 0.5

PRIOR_GAMES = 5     # poids de l'a priori dans l'ecart-type du joueur (en nombre de matchs)
MIN_GAMES_FOR_FIT = 4


def pra_spread(players: dict):
    """Ecart-type match a match du PRA de chaque joueur, pour juger si un ecart modele - ligne est grand
    au regard de la variabilite naturelle du joueur (c'est elle qui rend une ligne « battable » ou non).

    Avec 5 ou 6 matchs, l'ecart-type observe est tres bruite : il est melange a un a priori
    (variance attendue d'un joueur de ce niveau, droite ajustee sur toute la ligue : l'ecart-type
    croit avec le PRA moyen) pese comme PRIOR_GAMES matchs.
    """
    pra_by_player = {}
    for r in mf.load_game_logs():
        if r["mp"] > 0:
            pra_by_player.setdefault(r["player"], []).append(r["pts"] + r["trb"] + r["ast"])

    def sample_variance(values):
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / (len(values) - 1)

    # Droite ecart-type = a + b x PRA moyen, par moindres carres sur les joueurs ayant assez de matchs.
    fit = [(sum(v) / len(v), sample_variance(v) ** 0.5) for v in pra_by_player.values() if len(v) >= MIN_GAMES_FOR_FIT]
    mean_x = sum(x for x, _ in fit) / len(fit)
    mean_y = sum(y for _, y in fit) / len(fit)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in fit) / sum((x - mean_x) ** 2 for x, _ in fit)
    intercept = mean_y - slope * mean_x

    spread = {}
    for name, player in players.items():
        baseline = player["baseline"]
        mean = baseline["pts"] + baseline["reb"] + baseline["ast"]
        values = pra_by_player.get(name, [])
        dof = len(values) - 1 if len(values) >= 2 else 0
        observed = sample_variance(values) if dof else 0.0
        prior = max(intercept + slope * mean, 1.0) ** 2
        spread[name] = {
            "sd": round(((dof * observed + PRIOR_GAMES * prior) / (dof + PRIOR_GAMES)) ** 0.5, 2),
            "games": len(values),
        }
    return spread, {"intercept": round(intercept, 3), "slope": round(slope, 4)}


def main():
    players = mf.build_player_profiles()
    involvement, involvement_factors = im.build_involvement()
    spread, spread_prior = pra_spread(players)

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "teams": {full_name: abbr for abbr, full_name in mf.TEAM_FULL_NAME.items()},
        "involvementFactors": involvement_factors,
        "praSpreadPrior": spread_prior,
        "valueZ": VALUE_Z,
        "positionAdjustments": im.build_position_adjustments(),
        "players": {
            name: {
                "team": player["team"],
                "baseline": player["baseline"],
                "positionWeights": player["positionWeights"],
                "praSpread": spread[name],
                "involvement": involvement.get(name),
            }
            for name, player in players.items()
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    without = sum(1 for p in payload["players"].values() if not p["involvement"])
    print(f"{len(players)} joueurs ({without} sans estimation d'implication) -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
