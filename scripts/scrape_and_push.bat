@echo off
REM ============================================================================
REM  scrape_and_push.bat - Aggiornamento COMPLETO prezzi Pokemon DAL PC.
REM
REM  Perche' dal PC: CardRush blocca gli IP datacenter di GitHub Actions (403,
REM  anche la forma per-carta), quindi lo scraping in cloud non e' affidabile.
REM  Dal tuo PC (IP residenziale) funziona. Questo script fa TUTTO:
REM    CardRush (catalogo + prezzi) + Hareruya (prezzi) -> rigenera i JSON della
REM    dashboard -> commit + push (Cloudflare Pages ridistribuisce da solo).
REM
REM  PORTABILE: usa percorsi relativi al repo (%~dp0..), nessun percorso utente
REM  cablato. Gira su QUALSIASI PC che abbia: repo clonato + Python (launcher 'py')
REM  + git con permesso di push. Setup passo-passo: docs/RUNNER_SETUP.md.
REM
REM  REGOLA D'ORO: UN SOLO PC runner alla volta. Il DB (tcg_tracker.db) e' un file
REM  BINARIO committato nel repo: due macchine che lo scrivono = conflitti di push.
REM  Cambi PC? Configura la' e RIMUOVI la pianificazione qui.
REM
REM  Uso: doppio clic, oppure pianifica con "Utilita' di pianificazione" (di notte).
REM ============================================================================
setlocal
cd /d "%~dp0.."

REM Console UTF-8: evita UnicodeEncodeError quando Python stampa nomi/codici giapponesi
REM (la cmd di Windows usa cp1252). Rinforza la riconfigurazione stdout gia' in run.py.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Hareruya: quante carte per run (scelte per STALENESS, le piu' vecchie prima).
REM 11000 >= catalogo -> refresh COMPLETO ogni run (puo' durare alcune ore: schedula
REM di notte). Vuoi run piu' corti? Abbassa (es. 3000): su piu' run si copre tutto a
REM rotazione. CardRush invece si aggiorna SEMPRE tutto (l'harvest e' veloce, ~120 pagine).
set HR_BATCH=11000

echo === [1/4] CardRush: harvest catalogo + prezzi (lista SPA, IP residenziale) ===
py src\run.py --harvest-pokemon --sleep 0.5

echo === [2/4] Hareruya: prezzi per-carta/set (batch %HR_BATCH%) ===
py src\run.py --game pokemon --only hareruya --batch %HR_BATCH% --sleep 1.0 --jitter 0.6 --set-gap 2

echo === [3/4] Rigenero i JSON della dashboard dal DB ===
py -c "import sys; sys.path.insert(0,'src'); import database as db; db.export_web(db.get_conn(),'dashboard/data')"
if errorlevel 1 (
  echo ERRORE: export fallito. Niente commit.
  exit /b 1
)

echo === [4/4] Commit + push (pull --rebase prima, per sicurezza) ===
git pull --rebase --autostash
git add tcg_tracker.db dashboard\data\*.json dashboard\buylist_live.json
git diff --staged --quiet
if %errorlevel%==0 (
  echo Nessuna variazione da committare.
  goto :fine
)
git commit -m "chore: prezzi CR+HR dal PC"
git push
echo.
echo Fatto. Cloudflare Pages ridistribuira' la dashboard a breve.

:fine
endlocal
