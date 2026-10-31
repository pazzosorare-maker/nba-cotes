@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Cotes NBA (Winamax) et estimateur PTS/REB/AST
echo ============================================
echo.
echo Verification des logos des clubs...
python download_logos.py
if errorlevel 1 (
    echo.
    echo Attention : le telechargement des logos a echoue, l'appli s'affichera sans logos.
)

echo.
echo Verification des photos des joueurs (la premiere fois : ~3 minutes)...
python download_player_photos.py
if errorlevel 1 (
    echo.
    echo Attention : le telechargement des photos a echoue, l'appli affichera les initiales des joueurs.
)

echo.
echo Recuperation des cotes NBA du jour et du lendemain (Winamax)...
python nba_scraper.py
if errorlevel 1 (
    echo.
    echo Attention : le scraping des cotes NBA a echoue, on continue quand meme.
)

echo.
echo Recuperation des stats NBA de la saison (basketball-reference.com)...
python "..\nba-player-stats\download_nba_stats.py"
if errorlevel 1 (
    echo.
    echo Attention : le telechargement des stats NBA a echoue, on continue quand meme.
)

echo.
echo Recuperation Defense vs Position FanDuel (fantasypros.com)...
python "..\nba-player-stats\download_dvp.py"
if errorlevel 1 (
    echo.
    echo Attention : le telechargement Defense vs Position a echoue, on continue quand meme.
)

echo.
echo Recuperation des matchs joues cette saison (seuls les nouveaux matchs sont telecharges, ~3 s chacun)...
python "..\nba-player-stats\download_game_logs.py"
if errorlevel 1 (
    echo.
    echo Attention : le telechargement des matchs a echoue, on continue quand meme.
)

echo.
echo Calcul des estimations (modele d'implication)...
python "..\nba-player-stats\build_estimates.py"
if errorlevel 1 (
    echo.
    echo Attention : le calcul des estimations a echoue, on continue quand meme.
)

echo.
echo Preparation des statistiques par joueur...
python "..\nba-player-stats\build_player_stats.py"
if errorlevel 1 (
    echo.
    echo Attention : la preparation des stats joueur a echoue, on continue quand meme.
)

echo.
echo Preparation des performances par poste face a chaque equipe...
python "..\nba-player-stats\build_position_matchups.py"
if errorlevel 1 (
    echo.
    echo Attention : la preparation des performances par poste a echoue, on continue quand meme.
)

echo.
echo Suivi des modeles : enregistrement des cotes/estimations et des resultats...
python "..\nba-player-stats\track_history.py"
if errorlevel 1 (
    echo.
    echo Attention : le suivi des modeles a echoue, on continue quand meme.
)

echo.
echo Suivi des paris value : enregistrement des nouveaux paris et des resultats...
python "..\nba-player-stats\track_bets.py"
if errorlevel 1 (
    echo.
    echo Attention : le suivi des paris a echoue, on continue quand meme.
)

echo.
echo Lancement du serveur local sur le port 8765...
start "Serveur NBA - fermer cette fenetre pour arreter" cmd /k python -m http.server 8765

timeout /t 2 /nobreak >nul

echo Ouverture de l'application dans le navigateur...
start "" http://localhost:8765/index.html

endlocal
