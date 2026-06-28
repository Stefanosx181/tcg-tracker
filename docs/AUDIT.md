# AUDIT — TCG Tracker

> Ricognizione a sola lettura del repo. Nessun file di codice è stato modificato.
> Data: 2026-06-28. Riferimenti `file:riga` relativi alla root `tcg_tracker/`.
> Stato dati al momento dell'audit: 263 carte, 5048 prezzi, 11 snapshot
> (2026-04-07 → 2026-06-28), 12 record `in_stock=0` (carry-forward).

---

## 1. Mappa del flusso dati

```
Import_Kumamoto.xlsx  (sorgente di verità, MAI letto dall'app — solo seed manuale)
   │  (estrazione una tantum → SQL)
   ▼
db/schema_sqlite.sql  +  db/02_seed_sets_cards.sql   (32 set, 263 carte, URL CR/HR già pronti)
   │  src/init_db.py  (idempotente: crea solo se DB vuoto; --force CANCELLA lo storico)
   ▼
tcg_tracker.db  (SQLite, committato nel repo — è lo storico prezzi)
   │  tabelle: tcg_set → tcg_card → tcg_price(storico)
   │  viste:  v_latest_price (ultimo per carta+fonte) → v_buylist (riga per carta, CR vs HR)
   ▼
src/run.py  (orchestratore)
   ├─ db.fetch_cards()                          legge le 263 carte + URL
   ├─ per ogni carta:
   │    scrapers.scrape_cardrush(url)           __NEXT_DATA__ JSON → buyingPrices → max(amount standard)
   │    scrapers.scrape_hareruya(code,pack,mod) HTML hare2buy → filtra per 〈###/###〉 → max(prezzo)
   │    db.save_price(...)                       INSERT storico + carry-forward se prezzo None
   ├─ db.export_web(DATA_DIR)                   → dashboard/data/buylist.json + history.json + setindex.json
   └─ db.export_buylist_json(LEGACY_JSON)       → dashboard/buylist_live.json (retro-compat standalone)
   ▼
dashboard/data/*.json   (3 file)               buylist=snapshot, history=serie 1pt/giorno, setindex=indice ponderato
   ▼
dashboard/index.html  (statica, deployata)     fetch() dei 3 JSON → tabella per set + grafici Chart.js + modal indice
   │                                            (dashboard/dashboard.html = vecchia versione con dati INLINE, NON deployata)
   ▼
Cloudflare Pages (asset)  +  worker.js
   ├─ ASSETS.fetch  → serve dashboard/
   ├─ Cloudflare Access (JWT) → auth; ENFORCE_JWT opzionale rivalida la firma
   └─ POST /api/trigger → GitHub workflow_dispatch (secret GH_TOKEN) ── bottone "Aggiorna ora"
   ▲
.github/workflows/scrape.yml  (cron lunedì 06:00 UTC + dispatch)
   init_db → run.py → git add DB+JSON → commit → push   (ricommit dello storico)
```

**Anelli deboli del flusso** (dettaglio nei debiti):
- Il workflow **non ricommitta `setindex.json`** → l'indice/trend in produzione è congelato.
- `dashboard/dashboard.html` è un secondo front-end con dati stantii incorporati.
- `export_buylist_json` produce un quarto JSON (`buylist_live.json`) che nessuna pagina deployata consuma.

---

## 2. I 10 debiti tecnici più gravi (per impatto)

### D1 — Il workflow non committa `setindex.json`: il trend in produzione è morto
`.github/workflows/scrape.yml:48` — `git add tcg_tracker.db dashboard/data/buylist.json dashboard/data/history.json dashboard/buylist_live.json`
La pagina live legge l'indice da `dashboard/data/setindex.json` (`dashboard/index.html:189`), che `run.py`
rigenera ad ogni run ma il workflow **non aggiunge al commit**. Risultato: i grafici "📈 Andamento"
(set e globale) mostrano sempre l'ultimo `setindex.json` committato a mano, mai aggiornato dal cron.
**Costo di non risolverlo:** metà del contratto-output (indice/trend, il foglio `Charts`) è di fatto
non funzionante in produzione pur sembrando attivo. È il bug a più alto impatto/più basso costo di fix.

