# CLAUDE.md — Istruzioni di progetto

Claude Code legge questo file automaticamente a ogni sessione. Contiene cosa è il progetto,
i comandi, i vincoli invalicabili e il modo di lavorare. Non serve reincollarlo dopo `/clear`.

---

## Cos'è questo progetto

Comparatore di prezzi di **buyback** (quanto i negozi *pagano* per ricomprare carte, NON il
prezzo di vendita/mercato) per carte Pokémon sul **mercato giapponese**. Confronta due fonti:
**CardRush** (`cardrush.media`) e **Hareruya** (`hare2buy.com`).

Direzione del progetto: espansione a **One Piece** e **Yu-Gi-Oh**, restando il riferimento
per il buyback comparato. Il vantaggio difendibile è il *buyback comparato multi-gioco*, non
inseguire TCGplayer/Cardmarket. La UI deve restare semplice e usabile da un collezionista non
tecnico.

## Contratto-output (cosa "loro" vogliono vedere) — il confine del progetto

La sorgente di verità è `Import_Kumamoto.xlsx` (mai modificato). È il gestionale completo di
un'attività di import/rivendita carte JP. **L'app possiede SOLO lo slice prezzi + trend.**
Il resto resta nell'Excel e NON va costruito.

IN SCOPE (gli output che l'app deve produrre, per Pokémon e — in espansione — One Piece/Yu-Gi-Oh):
1. **Buylist per carta**: buyback CardRush vs Hareruya, prezzo ×1.10, miglior fonte
   (= colonne sx del foglio `BuyList Pokemon`).
2. **Indice di prezzo / trend**: indice settimanale **ponderato a pesi fissi sulla data base**
   per set, CR vs HR2 (= foglio `Market Trend (Pokemon)`), e la serie storica aggregata
   (= foglio `Charts`). Replicato in `src/database.py::export_web`.

⛔ OUT OF SCOPE — NON costruire (restano nell'Excel):
- pianificatore budget per rarità (target/budget necessario/residuo)
- registro acquisti reali
- negoziazione Mercari (`Mercari`)
- spedizioni/rivendita (`Shipped Cards`, `Shipping adress`)
Se un task sembra richiedere queste cose, FERMATI e chiedi: sono fuori scope.

🔒 Vincolo sul trend: il calcolo dell'indice deve **continuare a coincidere** con quello del
foglio `Market Trend`/`Charts` (pesi fissati alla data base). Miglioramenti tipo
anti-outlier/normalizzazione vanno aggiunti come VISTA AGGIUNTIVA, non sostituendo il numero
ufficiale che loro si aspettano di vedere.

## Architettura e flusso dati

```
Excel (seed) → db/ SQL → tcg_tracker.db (SQLite)
   → src/scrapers.py  (livello basso: HttpClient + parse_cardrush/hareruya/yuyutei + LayoutError)
   → src/adapters.py  (SourceAdapter per fonte: build_query/fetch/parse→Offer; registry ADAPTERS;
                       routing per GIOCO via a.supports(game): Pokémon=cardrush+hareruya,
                       One Piece=cardrush+yuyutei)
   → src/run.py       (orchestratore: per ogni carta cicla gli adapter del suo gioco; --game/--set)
   → src/database.py  (accesso DB, save_price con carry-forward, export_web → JSON multi-fonte)
   → dashboard/data/*.json (buylist.json, history.json, setindex.json, movers.json)
   → dashboard/ (statica, Cloudflare Pages)
GitHub Actions (.github/workflows/scrape.yml, cron settimanale) → commit DB+JSON
Cloudflare Worker (worker.js) → auth (Access JWT) + POST /api/trigger
```

## File chiave
- `src/scrapers.py` — livello basso testabile: `fetch` (`HttpClient`: timeout, retry+backoff,
  User-Agent, rate-limit) + `parse_cardrush`/`parse_hareruya` (HTML/JSON grezzo → lista, offline)
  + helper. `LayoutError` = struttura pagina cambiata (≠ "0 risultati"). Selettori in `HARERUYA_SELECTORS`.
- `src/adapters.py` — interfaccia `SourceAdapter` (`build_query`/`fetch`/`parse`→`Offer`, +
  `select` variant-aware/`scrape` condivisi, `supports(game)`) e gli adapter `CardRushAdapter`
  (tutti i giochi), `HareruyaAdapter` (solo Pokémon), `YuyuteiAdapter` (One Piece + Yu-Gi-Oh,
  per-set `/buy/{opc|ygo}/s/{set}` con cache). Registry `ADAPTERS`. Aggiungere una fonte = aggiungere
  un adapter qui (vedi `docs/ADAPTERS.md`).
- `src/database.py` — `save_price` (status esplicito `confirmed/carried/absent`, carry-forward
  LIMITATO nel tempo `max_carry_days`, flag `is_outlier` vs mediana storica), `export_web` (JSON
  multi-fonte: ogni riga buylist ha `prices`{source:{price,comm,stock,status,outlier}} + `game`
  + `trend`{source:{d7,d30,d90}}, `best_*` su tutte le fonti; indice/trend per fonte dinamica).
  `setindex.json`: indice UFFICIALE (`sets`/`global`, pesi fissi alla data base = foglio Charts)
  + vista NORMALIZZATA anti-outlier (`sets_norm`/`global_norm`, esclude outlier e non-confirmed).
  `ensure_intelligence_columns` aggiunge le colonne Fase 3 ai DB v2 esistenti (idempotente).
  SEGNALI azionabili (`movers.json`): `compute_alerts` (puro) calcola SPREAD best-vs-second tra
  negozi + MOVERS 7gg, usando SOLO prezzi affidabili (confirmed+non-outlier) e `series_norm`
  (aggancio anti-outlier/stale 3.1 → niente falsi segnali). Soglie `move_pct`/`spread_pct`
  (default 15/20%) parametri di `export_web`. `dispatch_alerts(payload, hook)` = aggancio per
  notifiche FUTURE (no-op di default; `export_web(..., alert_hook=)`).
- `src/build_catalog.py` — HARVESTER del catalogo OP/YGO: dalla pagina-set Yuyu-tei
  (`/buy/{opc|ygo}/s/{set}`, che elenca tutte le carte) costruisce le righe `tcg_card` nel DB v2
  (identita' canonica `(set, number, variant)`, standard vs `parallel` dal nome, URL CardRush
  per gioco; idempotente). Uso: `python src/build_catalog.py onepiece OP01 "ROMANCE DAWN"`
  (`--html` per cataloghare offline da una fixture). Test: `tests/test_build_catalog.py`.
- `db/seed_onepiece_sample.sql`, `db/seed_yugioh_sample.sql` — seed di PROVA One Piece (OP01,
  standard + variante parallel) e Yu-Gi-Oh (QCCU-JP002), per il sandbox `tcg_tracker.backup.db`
- `src/run.py` — eseguibile principale, flag `--set --limit --only --sleep`; cicla sul registry
  `ADAPTERS` (no fonti hard-coded), `HttpClient` condiviso, conta i `LayoutError` per l'allarme per-fonte.
- `src/init_db.py` — crea/aggiorna il DB (idempotente): bootstrap v1 dal seed → migra a v2;
  un DB v1 esistente viene aggiornato a v2 in-place (storico preservato). `--force` = da zero.
- `db/schema_sqlite.sql` — **schema corrente v2 (multi-gioco, game-agnostic)**; viste
  `v_latest_price`/`v_buylist` con alias ai nomi v1 → contratto-output invariato.
- `db/schema_v1_sqlite.sql` — schema v1 (Pokémon), solo per il bootstrap dal seed.
- `db/migrate_001_multigame.py` — migrazione v1→v2 (id preservati, pre-check collisioni/sorgenti).
- `tests/test_scrapers.py`, `tests/test_migration.py`, `tests/test_adapters.py` — test pytest
  offline; `tests/fixtures/` = pagine reali CR+HR
- `docs/ADAPTERS.md` — come scrivere/registrare un nuovo `SourceAdapter`
- `dashboard/index.html` — **UNICA UI** (la padrona), servita da Cloudflare (Worker + asset
  statici, vedi `wrangler.jsonc`/`worker.js`). Vanilla JS + Chart.js; layout a griglia di card
  con immagine, prezzi CR/HR/YT, totali per set, modal con grafico storico; dati via `fetch`
  di `data/*.json`. NIENTE dati inline.
- `dashboard/app.py` — anteprima LOCALE che serve gli STESSI file statici di Cloudflare
  (`index.html`+`data/`+`images/`), così localhost è identico al sito. Non c'è un secondo
  template. `/api/trigger` in locale è un no-op 501 (esiste solo sul Worker). Per fedeltà
  totale: `npx wrangler dev`.

## Comandi
```bash
python src/init_db.py            # crea/aggiorna DB v1->v2 (storico preservato)
python src/run.py --limit 3      # test scraping su 3 carte
python src/run.py --set S12A     # un solo set
python src/run.py --game onepiece  # solo One Piece (adapter cardrush+yuyutei)
python src/run.py --only cardrush
python db/migrate_001_multigame.py tcg_tracker.backup.db  # migrazione su un file specifico
pytest                           # test scraper+migrazione+adapter offline (usa tests/fixtures/)
```

---

## ⛔ VINCOLI INVALICABILI

1. **NON cancellare mai lo storico prezzi in `tcg_price`.** Nessuna migrazione/refactor deve
   perdere lo storico. Mai usare `init_db.py --force` sul DB reale.
2. **Prima di toccare il DB reale, backup**: `cp tcg_tracker.db tcg_tracker.backup.db`, e fai
   girare migrazioni/script PRIMA sulla copia, mostrando conteggi righe prima/dopo.
3. Niente segreti hard-coded nel codice (GH_TOKEN ecc. restano secret/env).

## Modo di lavorare (ogni sessione)
- **Prima il piano**: sui lavori strutturali (schema, migrazione, refactor scraper) mostra il
  piano in max 10 righe e **aspetta l'ok** prima di modificare file. Sui lavori piccoli procedi.
- **Diff piccoli e revisionabili**, non riscritture monolitiche.
- **Dopo ogni modifica**: fai girare i test e mostra l'output.
- **A fine fase**: committa con messaggio sensato (sono i miei punti di ripristino).
- **A fine fase, aggiorna QUESTO file (`CLAUDE.md`)**: rimuovi dalle "Trappole note" i
  problemi che hai appena risolto, aggiorna architettura/comandi/file chiave se cambiati, e
  segna la fase come completata nella roadmap. Il `CLAUDE.md` deve sempre riflettere lo stato
  ATTUALE del codice, non descrivere problemi già risolti. Includi questa modifica nel commit
  di fine fase.
- **Output di analisi** (audit, ricognizioni, review): scrivili in `docs/`, non solo in chat.
- **Una fase per conversazione**: a fine fase si fa `/clear` e si riparte pulito.
- Dove esistono **API/dataset ufficiali**, preferiscili allo scraping (più stabili, meno ToS).

## Trappole note (già individuate — non reintrodurle)
- **Catalogo OP/YGO PARZIALE**: il DB reale ha dati VERI per Pokémon (263, 32 set) + One Piece
  `OP01` (43 carte) + Yu-Gi-Oh `QCCU` (200 carte), scrapati il 2026-06-28. Mancano gli ALTRI set
  OP/YGO: il catalogo va esteso con `build_catalog.py` set per set. `name_en` per OP/YGO è null
  (solo nome JP): la UI mostra il nome giapponese finché non si aggiunge la traduzione.
- **Indice globale mescola i giochi**: il bottone "Andamento" usa `setindex.global` calcolato
  su TUTTI i set (ora anche OP/YGO): aggregato poco sensato cross-gioco. Da rendere per-gioco.
  (I 📈 per-set restano corretti.)
- **best_price = max()**: può catturare una variante/error card invece della standard. Ora il
  flag `is_outlier` (vs mediana storica) la segnala e la vista normalizzata la esclude
  dall'indice, ma la SELEZIONE del best_price è ancora `max()`: migliorabile.
- **DB committato a ogni run**: gonfia la history git nel tempo.
- **Casing incoerente** nei dati: `S12a` vs `SV1V`; `full_name` mescola JP/EN e ripete il set.

## Roadmap (riferimento)
Il piano completo dei prompt per fase è in `PROMPT_PLAYBOOK_CLAUDECODE.md`. Ordine rigido,
con stato (aggiornalo a fine fase):
- [x] Fase 0 — scraper robusti e testabili (3 livelli fetch/parse/pick, `HttpClient` con
      retry+backoff+rate-limit, `LayoutError` + allarme per-fonte, test pytest offline su fixtures)
- [x] Fase 1 — schema multi-gioco + migrazione (schema v2 game-agnostic: game/set/card con
      identità canonica + source + price raw/norm; migrazione id-preserving v1→v2 con diff-zero
      su buylist/indice; viste con alias v1). ✅ DB reale MIGRATO a v2 il 2026-06-28
      (`init_db.py`, storico 5048 prezzi / 263 carte preservato, diff-zero su buylist verificato;
      backup `tcg_tracker.db.premig.bak` locale, non committato). `buylist.json` ora ha
      `game`/`prices{}`/`trend{}`; `index.html` usa lo schema nativo `prices{}`.
- [x] Fase 2 — One Piece, Yu-Gi-Oh
      Entrambi FATTI: adapter CardRush (riuso, swap categoria) + Yuyu-tei (per-set) a due fonti,
      buylist+trend per gioco. ✅ DATI REALI sul DB (2026-06-28): One Piece `OP01` (43 carte) +
      Yu-Gi-Oh `QCCU` (200 carte), catalogo costruito con `build_catalog.py` (harvest da Yuyu-tei)
      e prezzi scrapati live (`run.py --game`). One Piece: standard + variante parallel.
      ⚠️ YGO: lo stesso set code ha piu' rarita'/versioni (CardRush distingue per rarita', Yuyu-tei
      per suffisso nome); senza disambiguazione fine la scelta 'standard' prende il max per fonte
      (puo' essere una stampa diversa tra CR e Yuyu-tei). Migliorabile in Fase 3 (intelligence).
- [x] Fase 3 — intelligence prezzi
      Slice prezzi+trend in `src/database.py`: prezzo grezzo (`price_raw`) vs normalizzato
      (`price_norm` ×1.10, invariato); carry-forward reso ESPLICITO e LIMITATO nel tempo
      (`price_status` confirmed/carried/absent, ancorato all'ultimo confirmed, `max_carry_days`
      default 30); rilevamento outlier vs MEDIANA storica della carta+fonte (`is_outlier`,
      soglia 50%, serve ≥3 storici). Trend per carta 7/30/90gg in `buylist.json`. Vista
      NORMALIZZATA anti-outlier in `setindex.json` (`sets_norm`/`global_norm`) AGGIUNTIVA:
      l'indice UFFICIALE (`sets`/`global`, pesi fissi alla data base) resta byte-identico al
      foglio Charts/Market Trend — lockato da `tests/test_intelligence.py`
      (`test_official_index_matches_excel_formula`).
      3.2 — SEGNALI azionabili (`dashboard/data/movers.json`): spread best-vs-second tra negozi
      + movers 7gg, su prezzi affidabili (confirmed+non-outlier) e serie normalizzata (aggancio
      3.1). `compute_alerts`/`dispatch_alerts` (hook notifiche future, no-op). Test in
      `tests/test_movers.py`. 72 test verdi.
      ⚠️ Resta: la SELEZIONE del best_price è ancora `max()` (il flag outlier la segnala ma non
      la corregge); disambiguazione fine rarità/stampa YGO (vedi Fase 2). La dashboard non
      consuma ancora `movers.json` (lavoro UX, Fase 4).
- [~] Fase 4 — UX (in corso)
      Dashboard unica `dashboard/index.html` (griglia di card, fetch dei JSON, modal con grafico
      storico). SEPARAZIONE PER GIOCO: schede Pokémon / One Piece / Yu-Gi-Oh in cima (default il
      primo gioco); set-filter, totali e fonti si adattano al gioco attivo → niente più giochi
      mescolati. `app.py` serve gli stessi statici di Cloudflare (localhost == sito).
      ⚠️ Resta: tradurre i nomi OP/YGO (ora solo JP), indice "Andamento" per-gioco, consumo di
      `movers.json`, immagini per OP/YGO.
- [ ] Fase 5 — scala / ops

Non aggiungere giochi prima dello schema multi-gioco (Fase 1).
