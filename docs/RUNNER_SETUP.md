# Runner PC — setup passo per passo

Come far girare l'aggiornamento prezzi **da un PC** (IP residenziale, che CardRush non
blocca), al posto del cron cloud. Vale per **qualsiasi PC Windows**: lo script è portabile
(percorsi relativi al repo, niente cartelle utente cablate).

> **Perché dal PC.** CardRush blocca con **403** gli IP datacenter di GitHub Actions (anche
> la forma per-carta), in modo intermittente → il cron cloud falliva spesso. Dal tuo PC
> funziona. Il cron cloud è stato **disattivato** (`.github/workflows/scrape.yml`).

> **⚠️ REGOLA D'ORO — un solo runner alla volta.** Il database `tcg_tracker.db` è un file
> **binario committato nel repo**. Se due macchine (o PC + cron) lo scrivono, git non sa
> fondere il binario → conflitti di push. Quindi: **un solo PC attivo** che aggiorna. Cambi
> PC? Configura il nuovo e **togli la pianificazione dal vecchio** (passo 6).

---

## Cosa fa lo script `scripts/scrape_and_push.bat`
1. **CardRush**: harvest catalogo + tutti i prezzi (lista SPA, veloce).
2. **Hareruya**: prezzi per-carta/set (batch per staleness).
3. Rigenera i JSON della dashboard (`dashboard/data/*.json`).
4. `git pull --rebase` → `commit` → `push`. Cloudflare Pages ridistribuisce da solo.

---

## Prerequisiti (installa una volta sul PC)

### 1. Python 3.12 (con il launcher `py`)
- Scarica da <https://www.python.org/downloads/> (Windows installer).
- Nell'installer **spunta "Add python.exe to PATH"** e lascia attivo **"py launcher"**.
- Verifica in un Prompt/PowerShell nuovo:
  ```
  py --version
  ```
  Deve stampare `Python 3.12.x`.

### 2. Git (per Windows)
- Scarica da <https://git-scm.com/download/win>. Installa con le opzioni di default
  (include **Git Credential Manager**, che ricorda le credenziali di push).
- Verifica:
  ```
  git --version
  ```

### 3. (Consigliato) GitHub CLI — per l'autenticazione al push
- Scarica da <https://cli.github.com/>.
- Verifica: `gh --version`.

---

## Setup del repo sul PC

### 4. Clona il repository
Apri PowerShell nella cartella dove vuoi tenere il progetto (es. `C:\progetti`) ed esegui:
```
git clone https://github.com/Stefanosx181/tcg-tracker.git
cd tcg-tracker
```
> Nota: il repo include lo storico e il DB, quindi il clone può pesare qualche centinaio di MB.