### D2 — Schema Pokémon-specifico, manca la dimensione `game`: blocca tutta la roadmap
`db/schema_sqlite.sql:14-32` — `pack_code` PK testuale, `model_number`, `card_code` ('114/083').
Non esiste colonna `game`; l'identità carta è modellata su Pokémon JP (`〈###/###〉`, `pack_code` tipo `M4`).
One Piece (`OP01-001`) e Yu-Gi-Oh non hanno questa forma. La logica di matching è incisa negli scraper
(`scrapers.py:99`, `scrapers.py:132 _COLLECTOR_RE`).
**Costo di non risolverlo:** l'espansione multi-gioco (Fase 1-2, il vantaggio difendibile dichiarato nel
CLAUDE.md) è impossibile senza prima toccare schema + scraper. Ogni feature aggiunta ora aumenta il costo
della migrazione.

### D3 — Scraper fragili senza alcun test/fixture; rilevamento rotture troppo grossolano
`src/scrapers.py` (intero) + `src/run.py:87` — selettori Hareruya dichiarati "da verificare"
(`scrapers.py:126-130`), CardRush legato alla forma di `__NEXT_DATA__` (`scrapers.py:55-63`).
Zero test, zero HTML di esempio salvati. Il solo allarme è `run.py:87`: scatta **solo se una fonte
restituisce ZERO prezzi su tutte le carte**. Una rottura parziale (es. cambia il layout di una rarità,
o il 60% delle carte smette di matchare) passa inosservata e viene mascherata dal carry-forward (D4).
**Costo di non risolverlo:** drift silenzioso dei dati. Il sito cambia, i numeri restano "plausibili"
ma sbagliati per settimane, erodendo la fiducia nell'unico output del prodotto.

### D4 — Carry-forward illimitato nel tempo: maschera carte delisted e inquina l'indice
`src/database.py:44-66` — se `buying_price is None`, riusa l'ultimo prezzo noto con `in_stock=0`,
**senza limite temporale**. Una carta rimossa dai buyback continua a comparire all'infinito con il
vecchio prezzo. `export_web` (`database.py:145-154`) include comunque quei punti nell'indice di set:
un prezzo fantasma pesa nell'aggregato.
**Costo di non risolverlo:** l'indice ponderato (D1/contratto-output) si discosta dalla realtà man mano
che le carte escono dai listini; il numero "ufficiale" che loro si aspettano di vedere diventa gonfiato.

### D5 — `best_price`/prezzo scelto via `max()`: rischio di catturare la variante/error-card
`db/schema_sqlite.sql:59` (`MAX(... cardrush, hareruya)` nella vista) e `scrapers.py:114` / `scrapers.py:192`
(`return max(chosen)` / `max(prices)`). Lo scraper CardRush separa già le varianti via `extra_difference`
(`scrapers.py:107-111`), ma Hareruya prende il massimo senza distinguere le error-card, e la vista sceglie
comunque il massimo tra le due fonti.
**Costo di non risolverlo:** prezzi sporadicamente troppo alti (carta "errore di stampa" invece della
standard) che falsano sia la buylist sia l'indice; difficili da notare perché sembrano outlier reali.

### D6 — Selettori Hareruya non verificati e nominati `selling_price`: rischio semantico (sell vs buyback)
`src/scrapers.py:126-130` — `HARERUYA_SELECTORS["price"] = ".selling_price, .price"`. Il prodotto confronta
il **buyback** (quanto il negozio paga), non il prezzo di vendita. Un selettore che punta al prezzo di
vendita restituirebbe il numero sbagliato pur "funzionando". I selettori sono dichiarati provvisori e non
c'è una fixture che fissi il contratto della pagina.
**Costo di non risolverlo:** rischio di pubblicare il prezzo *sbagliato per natura* (sell al posto di
buyback) su una delle due fonti — errore invisibile finché qualcuno non confronta a mano col sito.

