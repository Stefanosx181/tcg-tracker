# Deploy — aggiornamento automatico + dashboard online (gratis)

Architettura:

```
GitHub Actions (cron settimanale)
   └─ scraping CardRush + Hareruya
        └─ append nello storico (tcg_tracker.db, mai cancellato)
             └─ export dashboard/data/*.json
                  └─ commit nel repo PRIVATO
                       └─ Cloudflare Pages ridistribuisce la pagina
                            └─ URL nascosto, visibile solo a chi ha il link
```

Tutto gratis: GitHub Actions (repo privato = 2000 min/mese, ne servono ~8),
Cloudflare Pages (hosting statico illimitato).

---

## 1) Crea il repo GitHub PRIVATO e carica il progetto

Da dentro la cartella del progetto (`tcg_tracker/`, quella con `src/`, `dashboard/`, `.github/`):

```bash
git init
git add .
git commit -m "TCG Tracker: scraper + dashboard + automazione"
```

Poi su GitHub: **New repository** → nome a piacere → **Private** → *Create*.
Infine collega e carica (sostituisci USER/REPO):

```bash
git branch -M main
git remote add origin https://github.com/USER/REPO.git
git push -u origin main
```

## 2) Abilita la scrittura per le Actions

Sul repo: **Settings → Actions → General → Workflow permissions** →
seleziona **Read and write permissions** → *Save*.
(Serve perché il workflow ricommitta i prezzi aggiornati.)

## 3) Primo test dello scraping in cloud  ⚠️ importante

Sul repo: **Actions → "Aggiorna prezzi TCG" → Run workflow**.
Apri il log del job e controlla la fine:

- ✅ se vedi `cardrush: 1xx/115` e `hareruya: 1xx/115` e un commit `chore: aggiornamento prezzi …` → **funziona**.
- ❌ se vedi `ATTENZIONE: nessun prezzo trovato per: …` (job fallito) → i siti
  giapponesi stanno bloccando gli IP di GitHub. **Piano B**: lo scraping gira sul
  tuo PC (vedi sezione "Piano B" in fondo) e pusha i dati; il resto resta identico.

## 4) Pubblica la dashboard su Cloudflare Pages

1. Crea un account gratuito su <https://dash.cloudflare.com> (se non ce l'hai).
2. **Workers & Pages → Create → Pages → Connect to Git** → autorizza GitHub →
   seleziona il repo privato.
3. Impostazioni build:
   - **Framework preset**: `None`
   - **Build command**: *(lascia vuoto)*
   - **Build output directory**: `dashboard`
4. **Save and Deploy**. Ottieni un URL tipo `https://NOME.pages.dev` → è la dashboard.

Da qui in poi è **automatico**: ogni volta che le Actions committano nuovi prezzi,
Cloudflare ridistribuisce la pagina da solo. Tu condividi l'URL `*.pages.dev`
solo con la persona interessata (è "nascosto": non indicizzato, non indovinabile).

---

## Aggiornare ogni giorno invece che ogni settimana

In `.github/workflows/scrape.yml`, cambia una riga:

```yaml
- cron: "0 6 * * 1"   # settimanale (lunedì)
+ cron: "0 6 * * *"   # giornaliero
```

## Lanciare un aggiornamento manuale quando vuoi

**Actions → "Aggiorna prezzi TCG" → Run workflow.**

## Piano B — scraping dal tuo PC (se il cloud viene bloccato)

Su Windows, **Utilità di pianificazione** → nuova attività settimanale che esegue:

```
py C:\percorso\tcg_tracker\src\run.py --sleep 1.0
git -C C:\percorso\tcg_tracker add tcg_tracker.db dashboard/data
git -C C:\percorso\tcg_tracker commit -m "update prezzi" && git -C C:\percorso\tcg_tracker push
```

Cloudflare ridistribuisce comunque la pagina ad ogni push. In questo caso togli il
blocco `schedule:` dal workflow (o lascialo: non fa danni, semplicemente non trova
nuovi prezzi).

## Attivare il bottone "Aggiorna ora" (scraping on-demand)

La dashboard ha un bottone che avvia subito il workflow senza aspettare il lunedì.
Tecnicamente il bottone chiama `POST /api/trigger` sul Worker, che lancia il
workflow GitHub usando un token salvato come secret. Per attivarlo, una volta sola:

**1. Crea un token GitHub (fine-grained)**
- GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token
- Resource owner: il tuo account · Repository access: Only select repositories → `tcg-tracker`
- Permissions → Repository permissions → **Actions: Read and write**
- Generate token → copialo (visibile una volta sola)

**2. Salvalo come secret su Cloudflare**
- Cloudflare → Workers & Pages → `tcg-tracker` → Settings → Variables and Secrets
- Add → tipo **Secret** → Name `GH_TOKEN` → Value = il token → Save

Finché il secret non è impostato, il bottone risponde "Token non configurato".
Il token vive solo nel secret store di Cloudflare: non è mai nella pagina né nel repo.

> Nota: l'endpoint `/api/trigger` è raggiungibile da chi conosce l'URL (nascosto).
> Avviare uno scraping è un'azione a basso rischio; se vuoi proteggerlo di più si può
> aggiungere un controllo o Cloudflare Access.
