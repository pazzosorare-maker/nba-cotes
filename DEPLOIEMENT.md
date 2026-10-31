# Mettre l'appli en ligne (Vercel + GitHub)

Principe : **GitHub** garde le code et les donnees et relance vos scripts Python (cotes, stats, estimations,
suivi), **Vercel** affiche les pages. Le bouton « Actualiser » du site demande a GitHub de relancer les scripts.

```
Visiteur ──► Vercel (pages + /api/refresh) ──► GitHub Actions (scripts Python) ──► commit des donnees ──► Vercel redeploie
```

Ce dossier (`NBA`) est la racine du depot : `wnba-odds/` (pages), `nba-player-stats/` (calculs),
`api/refresh.js` (bouton), `.github/workflows/refresh.yml` (actualisation), `vercel.json`, `requirements.txt`.

## 1. GitHub

1. Creez un compte sur github.com, puis un depot **public** (ex. `nba-cotes`). Public : les actualisations
   planifiees sont gratuites sans limite ; en prive, comptez 2 000 min/mois gratuites, ce qui ne suffit pas au
   rythme actuel (voir « Reglages »).
2. Envoyez-y le contenu de ce dossier `NBA` (hors `.claude`, deja ignore). Il y a plus de 250 photos : utilisez
   **GitHub Desktop** (desktop.github.com) → *Add local repository* → *Publish repository*, ou installez Git.
   `wnba-odds/data/history.json` et `bets.json` partent avec : ils contiennent votre suivi actuel.
3. Jeton pour le bouton : GitHub → *Settings* → *Developer settings* → *Fine-grained tokens* → *Generate*.
   - *Repository access* : **Only select repositories** → votre depot.
   - *Permissions* → **Actions : Read and write** (le reste en lecture seule par defaut).
   - Copiez le jeton (il ne s'affiche qu'une fois).

## 2. Vercel

1. Creez un compte sur vercel.com (connexion avec GitHub), puis *Add New… → Project* → importez le depot.
2. *Framework Preset* : **Other**. Laissez le reste (tout est dans `vercel.json`).
3. *Environment Variables* :
   | Nom | Valeur |
   |---|---|
   | `GITHUB_REPO` | `votre-pseudo/nba-cotes` |
   | `GITHUB_TOKEN` | le jeton de l'etape 1.3 |
4. *Deploy*. Vercel donne l'adresse publique (ex. `https://nba-cotes.vercel.app`).

## 3. Premier test

Sur GitHub : onglet *Actions* → *Actualisation des donnees* → *Run workflow* → mode **full**. Comptez 5 a 10 min.
- Etape « Cotes Winamax » ou « Statistiques des joueurs » en rouge = le site source refuse les serveurs de
  GitHub. Le site continue de marcher avec les dernieres donnees ; dites-le-moi et on cherchera une parade.
- Tout vert : les donnees sont commitees, Vercel redeploie seul, et le bouton « Actualiser » du site fonctionne.

## Comment ca fonctionne ensuite

- **Planifie** : cotes + estimations + suivi toutes les heures ; en plus, statistiques des joueurs 4 fois par jour.
- **Bouton « Actualiser »** : lance une actualisation, affiche l'avancement, puis recharge la page (les
  selections de joueur et d'equipe sont conservees). Protections : une seule actualisation a la fois, 15 min
  minimum entre deux (planifiees comprises), statistiques des joueurs au plus une fois par heure. Le jeton
  reste cote serveur, jamais dans le navigateur.
- **Suivi des modeles et des paris** : il continue en ligne, mais **la source de verite devient GitHub**.
  Ne lancez plus `start.bat` en meme temps : vos fichiers locaux divergeraient de ceux du site. Pour
  retrouver les donnees en local, recuperez-les (*Pull* dans GitHub Desktop). L'historique git sert de
  sauvegarde de `history.json` et `bets.json`.

## Reglages

- Delais : variables Vercel `REFRESH_COOLDOWN_MIN` (15) et `FULL_REFRESH_MIN` (60).
- Rythme planifie : lignes `cron` de `.github/workflows/refresh.yml` (heure UTC). En depot prive, passez
  l'actualisation rapide a toutes les 3 h pour rester dans les 2 000 min gratuites.
- Chaque actualisation avec nouvelles donnees = un deploiement Vercel (offre gratuite : 100 par jour).

## A savoir avant de rendre le site public

- Les cotes viennent de Winamax, les stats de basketball-reference.com, les photos de FantasyPros et les logos
  d'ESPN. Les republier publiquement n'est pas couvert par les conditions de ces sites (usage personnel). C'est
  votre responsabilite ; en cas de doute, gardez le depot et le site prives (Vercel et GitHub le permettent) ou
  retirez photos et logos.
- Les pages affichent une mention « informatif, pas un conseil de pari, jouer comporte des risques ».
- L'offre gratuite de Vercel est reservee a un usage non commercial.
