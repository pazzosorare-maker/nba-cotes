"""Seconde estimation PTS/REB/AST : le taux d'implication du joueur.

Principe, pour un joueur P de l'equipe A qui affronte l'equipe B :

1. Taux d'implication : part de P dans la production de son equipe A, stat par stat
   (points de P / points de A, rebonds de P / rebonds de A, passes de P / passes de A).
   Calcule par match joue (moyenne par match du joueur / moyenne par match de l'equipe),
   pour ne pas penaliser un joueur absent d'une partie des matchs.
2. Ce que B concede par match (points, rebonds, passes), multiplie par ce taux.
3. Ajustement du rythme (pace) pour les points et les passes : B concede ses stats
   dans des matchs a SON rythme ; le rythme attendu d'un A-B est pace(A) x pace(B) / pace(ligue).
4. Pour les rebonds, on corrige plutot par les tirs ratés (= occasions de rebond) :
   tirs ratés attendus dans le match A-B / tirs ratés d'un match type de B. Ce facteur
   integre deja le rythme (plus de possessions = plus de tirs), d'ou l'absence de
   double comptage avec le pace.

Variante « implication + poste » (suivie en parallele dans l'onglet Suivi) : l'estimation de base
est corrigee par ce que l'adversaire concede AU POSTE du joueur, au-dela de son effet global.
Voir build_position_adjustments().

Aucune requete reseau : lit les fichiers deja telecharges (voir matchup_factors.py).
"""
import matchup_factors as mf

STATS = ("pts", "reb", "ast")
PLAYER_COLUMN = {"pts": "pts_per_g", "reb": "trb_per_g", "ast": "ast_per_g"}
TEAM_COLUMN = {"pts": "pts", "reb": "trb", "ast": "ast"}  # production propre de l'equipe
CONCEDED_COLUMN = {"pts": "opp_pts", "reb": "opp_trb", "ast": "opp_ast"}  # concede par l'equipe

# Lissage de l'ajustement par poste : il pese n / (n + K) avec n = matchs de l'equipe adverse.
# K = 10 : un tiers du poids avec 5 matchs, deux tiers avec 20, 90 % avec toute une saison.
POSITION_SHRINKAGE_GAMES = 10


def _by_team(filename: str) -> dict:
    return {row["team"].rstrip("*"): row for row in mf.load_csv_rows(filename)}


def build_team_info() -> tuple[dict, float]:
    own = _by_team(mf.season_file("team_stats"))
    advanced = _by_team(mf.season_file("team_advanced"))
    conceded = _by_team(mf.season_file("team_opponent_stats"))

    info = {}
    for team in mf.TEAM_FULL_NAME.values():
        o, c = own[team], conceded[team]
        info[team] = {
            "own": {s: mf.safe_float(o[TEAM_COLUMN[s]]) for s in STATS},
            "conceded": {s: mf.safe_float(c[CONCEDED_COLUMN[s]]) for s in STATS},
            "pace": mf.safe_float(advanced[team]["pace"]),
            # Tirs ratés par match : les siens, et ceux de ses adversaires face a lui.
            "own_misses": mf.safe_float(o["fga"]) - mf.safe_float(o["fg"]),
            "opp_misses": mf.safe_float(c["opp_fga"]) - mf.safe_float(c["opp_fg"]),
        }
    league_pace = sum(t["pace"] for t in info.values()) / len(info)
    return info, league_pace


def matchup_factors(info: dict, league_pace: float) -> dict:
    """factors[A][B] = ajustements a appliquer a ce que B concede, pour un joueur de A."""
    factors = {}
    for a, ia in info.items():
        factors[a] = {}
        for b, ib in info.items():
            if a == b:
                continue
            expected_pace = ia["pace"] * ib["pace"] / league_pace
            pace_factor = expected_pace / ib["pace"]

            # Tirs ratés attendus : A contre la defense de B, et B contre la defense de A.
            expected_misses = (ia["own_misses"] + ib["opp_misses"]) / 2 + (
                ib["own_misses"] + ia["opp_misses"]
            ) / 2
            typical_misses_in_b_games = ib["own_misses"] + ib["opp_misses"]
            miss_factor = expected_misses / typical_misses_in_b_games

            factors[a][b] = {"pace": round(pace_factor, 4), "miss": round(miss_factor, 4)}
    return factors


