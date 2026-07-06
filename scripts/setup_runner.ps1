# ============================================================================
#  setup_runner.ps1 - Configura il runner settimanale dei prezzi SU QUESTO PC.
#
#  Cosa fa (idempotente, ri-eseguibile):
#   1. verifica che 'py' (Python) e 'git' ci siano;
#   2. installa le dipendenze Python (requirements.txt);
#   3. crea/aggiorna un'attivita' pianificata di Windows che lancia
#      scripts\scrape_and_push.bat una volta a settimana (lunedi 02:00).
#
#  NON puo' fare l'autenticazione git al push (serve interazione): dopo, esegui
#  UNA volta 'gh auth login' (o configura un PAT). Vedi docs/RUNNER_SETUP.md.
#
#  Uso (PowerShell, nella cartella del repo):
#     powershell -ExecutionPolicy Bypass -File scripts\setup_runner.ps1
#  Parametri opzionali: -Day Monday -Time 02:00  (giorno/ora della pianificazione)
#
#  REGOLA D'ORO: un solo PC runner alla volta (il DB e' un file binario committato;
#  due scrittori = conflitti). Su un altro PC: esegui qui e RIMUOVI il task dal vecchio.
# ============================================================================
param(
  [string]$Day  = "Monday",
  [string]$Time = "02:00",
  [string]$TaskName = "TCG prezzi settimanale"
)
$ErrorActionPreference = "Stop"

# --- percorsi (relativi al repo: scripts\.. ) --------------------------------
$repo = Split-Path -Parent $PSScriptRoot
$bat  = Join-Path $PSScriptRoot "scrape_and_push.bat"
$req  = Join-Path $repo "requirements.txt"
if (-not (Test-Path $bat)) { Write-Host "Non trovo $bat - esegui dallo script nella cartella scripts del repo." -ForegroundColor Red; exit 1 }

# --- 1. prerequisiti ---------------------------------------------------------
foreach ($cmd in @("py","git")) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
    Write-Host "MANCA '$cmd'. Installalo prima (Python con 'Add to PATH' + py launcher; Git per Windows). Vedi docs/RUNNER_SETUP.md." -ForegroundColor Red
    exit 1
  }
}
Write-Host "OK: Python e git presenti." -ForegroundColor Green

# --- 2. dipendenze -----------------------------------------------------------
Write-Host "Installo le dipendenze Python..."
& py -m pip install -r $req
if ($LASTEXITCODE -ne 0) { Write-Host "pip install fallito." -ForegroundColor Red; exit 1 }

# --- 3. attivita' pianificata ------------------------------------------------
# Gira nel contesto dell'utente corrente (nessuna password): parte quando l'utente
# e' loggato. Per 'anche a utente non loggato' -> impostalo dalla GUI (serve password).
try {
  $action   = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $PSScriptRoot
  $trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $Time
  $settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
                -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
                -Settings $settings -Description "Aggiorna i prezzi TCG (CardRush+Hareruya) e fa push. Vedi docs/RUNNER_SETUP.md" -Force | Out-Null
  Write-Host "OK: attivita' '$TaskName' creata ($Day $Time)." -ForegroundColor Green
} catch {
  Write-Host "Impossibile creare l'attivita' pianificata: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "Prova a rieseguire questo script in un PowerShell APERTO COME AMMINISTRATORE, oppure crea l'attivita' a mano (docs/RUNNER_SETUP.md)." -ForegroundColor Yellow
  exit 1
}

# --- prossimi passi ----------------------------------------------------------
Write-Host ""
Write-Host "FATTO. Restano 2 cose (una volta sola):" -ForegroundColor Cyan
Write-Host "  1) Autentica il push:  gh auth login   (oppure configura un PAT - vedi docs/RUNNER_SETUP.md)"
Write-Host "  2) Prova subito:       Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "     (il primo giro Hareruya completo puo' durare alcune ore)"