### D7 — Dashboard a doppia fonte: `dashboard.html` con dati inline stantii
`dashboard/dashboard.html:138` — riga unica `const DATA=[…]` con uno snapshot incorporato (~64k token),
più `backups/dashboard_table_layout.html`. La pagina realmente deployata è `dashboard/index.html`
(fetch dei JSON). Convivono due front-end divergenti.
**Costo di non risolverlo:** chi apre il file sbagliato vede dati vecchi e li crede live; rischio concreto
di deployare la versione stantia. Manutenzione doppia di CSS/markup.

### D8 — Nessun retry/backoff: errore transitorio = prezzo perso = carry-forward
`src/scrapers.py:71` e `:159` — una singola `requests.get`; qualsiasi 5xx/timeout/rate-limit → `None`
→ carry-forward (D4). Nessun tentativo ripetuto, nessuna distinzione tra "carta non più in vendita" e
"richiesta fallita".
**Costo di non risolverlo:** un blip di rete del lunedì mattina degrada silenziosamente una fetta dello
snapshot settimanale, indistinguibile da un delisting reale.

### D9 — DB e JSON ricommittati ad ogni run: history git in crescita illimitata
`.github/workflows/scrape.yml:48` + `.gitignore:19` (DB committato di proposito). `tcg_tracker.db` è già
~626 KB e cresce di ~526 righe/settimana; ogni run aggiunge un blob binario completo + 3 JSON alla history.
**Costo di non risolverlo:** il `.git` si gonfia in modo monotòno (clone/CI sempre più lenti). Problema
lento ma irreversibile senza riscrittura della history.

### D10 — Schema MySQL e SQLite divergenti: il ramo MySQL è già rotto
`db/01_schema.sql:34-48` (MySQL) **non ha** le colonne `name_en` e `rarity` che invece esistono in
`db/schema_sqlite.sql:20-32` e che la vista/dashboard usano (`v_buylist`, `index.html:264-265`).
`database.py:13-21` mantiene un ramo MySQL e `save_price`/`_last_known_price` gestiscono i placeholder
`%s`, ma su MySQL `export_web` fallirebbe (colonne mancanti).
**Costo di non risolverlo:** codice morto che *sembra* supportato; chiunque tenti il path MySQL sbatte su
errori, e ogni modifica di schema va replicata a mano in due file che già divergono.

> **Menzioni minori** (sotto la top-10, da tenere d'occhio): casing incoerente `S12a`/`SV1V` e
> `full_name` che mescola JP/EN ripetendo il set; `buylist_live.json` generato ma non consumato da
> nessuna pagina deployata (`run.py:76`); `app.py` (Flask) è una terza via di accesso ai dati non più
> necessaria col modello statico; `v_latest_price` usa `MAX(scraped_at)` a granularità secondo → due
> scrape nello stesso secondo duplicano la riga in `v_buylist`.

---

## 3. Roadmap in fasi (scope invariato: SOLO prezzi + trend)

Ordine rigido. Ogni fase è una conversazione (`/clear` a fine fase). Nessuna fase introduce gli output
OUT OF SCOPE (budget, acquisti reali, Mercari, spedizioni). Il numero d'indice "ufficiale" resta quello
a pesi fissi del foglio `Charts`; ogni miglioria è una *vista aggiuntiva*.

### Fase 0 — Scraper robusti e testabili (sblocca D1, D3, D6, D8)
Obiettivo: rendere i due output attuali affidabili e osservabili PRIMA di toccare lo schema.
- Aggiungere `dashboard/data/setindex.json` al `git add` del workflow (D1) — fix immediato, alto impatto.
- Salvare HTML/JSON di esempio come fixture e scrivere test su `_extract_cardrush_items`, sul filtro
  `〈###/###〉` e su `_to_int_price`; verificare/congelare i selettori Hareruya e confermare che puntino
  al **buyback** e non al sell (D3, D6).
- Retry con backoff + distinzione esplicita "fallita richiesta" vs "carta assente" (D8).
- Rilevamento rotture per-fonte basato su **soglia** (es. <X% match) invece del solo zero assoluto (D3).
- Esito: scraper con test verdi, allarmi sensibili, indice che si aggiorna in produzione.

### Fase 1 — Schema multi-gioco + migrazione non distruttiva (sblocca D2, D4, D5, D10)
Obiettivo: introdurre l'identità canonica multi-gioco SENZA perdere lo storico `tcg_price`.
- Backup obbligatorio (`cp tcg_tracker.db tcg_tracker.backup.db`), migrazione su copia, conteggi righe
  prima/dopo (vincolo invalicabile del CLAUDE.md).
- Aggiungere dimensione `game` e una identità canonica indipendente dal formato Pokémon (D2); decidere
  un unico schema sorgente ed eliminare/derivare l'altro per chiudere la divergenza MySQL/SQLite (D10).
- Rendere il carry-forward esplicito e **limitato nel tempo** (es. decade dopo N settimane) come parte
  della migrazione, marcando le carte delisted (D4).
- Rendere la scelta del prezzo robusta alle varianti anche lato Hareruya (D5).
- Vincolo: l'indice deve **continuare a coincidere** col foglio `Charts` per i dati Pokémon esistenti
  (test di regressione sui valori storici).

### Fase 2 — One Piece + Yu-Gi-Oh (solo dopo Fase 1)
Obiettivo: estendere buylist + indice ai due nuovi giochi, riusando la pipeline.
- Scraper per le sorgenti buyback dei nuovi giochi (preferire eventuali API/dataset ufficiali allo
  scraping, come da CLAUDE.md); identità canonica `OP01-001` ecc. già supportata dallo schema di Fase 1.
- Seed e immagini per i nuovi set; la dashboard è già pensata per raggruppare per set.
- Stesso contratto-output (buylist ×1.10 + indice ponderato), nessun nuovo tipo di output.

### Fase 3 — Intelligence prezzi (solo viste aggiuntive)
Obiettivo: migliorare la *lettura* dei dati senza toccare il numero ufficiale.
- Vista anti-outlier / normalizzata dell'indice come layer separato (il numero a pesi fissi resta quello
  mostrato di default).
