# SOURCES — fonti buyback/prezzo per One Piece e Yu-Gi-Oh (ricognizione)

> Ricognizione verificata fetchando le pagine reali e i `robots.txt` (giugno 2026).
> Solo analisi: nessun codice scritto, nessuna fonte ancora integrata.
> **Buyback (買取)** = quanto il negozio *paga* per ricomprare la carta (il dato del
> prodotto). **Market** = prezzo di vendita/mercato (solo fallback, mai spacciato per buyback).

---

## TL;DR — le due decisioni che contano

1. **CardRush copre già One Piece e Yu-Gi-Oh** con la **stessa struttura Next.js** del Pokémon
   (`/onepiece/buying_prices`, `/yugioh/buying_prices`). ⇒ Si riusa l'adapter CardRush cambiando
   **solo il segmento di categoria** del path. (Spot-check da fare: confermare che lo
   `__NEXT_DATA__` esponga la stessa chiave `buyingPrices` — vedi nota sotto.)
2. **Hareruya NON copre One Piece né Yu-Gi-Oh.** Il gruppo 晴れる屋 splitta per brand:
   `hareruyamtg.com` = Magic, `hare2buy.com` (晴れる屋2) = **solo Pokémon**, `hareruya3.com` =
   Duel Masters. ⇒ Il confronto a due fonti **CardRush vs Hareruya esiste solo per Pokémon**.
   Per OP/YGO serve una **seconda fonte diversa** per mantenere il "buyback comparato" (che è il
   vantaggio difendibile del progetto). Candidata migliore: **Yuyu-tei** (HTML statico, pulito).

⇒ Modello consigliato per i nuovi giochi: **CardRush (riuso) + Yuyu-tei (nuovo adapter)** come
coppia primaria, con **Toretoku** come terzo comparatore opzionale.

---

## Tabella: gioco → fonte → tipo accesso → dato → difficoltà

| Gioco | Fonte | URL (verificato) | Tipo accesso | Dato | Difficoltà |
|---|---|---|---|---|---|
| **One Piece** | **CardRush** | `cardrush.media/onepiece/buying_prices` | Scraping — Next.js `__NEXT_DATA__` (riuso adapter) | **Buyback** | Media (riuso codice) |
| One Piece | **Yuyu-tei** | `yuyu-tei.jp/buy/opc/s/{set}` (es. `/op01`, `/op09`) | Scraping — HTML statico server-rendered | **Buyback** | **Facile** |
| One Piece | **Toretoku** | `kaitori-toretoku.jp/buypricelist/onepiece` | Scraping — HTML statico (WordPress) | **Buyback** | Facile–media |
| One Piece | magi | `magi.camp` (news shop ufficiale) | Scraping — buyback sparso in news + marketplace | Buyback (parziale) + Market | Media–alta |
| One Piece | Dorasuta | `buy.dorasuta.jp/onepiece-cardgame` | Scraping — **403 anti-bot** al fetch | Buyback | **Alta** |
| One Piece | apitcg.com | `docs.apitcg.com` | **API (key richiesta)** — unofficial | **Catalogo** (no prezzi) | Bassa (solo catalogo) |
| One Piece | optcgapi.com | `optcgapi.com` | API senza key — unofficial | Catalogo + **Market EN** (TCGplayer) | Bassa (solo catalogo/market) |
| One Piece | Bandai ufficiale | `en/jp.onepiece-cardgame.com/cardlist` | Solo HTML (no API) | Catalogo | Media |
| **Yu-Gi-Oh** | **CardRush** | `cardrush.media/yugioh/buying_prices` | Scraping — Next.js `__NEXT_DATA__` (riuso adapter) | **Buyback** | Media (riuso codice) |
| Yu-Gi-Oh | **Yuyu-tei** | `yuyu-tei.jp/buy/ygo/s/{set}` | Scraping — HTML statico | **Buyback** | **Facile** |
| Yu-Gi-Oh | **Toretoku** | `kaitori-toretoku.jp/buypricelist/yugioh` | Scraping — HTML statico | **Buyback** | Facile–media |
| Yu-Gi-Oh | **YGOPRODeck** | `db.ygoprodeck.com/api/v7/` | **API senza key** — unofficial, mantenuta | **Catalogo** (+ market EN) | Bassa (solo catalogo) |
| Yu-Gi-Oh | YGOResources | `db.ygoresources.com` | API/dump — ID ufficiali Konami | Catalogo (ID JP) | Bassa |
| Yu-Gi-Oh | Konami ufficiale | `db.yugioh-card.com` | Solo HTML (no API) | Catalogo | Media |
| **Entrambi** | TCGplayer API | `developer.tcgplayer.com` | **API CHIUSA a nuovi dev (2026)** | Market + buylist (EN) | N/D (inaccessibile) |
| **Entrambi** | Cardmarket API | `api.cardmarket.com` | API — OAuth + account pro, **non accetta nuove app** | Market (EU) | N/D (inaccessibile) |
| Hareruya | hare2buy | — | — | **NON copre OP/YGO** | — |

