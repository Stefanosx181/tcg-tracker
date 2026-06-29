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
CATALOGO Pokémon = lista buyback CardRush (HARVEST paginato), NON piu' l'Excel:
  src/build_catalog.harvest_pokemon_cardrush → tutte le singole + prezzi CR + immagini
CATALOGO OP/YGO  = pagina-set Yuyu-tei (build_catalog.harvest, set per set)
                         ↓
   tcg_tracker.db (SQLite)
   → src/scrapers.py  (livello basso: HttpClient + parse_cardrush/hareruya/yuyutei + LayoutError)
   → src/adapters.py  (SourceAdapter per fonte: build_query/fetch/parse→Offer; registry ADAPTERS;
                       routing per GIOCO via a.supports(game): Pokémon=cardrush+hareruya,
                       One Piece=cardrush+TORETOKU, Yu-Gi-Oh=cardrush+yuyutei)
   → src/run.py       (orchestratore: --harvest-pokemon = catalogo+prezzi CR in 1 passata;
                       altrimenti per ogni carta cicla gli adapter del suo gioco; Hareruya
                       per-carta shardato con --batch (staleness) + jitter/set-gap)
   → src/database.py  (accesso DB, save_price con carry-forward, fetch_cards_stale, export_web)
   → dashboard/data/*.json (buylist.json, history.json, setindex.json, movers.json)
   → dashboard/ (statica, Cloudflare Pages)
GitHub Actions (.github/workflows/scrape.yml, cron NOTTURNO multi-trigger: 1o trigger = harvest
   CR completo + OP/YGO; trigger seguenti = lotti Hareruya per staleness) → commit DB+JSON
Cloudflare Worker (worker.js) → auth (Access JWT) + POST /api/trigger
```

## File chiave
- `src/scrapers.py` — livello basso testabile: `fetch` (`HttpClient`: timeout, retry+backoff,
  User-Agent, rate-limit) + `parse_cardrush`/`parse_hareruya` (HTML/JSON grezzo → lista, offline)
  + `cardrush_last_page` (pageProps.lastPage, per paginare l'harvest Pokémon) + helper.
  `LayoutError` = struttura pagina cambiata (≠ "0 risultati"). Selettori in `HARERUYA_SELECTORS`.
- `src/adapters.py` — interfaccia `SourceAdapter` (`build_query`/`fetch`/`parse`→`Offer`, +
  `select` variant-aware/`scrape` condivisi, `supports(game)`) e gli adapter `CardRushAdapter`
  (tutti i giochi), `HareruyaAdapter` (solo Pokémon), `ToretokuAdapter` (PREZZI One Piece,
  buyback specialista `kaitori-toretoku.jp`, lista unica per gioco), `YuyuteiAdapter` (PREZZI
  solo Yu-Gi-Oh; per OP resta solo CATALOGO via build_catalog,
  per-set `/buy/{opc|ygo}/s/{set}` con cache). Registry `ADAPTERS`. Aggiungere una fonte = aggiungere
  un adapter qui (vedi `docs/ADAPTERS.md`).
- `src/database.py` — `save_price` (status esplicito `confirmed/carried/absent`, carry-forward
  LIMITATO nel tempo `max_carry_days`, flag `is_outlier` vs mediana storica), `fetch_cards_stale`
  (carte ordinate per STALENESS di una fonte: mai-viste prima, poi piu' vecchie → sharding
  notturno di Hareruya che si auto-coordina su piu' run), `export_web` (JSON
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
- `src/build_catalog.py` — HARVESTER dei cataloghi. **Pokémon**: `harvest_pokemon_cardrush`
  pagina la lista buyback CardRush (`/pokemon/buying_prices`, ~120 pagine), tiene SOLO le singole
  (`product_category=シングル`), dedup per `(set, number)` sulla stampa standard, UPSERT su
  `(set, number, variant='')` (controllo esplicito → preserva id+storico delle carte gia' note,
  niente duplicati anche se cambia la rarita') e salva il prezzo CR nella STESSA passata; immagini
  LAZY (URL CDN remoto di default, locale solo con `images_dir`). **OP/YGO**: `harvest` dalla
  pagina-set Yuyu-tei (`/buy/{opc|ygo}/s/{set}`), identita' `(set, number, variant)`, standard vs
  `parallel` dal nome. Idempotenti. Uso: `python src/run.py --harvest-pokemon`;
  `python src/build_catalog.py onepiece OP01 "ROMANCE DAWN"` (`--html` = offline da fixture).
  Test: `tests/test_build_catalog.py`.
- `db/seed_onepiece_sample.sql`, `db/seed_yugioh_sample.sql` — seed di PROVA One Piece (OP01,
  standard + variante parallel) e Yu-Gi-Oh (QCCU-JP002), per il sandbox `tcg_tracker.backup.db`
- `src/run.py` — eseguibile principale. `--harvest-pokemon` (+`--images`) = catalogo Pokémon
  completo + prezzi CR in una passata, poi export ed esci. Altrimenti scraping per-carta sul
  registry `ADAPTERS`: `--set --game --limit --only --sleep`, e per lo sharding notturno di
  Hareruya `--batch N` (con `--only` sceglie le N carte piu' STALE per quella fonte) +
  `--jitter`/`--set-gap` (pausa casuale tra carte / al cambio set = traffico credibile). `HttpClient`
  condiviso; conta i `LayoutError` per l'allarme per-fonte (il segnale "0 prezzi" scatta solo
  con ≥30 tentativi → un lotto di carte che Hareruya non compra non e' un falso allarme).
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
  di `data/*.json`. NIENTE dati inline. RENDER LAZY (per il catalogo ~10k carte): i set sono
  CHIUSI di default, le tile si costruiscono solo per i set aperti (clic / filtro set / ricerca),
  cap `MAX_TILES=400` per render. Toggle VALUTA ¥/€ (`#curBtn`): `YEN()` è currency-aware
  (converte tile/totali/grafici al re-render); tasso JPY→EUR vivo da `api.frankfurter.app`
  (`ensureRate`, una volta) con `FALLBACK_RATE` se l'API è giù; scelta persistita in localStorage.
- `dashboard/app.py` — anteprima LOCALE che serve gli STESSI file statici di Cloudflare
  (`index.html`+`data/`+`images/`), così localhost è identico al sito. Non c'è un secondo
  template. `/api/trigger` in locale è un no-op 501 (esiste solo sul Worker). Per fedeltà
  totale: `npx wrangler dev`.

## Comandi
```bash
python src/init_db.py            # crea/aggiorna DB v1->v2 (storico preservato)
python src/run.py --harvest-pokemon          # catalogo Pokémon COMPLETO da CardRush + prezzi CR
python src/run.py --game pokemon --only hareruya --batch 2500 --jitter 1.5 --set-gap 8  # lotto HR
python src/run.py --limit 3      # test scraping su 3 carte
python src/run.py --set S12A     # un solo set
python src/run.py --game onepiece  # solo One Piece (prezzi: cardrush+toretoku)
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
- **Catalogo Pokémon COMPLETO, OP/YGO PARZIALE**: il DB reale (2026-06-29) ha l'INTERO catalogo
  buyback Pokémon di CardRush — **10.191 singole / 351 set** (incl. il bucket `その他` ~1.889 per
  promo/old-back/sfusi senza pack_code) — via `run.py --harvest-pokemon`. I prezzi CardRush sono
  freschi per tutte; **Hareruya parte solo dalle 263 storiche** e si riempie col cron notturno per
  staleness (qualche notte per coprire tutto). OP/YGO restano PARZIALI: solo `OP01` (43) + `QCCU`
  (200); estendere con `build_catalog.py` set per set. `name_en` Pokémon/OP/YGO assente per le carte
  nuove (solo nome JP): la UI mostra il nome giapponese finché non si traduce.
- **Indice globale mescola i giochi**: il bottone "Andamento" usa `setindex.global` calcolato
  su TUTTI i set (ora anche OP/YGO): aggregato poco sensato cross-gioco. Da rendere per-gioco.
  (I 📈 per-set restano corretti.)
- **UNIQUE di `tcg_card` include `rarity`**: il vincolo è `(set_id, number, language, rarity,
  variant)`. L'identità VERA di una carta è `(set, number, variant)`: cambiare la rarità e
  ri-catalogare con `INSERT OR IGNORE` creava DUPLICATI. `build_catalog.py` ora fa un controllo
  di esistenza esplicito su `(set, number, variant)` (no INSERT OR IGNORE). Lockato da
  `tests/test_build_catalog.py::test_no_duplicati_dopo_cambio_rarita`. Schema da semplificare.
- **best_price = max()**: può catturare una variante/error card invece della standard. Ora il
  flag `is_outlier` (vs mediana storica) la segnala e la vista normalizzata la esclude
  dall'indice, ma la SELEZIONE del best_price è ancora `max()`: migliorabile.
- **One Piece multi-stampa**: stesso numero = più stampe (10-1000x). PRECISIONE MASSIMA:
  `src/op_match.py` riconcilia CardRush↔Toretoku per tier + similarità d'arte; catalogo OP =
  una carta per STAMPA (`build_catalog.rebuild_onepiece_prints`), prezzi agganciati alla stessa
  arte; stampe esclusive di una fonte → single-fonte. Più filtro rumore + confirmed-only (solo OP)
  + GUARD `print_ambiguous` (>4x) come backstop. OP01: 20 coppie, mediana 1.53, max 2.7. Vedi
  `docs/SOURCES_BUYBACK_OP_YGO.md`. (Catalogo OP = solo stampe a 2 fonti + single-fonte ≥¥3.000.)
- **DB committato a ogni run + catalogo grande**: con ~10k carte Pokémon ogni notte si
  aggiungono ~10k righe prezzo CR + i lotti Hareruya → `tcg_tracker.db` cresce in fretta e gonfia
  la history git. Da affrontare in Fase 5 (es. salvare solo i prezzi CAMBIATI, o DB fuori da git).
- **buylist.json grande (~4.3 MB)**: il freeze al load è RISOLTO (render lazy + file snellito da
  ~8MB a ~4.3MB, vedi `dashboard/index.html`). Resta un fetch da qualche MB: se servisse ancora
  più leggero, prossimo passo = split per-set / per-gioco o catalogo+dettaglio on-demand.
- **Rumore nel catalogo Pokémon completo**: 351 "set" includono micro-bucket di CardRush
  (codici di 1 carattere, `その他`, voci `model_number` non-carta come `旧裏`); alcune carte hanno
  rarità `-`/vuota. È il prezzo di "tutte le carte"; eventuale pulizia = filtro AGGIUNTIVO, non
  rimuovere righe (lo storico non si cancella).
- **Casing dei set**: i set Pokémon usano il casing ESATTO di CardRush (`S12a`, `M1L`, `sm12a`…);
  l'harvest fa match esatto su `set_code` (nessuna collisione riscontrata col catalogo curato).
  `full_name` mescola ancora JP/EN e a volte ripete il set.

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
      e prezzi scrapati live (`run.py --game`). RARITÀ + IMMAGINI HI-RES da CardRush
      (`build_catalog.py --images`/`--rarity` → `enrich_from_cardrush`, una fetch per carta dà
      rarità + `ocha_product.image_source` ~564x800, come i Pokémon; Yuyu-tei dà solo 100x140).
      Rarità normalizzata in sigle corte (OP L/SR/SEC/UC/C +`/P`, YGO QCSE). One Piece: standard
      + variante parallel. Catalogo (numeri/nomi) da Yuyu-tei via `harvest`.
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
      IMMAGINI OP/YGO: scaricate da Yuyu-tei in `dashboard/images/` (43 OP + 200 YGO = 243),
      colonna `tcg_card.image_url` + campo `image` nel buylist; la UI usa `c.image` se presente,
      altrimenti il path legacy `.webp` (Pokémon). Harvest con `build_catalog.py … --images`.
      SCALA (catalogo Pokémon ~10k): render LAZY (set chiusi di default, tile on-demand, cap 400)
      + buylist.json snellito → niente freeze al load. VALUTA: toggle ¥/€ con conversione
      automatica (tasso live Frankfurter + fallback, persistito in localStorage).
      ⚠️ Resta: tradurre i nomi OP/YGO+Pokémon nuovi (ora solo JP), indice "Andamento" per-gioco,
      consumo di `movers.json`.
- [~] Fase 5 — scala / ops (in corso)
      ✅ CATALOGO POKÉMON COMPLETO (2026-06-29): `harvest_pokemon_cardrush` prende TUTTE le singole
      buyback da CardRush (10.191 carte / 351 set) — niente più sottoinsieme curato dall'Excel.
      Catalogo+prezzi CR in UNA scansione paginata; immagini LAZY (URL CDN remoto, no git bloat);
      le 263 storiche preservate (UPSERT id-stable, storico intatto, 0 duplicati). Cron NOTTURNO
      multi-trigger (`scrape.yml`): 1° trigger = harvest CR completo + OP/YGO; trigger seguenti =
      lotti Hareruya per STALENESS (`fetch_cards_stale` + `--batch`), traffico spalmato/jitter per
      restare sotto il limite di 6h e credibile. Test offline in `tests/test_build_catalog.py`.
      ⚠️ Resta: DB che cresce in fretta (vedi Trappole → prezzi solo-se-cambiati / DB fuori git);
      pulizia rumore catalogo (`その他`/micro-set); estendere idea catalogo-completo a OP/YGO.

Non aggiungere giochi prima dello schema multi-gioco (Fase 1).