### 5. Installa le dipendenze Python
```
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

### 6. Configura l'identità git e l'accesso al push
Identità (una volta):
```
git config user.name  "TCG Bot"
git config user.email "tuo@email.com"
```
Accesso al push — **scegli UN metodo**:

- **Metodo A (facile): GitHub CLI**
  ```
  gh auth login
  ```
  Scegli `GitHub.com` → `HTTPS` → login via browser. Fatto: git userà queste credenziali.

- **Metodo B: Personal Access Token (PAT)**
  1. Vai su <https://github.com/settings/tokens> → *Generate new token (classic)*.
  2. Scope: **`repo`**. Genera e **copia** il token.
  3. Al primo `git push` Windows ti chiederà le credenziali: usa il **tuo username** e,
     come **password**, incolla il **token**. Git Credential Manager lo ricorderà.

### 7. Primo run di prova (manuale)
Doppio clic su `scripts\scrape_and_push.bat`, **oppure** da terminale nella cartella del repo:
```
scripts\scrape_and_push.bat
```
- CardRush (~120 pagine) è veloce; **Hareruya può durare alcune ore** al primo giro
  completo (`HR_BATCH=11000`). Vuoi un test rapido? Apri il `.bat` e metti `set HR_BATCH=50`
  per la prova, poi rimettilo a `11000`.
- A fine run deve fare `commit` + `push`. Controlla che sul sito i prezzi si aggiornino
  (dopo 1-2 min; se vedi ancora il vecchio è cache → hard refresh).

---

## Pianificazione automatica (Utilità di pianificazione di Windows)

Così gira da solo (es. una volta a settimana, di notte).

1. Premi `Win` → scrivi **"Utilità di pianificazione"** → aprila.
2. A destra: **"Crea attività…"** (non "Crea attività di base", serve più controllo).
3. **Scheda Generale**
   - Nome: `TCG prezzi settimanale`.
   - Seleziona **"Esegui indipendentemente dalla connessione dell'utente"** (gira anche
     se non hai fatto login). *(Richiederà la password Windows dell'utente.)*
   - Spunta **"Esegui con i privilegi più elevati"**.
4. **Scheda Attivazione → Nuovo…**
   - Inizio attività: **"In base a una pianificazione"** → **Settimanale** → scegli il
     giorno/ora (es. **Lunedì 02:00**). OK.
5. **Scheda Azioni → Nuovo…**
   - Azione: **"Avvio programma"**.
   - Programma/script: **il percorso completo del .bat**, es.
     `C:\progetti\tcg-tracker\scripts\scrape_and_push.bat`
   - "Inizio (facoltativo)": la cartella `scripts`, es. `C:\progetti\tcg-tracker\scripts`
     *(non obbligatorio: lo script fa `cd` da solo, ma è più pulito).* OK.
6. **Scheda Condizioni**
   - Spunta **"Riattiva il computer per eseguire l'attività"** (se il PC va in sospensione).
   - Se è un **portatile** e vuoi che giri a batteria, **togli** "Avvia l'attività solo se
     il computer è alimentato…".
7. **Scheda Impostazioni**
   - Spunta **"Consenti esecuzione su richiesta"** (così puoi lanciarla a mano col tasto
     destro → Esegui).
   - "Se l'attività non viene eseguita all'ora prevista, avviala appena possibile".
8. **OK** → inserisci la password Windows quando richiesto.
9. **Prova subito**: tasto destro sull'attività → **Esegui**. Verifica commit+push.

---

## Spostare il runner su un altro PC
1. Sul **PC nuovo**: ripeti i passi **1–7** (prerequisiti + clone + auth + run di prova).
2. Sul **PC vecchio**: apri l'Utilità di pianificazione, **disabilita o elimina** l'attività
   `TCG prezzi settimanale`.
3. Pianifica sul PC nuovo (passo Pianificazione).

> È intercambiabile: "quale PC" = semplicemente quello dove metti la pianificazione. Basta
> che sia **uno solo alla volta** a scrivere il DB.

---

## Problemi comuni
- **`'py' non riconosciuto`** → Python non è nel PATH o manca il launcher. Reinstalla Python
  spuntando "Add to PATH" + "py launcher". Riapri il terminale.
- **`git push` chiede sempre le credenziali** → rifai `gh auth login` (Metodo A) o reinserisci
  il PAT (Metodo B); assicurati che Git Credential Manager sia installato.
- **"Nessuna variazione da committare"** → normale: i prezzi non sono cambiati da quel run.
- **Conflitto in `git pull --rebase` / push rifiutato** → sta scrivendo **un altro** runner
  (altro PC o cron cloud riattivato). Assicurati che ci sia **un solo** runner attivo. In
  emergenza: `git rebase --abort`, poi ripeti il run quando l'altro ha finito.
- **CardRush dà 403 anche dal PC** (raro) → aumenta le pause: nel `.bat` alza `--sleep` (es.
  `--sleep 1.0`) sull'harvest, riprova più tardi.
- **Il run dura troppo (Hareruya)** → abbassa `HR_BATCH` nel `.bat` (es. `3000`): copre le
  carte più vecchie prima, e su più run settimanali si aggiorna tutto a rotazione.

---

## Note
- **One Piece / Yu-Gi-Oh**: questo script aggiorna i **Pokémon**. Per OP/YGO (fonti
  Toretoku/Yuyu-tei) aggiungi manualmente `py src\run.py --game onepiece` / `--game yugioh`
  se/quando quelle fonti sono a posto.
- **Immagini**: di default si salva l'URL CDN remoto (niente download). Per scaricarle in
  locale aggiungi `--images` alla riga dell'harvest nel `.bat`.
- **Riattivare il cron cloud** (es. se un giorno usi un proxy residenziale): togli il commento
  al blocco `schedule:` in `.github/workflows/scrape.yml` **e** spegni il runner PC (mai due
  scrittori insieme).
