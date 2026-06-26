@echo off
REM ============================================================
REM  Compila lo scraper in un eseguibile Windows (.exe)
REM  Richiede: Windows + Python 3.10+  (gli .exe sono platform-specific:
REM  vanno generati su Windows, non su Linux/Mac).
REM ============================================================
cd /d "%~dp0\.."
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller

REM Eseguibile dello scraper (CLI)
pyinstaller --onefile --name TCG-Tracker-Scraper ^
    --add-data "db;db" ^
    src\run.py

REM Eseguibile per inizializzare il DB SQLite
pyinstaller --onefile --name TCG-Tracker-InitDB ^
    --add-data "db;db" ^
    src\init_db.py

echo.
echo Fatto. Trovi gli .exe nella cartella dist\
pause