def build_position_adjustments() -> dict:
    """Ce que chaque equipe concede a chaque poste, au-dela de son effet global, mesure sur nos box-scores.

    Pour l'equipe B qui defend et le poste P (poste principal des joueurs adverses de 10 min ou plus) :
        concede(B, P)  = total de la stat des joueurs du poste P contre B, en moyenne par match
        ecart_poste    = [concede(B, P) / moyenne ligue de ce poste]
                         / [concede(B, tous postes) / moyenne ligue tous postes]
    Diviser par l'effet global evite de compter deux fois ce que le modele de base integre deja.
    L'ecart est ensuite rapproche de 1 selon le nombre de matchs de B (tres peu de matchs = peu de
    confiance), puis le facteur du joueur est la moyenne de ces ecarts ponderee par son temps de
    jeu a chaque poste (PG%..C%).
    """
    positions = mf.main_positions()
    per_game = {}   # abbr du defenseur -> match -> poste -> {stat: total}
    for r in mf.load_game_logs():
        pos = positions.get(r["player"])
        if pos is None or r["mp"] < mf.POSITION_MIN_MINUTES:
            continue
        game = per_game.setdefault(r["opponent"], {}).setdefault(
            r["game_id"], {p: {s: 0 for s in STATS} for p in mf.POSITIONS}
        )
        game[pos]["pts"] += r["pts"]
        game[pos]["reb"] += r["trb"]
        game[pos]["ast"] += r["ast"]

    n_games = {abbr: len(games) for abbr, games in per_game.items()}
    mean_by_position = {   # abbr -> poste -> stat -> moyenne par match
        abbr: {p: {s: sum(g[p][s] for g in games.values()) / len(games) for s in STATS} for p in mf.POSITIONS}
        for abbr, games in per_game.items()
    }
    mean_all = {abbr: {s: sum(by_pos[p][s] for p in mf.POSITIONS) for s in STATS} for abbr, by_pos in mean_by_position.items()}

    teams = list(mean_by_position)
    league_position = {p: {s: sum(mean_by_position[t][p][s] for t in teams) / len(teams) for s in STATS} for p in mf.POSITIONS}
    league_all = {s: sum(mean_all[t][s] for t in teams) / len(teams) for s in STATS}

    adjustments = {}
    for abbr, full_name in mf.TEAM_FULL_NAME.items():
        n = n_games.get(abbr, 0)
        weight = n / (n + POSITION_SHRINKAGE_GAMES)
        by_stat = {}
        for s in STATS:
            by_stat[s] = {}
            for p in mf.POSITIONS:
                if n and league_position[p][s] and mean_all[abbr][s] and league_all[s]:
                    raw = (mean_by_position[abbr][p][s] / league_position[p][s]) / (mean_all[abbr][s] / league_all[s])
                else:
                    raw = 1.0
                by_stat[s][p] = round(1 + (raw - 1) * weight, 4)
        adjustments[full_name] = {"games": n, "adjustments": by_stat}
    return adjustments


def current_team_rows() -> dict:
    """Une ligne par joueur : celle de son equipe actuelle (les lignes agregees 2TM/3TM
    sont ignorees ; basketball-reference liste les passages par equipe dans l'ordre)."""
    rows = {}
    for row in mf.load_csv_rows(mf.season_file("per_game")):
        if row["team_name_abbr"] in mf.TEAM_FULL_NAME:
            rows[row["name_display"]] = row
    return rows


def build_involvement() -> tuple[dict, dict]:
    """Renvoie (donnees par joueur, facteurs de matchup entre equipes)."""
    info, league_pace = build_team_info()
    factors = matchup_factors(info, league_pace)
    position_weights = {name: p["positionWeights"] for name, p in mf.build_player_profiles().items()}
    position_adjustments = build_position_adjustments()

    players = {}
    for name, row in current_team_rows().items():
        team_a = mf.TEAM_FULL_NAME[row["team_name_abbr"]]
        shares = {}
        for stat in STATS:
            team_total = info[team_a]["own"][stat]
            shares[stat] = mf.safe_float(row[PLAYER_COLUMN[stat]]) / team_total if team_total else 0.0

        weights = position_weights.get(name)
        predictions = {}
        position_adjusted = {}
        for team_b, f in factors[team_a].items():
            conceded = info[team_b]["conceded"]
            base = {
                "pts": shares["pts"] * conceded["pts"] * f["pace"],
                "reb": shares["reb"] * conceded["reb"] * f["miss"],
                "ast": shares["ast"] * conceded["ast"] * f["pace"],
            }
            predictions[team_b] = {s: round(v, 1) for s, v in base.items()}
            if weights:
                adjust = position_adjustments[team_b]["adjustments"]
                position_adjusted[team_b] = {
                    s: round(base[s] * sum(weights[p] * adjust[s][p] for p in mf.POSITIONS), 1) for s in STATS
                }

        players[name] = {
            "team": team_a,
            "games": int(mf.safe_float(row["games"])),
            "shares": {s: round(v, 4) for s, v in shares.items()},
            "predictions": predictions,
            "positionAdjusted": position_adjusted or None,
        }

    return players, factors
