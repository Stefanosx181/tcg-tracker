# Deploy — aggiornamento automatico + dashboard online (gratis)

Architettura:

```
GitHub Actions — cron NOTTURNO (scrape.yml)            [AUTOMATICO, niente PC]
   └─ PREZZI per-carta CardRush + Hareruya, per staleness (lotti)
        └─ commit + push ─────────────────────────────────┐
                                                           │
SCOPERTA carte nuove (rara, ~quando esce un set):          │
   • via PROXY: discovery.yml (dispatch) con secret SCRAPER_PROXY   [niente PC]
   • oppure dal PC: scripts/harvest_local.bat                       [serve PC acceso]
        └─ harvest lista CardRush -> commit + push ─────────┤
                                                           ▼
   tcg_tracker.db + dashboard/data/*.json  ──► Cloudflare Pages ridistribuisce
                                                  └─ URL nascosto (solo chi ha il link)
```

⚠️ **Perche' i PREZZI girano in cloud ma la SCOPERTA no:** dagli IP datacenter di GitHub
Actions, CardRush applica una regola di **forma della richiesta**, non un ban d'IP:
- la richiesta **PER-CARTA** (`?model_number=...`, forma completa della SPA) **passa**
  → i prezzi CardRush+Hareruya si rinfrescano **in cloud, automaticamente, senza PC** (verificato: 249/250);
- la **LISTA** non filtrata (`model_number` vuoto, "dammi tutto") da' **403 anche in forma
  completa** → la SCOPERTA di carte/set nuovi richiede un **proxy residenziale**
  (`SCRAPER_PROXY`, vedi sotto) oppure il **PC** (`scripts/harvest_local.bat`). È rara
  (solo quando esce un set nuovo), quindi non e' un collo di bottiglia quotidiano.
- Le fonti One Piece/Yu-Gi-Oh (Yuyu-tei/Toretoku) danno 403 anche per-carta → servono comunque proxy/PC.

**Cadenza & minuti:** repo **PUBBLICO** = minuti Actions illimitati. Il cron prezzi gira **1 notte a
settimana** (lunedì), in **4 finestre scaglionate** da 2.600 carte/fonte (4×2.600 = 10.400 ≥ catalogo):
giro COMPLETO CR+HR ma con Hareruya distribuito su ~9h invece che in un'unica raffica.

**Scoperta via proxy (niente PC):** crea un proxy residenziale pay-as-you-go (es. DataImpulse ~1$/GB;
l'harvest mensile sono pochi MB = centesimi), salvalo come **GitHub Secret `SCRAPER_PROXY`**
(`http://user:pass@host:port`) e lancia il workflow **"Scoperta catalogo"** (Actions → Run workflow).
Tutto gratis: Cloudflare Pages (hosting statico illimitato).

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

## Aggiornamento on-demand: RIMOSSO

Il bottone "Aggiorna ora" e l'endpoint `POST /api/trigger` sono stati **rimossi**:
l'aggiornamento prezzi è SOLO automatico (cron settimanale qui sopra) + eventuale
`workflow_dispatch` manuale da GitHub → Actions → "Run workflow". Niente token
`GH_TOKEN` su Cloudflare, niente endpoint pubblico da proteggere.