- Segnalazione automatica di salti sospetti (possibile error-card/variante) e di carte "stantie" da
  carry-forward, sfruttando il flag esplicito introdotto in Fase 1.

### Fase 4 — UX (consolidamento front-end)
Obiettivo: una sola fonte di verità per la UI.
- Eliminare `dashboard/dashboard.html` (inline stantio) e `backups/` divergenti; unificare su
  `index.html` via fetch (D7). Valutare se ritirare `app.py`/`buylist_live.json` ora ridondanti.
- Indicatori chiari per prezzo riportato/non confermato e per fonte migliore (già abbozzati).

### Fase 5 — Scala / ops
Obiettivo: sostenibilità operativa nel tempo.
- Risolvere il gonfiore git del DB committato (D9): es. spostare lo storico fuori dal versionamento
  binario o compattarlo, mantenendo il vincolo "mai perdere `tcg_price`".
- Monitoraggio/notifiche sulle rotture scraper; eventuale parallelizzazione delle richieste entro i
  limiti di cortesia verso i siti.

---

## Appendice — riferimenti rapidi `file:riga`

| # | Debito | Riferimento |
|---|--------|-------------|
| D1 | setindex.json non committato | `.github/workflows/scrape.yml:48` ↔ `dashboard/index.html:189` |
| D2 | schema Pokémon-specifico | `db/schema_sqlite.sql:14-32`, `src/scrapers.py:99,132` |
| D3 | scraper senza test, allarme grossolano | `src/scrapers.py:55-63,126-130`, `src/run.py:87` |
| D4 | carry-forward illimitato | `src/database.py:44-66`, `src/database.py:145-154` |
| D5 | prezzo via max() | `db/schema_sqlite.sql:59`, `src/scrapers.py:114,192` |
| D6 | selettore Hareruya sell vs buyback | `src/scrapers.py:126-130` |
| D7 | dashboard doppia fonte | `dashboard/dashboard.html:138`, `backups/` |
| D8 | nessun retry/backoff | `src/scrapers.py:71,159` |
| D9 | DB ricommittato ogni run | `.github/workflows/scrape.yml:48`, `.gitignore:19` |
| D10 | drift schema MySQL/SQLite | `db/01_schema.sql:34-48` ↔ `db/schema_sqlite.sql:20-32` |
