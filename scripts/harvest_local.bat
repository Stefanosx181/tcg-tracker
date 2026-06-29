@echo off
REM ============================================================================
REM  harvest_local.bat - Harvest del CATALOGO Pokemon + prezzi CardRush DAL PC.
REM
REM  Perche' dal PC: l'endpoint-lista di CardRush blocca gli IP datacenter di
REM  GitHub Actions (403), quindi l'harvest del catalogo NON puo' girare in cloud.
REM  Dal tuo PC (IP residenziale) funziona. Hareruya invece lo aggiorna il cron
REM  in cloud, quindi qui basta l'harvest CardRush.
REM
REM  Cosa fa: scansiona la lista buyback CardRush (~120 pagine) -> aggiorna le
REM  carte e i prezzi CardRush nel DB, rigenera i JSON della dashboard, poi
REM  commit + push (Cloudflare Pages ridistribuisce da solo).
REM
REM  Uso: doppio clic, oppure pianifica con "Utilita' di pianificazione" di Windows
REM  (es. ogni giorno alle 13:00, quando il cron notturno cloud non e' attivo).
REM  Immagini: di default si salva l'URL CDN remoto (niente download). Aggiungi
REM  --images alla riga del run se vuoi scaricarle in locale.
REM ============================================================================
setlocal
cd /d "%~dp0.."

echo === Harvest CardRush Pokemon (catalogo + prezzi) ===
py src\run.py --harvest-pokemon --sleep 0.5
if errorlevel 1 (
  echo ERRORE: harvest fallito. Niente commit.
  exit /b 1
)

echo === Commit + push ===
git pull --rebase --autostash
git add tcg_tracker.db dashboard\data\*.json dashboard\buylist_live.json
git diff --staged --quiet
if %errorlevel%==0 (
  echo Nessuna variazione da committare.
  exit /b 0
)
git commit -m "chore: harvest catalogo+prezzi CardRush (PC)"
git push
echo Fatto. Cloudflare Pages ridistribuira' la dashboard a breve.
endlocal