---

## Dettaglio per fonte (cosa ho verificato)

### CardRush — `cardrush.media` ✅ buyback OP + YGO, struttura riusabile
- Fetch confermato: `/onepiece/buying_prices` (lista 買取 live, model `OP02-099`/`OP13-118`, rarità
  SR/SEC/L/R, ~100/pagina, 25 pagine) e `/yugioh/buying_prices` (158 pagine, rarità Secret/Ultra…).
- Stessa UI/paginazione/filtri del Pokémon; tutte e tre Next.js. **Identico salvo il path di categoria.**
- ⚠️ **Da confermare prima di cablare**: il `WebFetch` strippa i `<script>`, quindi non ho potuto
  ispezionare direttamente il blob `__NEXT_DATA__` → chiave `buyingPrices`. Spot-check rapido:
  `curl -s https://cardrush.media/onepiece/buying_prices | grep -o '__NEXT_DATA__'` e verificare la
  chiave. Atteso identico al Pokémon.
- **robots.txt**: blocca solo `/api`, `/test`, `/404`, `/users/*`, `/*?fpc=*`. I path
  `/{gioco}/buying_prices` **sono permessi** (l'adapter legge il JSON embedded, non `/api`).

### Hareruya / hare2buy — `hare2buy.com` ❌ niente OP/YGO
- `hare2buy.com/product-list?keyword=OP01-001` → **0 risultati**. Sito = "晴れる屋2", **solo Pokémon**.
- Yu-Gi-Oh e One Piece sono esplicitamente **fuori dal buyback** del gruppo Hareruya.
- Conseguenza di prodotto: per OP/YGO il comparatore a due fonti va ricostruito con una fonte diversa.

### Yuyu-tei — `yuyu-tei.jp` ✅ buyback OP + YGO, la più pulita
- Fetch confermato: One Piece `/buy/opc/s/op01`, `/buy/opc/s/op09` (es. Shanks parallel 1.400円,
  model `OP09-118`); Yu-Gi-Oh `/buy/ygo/s/sale`, `/buy/ygo/s/ultra` (es. `QCCU-JP002` = 100.000円).
- **HTML statico server-rendered**, prezzi come testo (`<strong>2.700 円</strong>`), model number
  inline, URL stabili per set `/buy/{opc|ygo}/s/{set}`. Niente Next.js/JSON/anti-bot/login.
- **robots.txt**: **nessun `Disallow`** (solo crawl-delay per alcuni bot nominati). Path buy aperti.
- **Difficoltà: facile** — è la nuova integrazione a minor rischio.

### Toretoku — `kaitori-toretoku.jp` ✅ buyback OP + YGO
- Fetch confermato: `/buypricelist/onepiece` (es. `OP01-003` L ¥33.500) e `/buypricelist/yugioh`.
- HTML statico (WordPress), immagine+nome+set/model+rarità+yen. `robots.txt` blocca solo `/wp-admin/`.
- **Difficoltà: facile–media.** Buon terzo comparatore.

### magi — `magi.camp` ⚠️ ibrido, marketplace
- Lo **shop ufficiale** magi pubblica liste 買取; ma magi è soprattutto un **marketplace** (prezzi di
  vendita degli utenti, NON buyback). Dato buyback sparso in news/blog, non in un feed strutturato.
- **Secondaria**: rischio di mescolare market e buyback. Difficoltà media–alta.

### Dorasuta — `buy.dorasuta.jp` ⚠️ anti-bot
- Copre buyback OP + YGO, ma il fetcher riceve **HTTP 403** (WAF/UA filtering). Servirebbe browser
  headless. **Difficoltà alta**, da evitare per ora.

---

## API / dataset ufficiali (catalogo e prezzi)

### Catalogo carte (per il seed delle identità canoniche)
- **Yu-Gi-Oh → YGOPRODeck** (`db.ygoprodeck.com/api/v7/`): **gratis, senza key**, catalogo completo
  con **set code + rarità**, 20 req/s. ⚠️ **Solo testo/immagini EN** (niente giapponese) → per
  l'identità JP affiancare **YGOResources** (ID ufficiali Konami). ToS: scaricare e ospitare i dati
  localmente (no hotlinking), uso commerciale non vietato esplicitamente.
- **One Piece → apitcg.com** (catalogo pulito, set code `OP01-001`, copre anche YGO; **richiede key**,
  unofficial, **niente prezzi**) come primario; **optcgapi.com** come cross-check (senza key, catalogo
  + **market EN** da TCGplayer). Entrambe basate sulla **release EN**: per il catalogo JP serve
  comunque scraping del sito Bandai JP.
- **Bandai (One Piece) e Konami (Yu-Gi-Oh)**: **nessuna API pubblica**, solo cardlist HTML.

### Prezzi via API — verdetto onesto
- **Nessuna API fornisce buyback.** TCGplayer (market+buylist) e Cardmarket (market) sono le uniche
  vere API prezzi, ma nel 2026 **entrambe chiuse a nuovi sviluppatori** (TCGplayer partner-only;
  Cardmarket non accetta nuove app, richiede account pro + OAuth). Mercati EN/EU, non JP.
- I relay gratuiti (YGOPRODeck, optcgapi) espongono solo **market EN di TCGplayer** → utile come
  **fallback market**, mai come buyback né come mercato JP.
- **Conclusione**: per il dato di prodotto (buyback JP comparato) **non esiste alternativa allo
  scraping**. Le API servono **solo a seedare il catalogo**.

---

## Vincoli ToS / robots (sintesi)

| Dominio | robots.txt | Note |
|---|---|---|
| cardrush.media | blocca `/api`, `/test`, `/users/*` | `buying_prices` permessi; usare il path-route, non `/api` |
| yuyu-tei.jp | nessun `Disallow` | crawl-delay solo per bot nominati; impostare UA non-bot e ritmo cortese |
| kaitori-toretoku.jp | solo `/wp-admin/` | buypricelist permesso |
| hare2buy.com | blocca per nome GPTBot/Bytespider/ecc. | nessuna regola `*`; non rilevante per OP/YGO (assenti) |
| buy.dorasuta.jp | non leggibile (403) | anti-bot attivo |
| YGOPRODeck | — | obbligo di ospitare dati/immagini localmente, 20 req/s |

⚠️ Ho verificato i **robots.txt**, non il testo formale dei **Terms of Service** di ciascun sito:
prima della messa in produzione di uno scraping va fatto un controllo ToS manuale. Mantenere rate
cortese, UA identificabile non-bot, e preferire API/dataset ufficiali dove esistono (come da CLAUDE.md).

---

## Implicazioni per la roadmap (Fase 2)

- **Riuso CardRush**: l'adapter esistente regge OP/YGO cambiando il path di categoria — costo basso,
  da fare dopo lo spot-check `__NEXT_DATA__`.
- **Nuovo adapter Yuyu-tei**: necessario per avere il *confronto a due fonti* su OP/YGO (Hareruya non
  c'è). HTML statico → adapter semplice, basso rischio. Eventuale terzo: Toretoku.
- **Identità canonica multi-gioco** (già pronta in Fase 1): OP usa `OP09-118`, YGO usa `QCCU-JP002` /
  `108-002`; lo schema v2 (`number`/`language`/`variant`) li regge senza modifiche.
- **Seed catalogo**: YGOPRODeck (YGO) e apitcg/optcgapi (OP) per popolare le carte; attenzione al gap
  **EN-only** delle API (per il JP serve abbinare scraping Bandai/Konami o i nomi JP delle fonti buyback).
- **Decisione aperta da portarti**: quale seconda fonte adottare per OP/YGO (Yuyu-tei consigliata) e se
  tenere il comparatore a 2 o 3 fonti. Non procedo finché non scegli (resta nello scope "prezzi+trend").
