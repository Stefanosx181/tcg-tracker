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
   → src/scrapers.py  (CardRush via __NEXT_DATA__ JSON, Hareruya via selettori HTML)
   → src/run.py       (orchestratore: scrape + salva storico + export)
   → src/database.py  (accesso DB, save_price con carry-forward, export_web → JSON)
   → dashboard/data/*.json (buylist.json, history.json, setindex.json)
   → dashboard/ (statica, Cloudflare Pages)
GitHub Actions (.github/workflows/scrape.yml, cron settimanale) → commit DB+JSON
Cloudflare Worker (worker.js) → auth (Access JWT) + POST /api/trigger
```

## File chiave
- `src/scrapers.py` — scraping a 3 livelli testabili: `fetch` (`HttpClient`: timeout,
  retry+backoff, User-Agent, rate-limit) → `parse_cardrush`/`parse_hareruya` (HTML/JSON
  grezzo → lista, offline) → `pick_cardrush`/`pick_hareruya` (filtro + scelta prezzo).
  `LayoutError` = struttura pagina cambiata (≠ "0 risultati"). Selettori in `HARERUYA_SELECTORS`.
- `src/database.py` — `save_price` (carry-forward), `export_web` (genera i JSON + indice set)
- `src/run.py` — eseguibile principale, flag `--set --limit --only --sleep`; usa un solo
  `HttpClient` condiviso e conta i `LayoutError` per l'allarme rottura per-fonte.
- `src/init_db.py` — crea il DB (idempotente; `--force` ricrea da zero = cancella storico)
- `db/schema_sqlite.sql` — schema attuale (Pokémon-specifico)
- `tests/test_scrapers.py` — test pytest offline; `tests/fixtures/` = pagine reali CR+HR
- `dashboard/dashboard.html` — dashboard (ATTENZIONE: dati inline stale, vedi sotto)

## Comandi
```bash
python src/init_db.py            # crea DB se manca (storico preservato)
python src/run.py --limit 3      # test scraping su 3 carte
python src/run.py --set S12A     # un solo set
python src/run.py --only cardrush
pytest                           # test scraper offline (usa tests/fixtures/)
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
- **Dashboard a doppia fonte**: `dashboard/dashboard.html` ha i dati INLINE (`const DATA=[…]`,
  snapshot stale) E separatamente in `dashboard/data/buylist.json`. `history.json` e le
  immagini `.webp` esistono ma NON sono usate. Va unificato su un'unica fonte via fetch.
- **Carry-forward** in `save_price`: riusa l'ultimo prezzo con `in_stock=0`, mascherando carte
  delisted e inquinando l'indice di set. Da rendere esplicito e limitato nel tempo.
- **best_price = max()**: può catturare una variante/error card invece della standard.
- **Schema Pokémon-specifico**: `pack_code`/`model_number`/`card_code` ('114/083') non reggono
  One Piece (OP01-001) né Yu-Gi-Oh. Serve dimensione `game` + identità canonica prima di
  aggiungere giochi.
- **DB committato a ogni run**: gonfia la history git nel tempo.
- **Casing incoerente** nei dati: `S12a` vs `SV1V`; `full_name` mescola JP/EN e ripete il set.

## Roadmap (riferimento)
Il piano completo dei prompt per fase è in `PROMPT_PLAYBOOK_CLAUDECODE.md`. Ordine rigido,
con stato (aggiornalo a fine fase):
- [x] Fase 0 — scraper robusti e testabili (3 livelli fetch/parse/pick, `HttpClient` con
      retry+backoff+rate-limit, `LayoutError` + allarme per-fonte, test pytest offline su fixtures)
- [ ] Fase 1 — schema multi-gioco + migrazione
- [ ] Fase 2 — One Piece, Yu-Gi-Oh
- [ ] Fase 3 — intelligence prezzi
- [ ] Fase 4 — UX
- [ ] Fase 5 — scala / ops

Non aggiungere giochi prima dello schema multi-gioco (Fase 1).
