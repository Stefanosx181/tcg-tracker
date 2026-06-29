# One Piece — fonte buyback comparabile a CardRush (indagine giugno 2026)

> Motivo: su One Piece i buy price di **Yuyu-tei** risultano molto piu' bassi di **CardRush**
> (fino a ~10x su alcune carte), rendendo il confronto a due fonti poco affidabile. Indagine
> per trovare una seconda fonte buyback (買取) giapponese davvero comparabile a CardRush.

## Confronto sui prezzi REALI (set OP01, stesse carte)

| Carta | Rarità | CardRush | Yuyu-tei | Toretoku |
|---|---|---:|---:|---:|
| OP01-003 Luffy (parallel) | L | ¥50.000 | ¥35.000 | ¥33.500 |
| OP01-001 Zoro (parallel) | L | ¥30.000 | ¥16.000 | ¥16.400 |
| OP01-016 Nami (parallel) | R/SR | ¥120.000 | ¥13.000 | ¥14.200 |
| OP01-002 Law (parallel) | L | ¥11.000 | ¥7.000 | ¥6.100 |
| OP01-060 Doflamingo (parallel) | L | ¥6.000 | ¥4.000 | ¥3.200 |

(CardRush/Yuyu-tei dal nostro DB; Toretoku fetchato il 2026-06.)

## Due conclusioni che contano

### 1) CardRush è in cima al mercato: nessuno lo "eguaglia" davvero
Le guide JP (oikura, kaitori-value, uridoki, netoff…) **non indicano un negozio che paghi sempre
di più**, anzi ripetono "confronta più negozi". CardRush è un negozio enthusiast noto per buy price
aggressivi: gli altri buyback restano tipicamente **~50-70% di CardRush** sulle carte ben agganciate.
Quindi "una fonte alta come CardRush" in pratica **non esiste**: che CardRush risulti il migliore è
NORMALE — ed è proprio il dato di valore del progetto ("CardRush conviene davvero?").

### 2) I "10x" sono soprattutto un BUG DI MATCHING, non la fonte
Lo stesso numero carta ha **più stampe** con prezzi diversissimi. Esempio OP01-120 シャンクス:
- CardRush **¥650.000** (刻印なし) · Yuyu-tei **¥200** (una stampa economica) · Toretoku **¥3.000** (SEC pirate-flag)

Sono **tre carte fisiche diverse** con lo stesso numero. Noi agganciamo per `(numero, variante=parallel)`
e prendiamo il `max` per fonte → fonti diverse possono prendere stampe diverse → confronto falsato.
È la "disambiguazione fine rarità/stampa" già segnalata in `CLAUDE.md`. **Va risolta a prescindere
dalla fonte**: è la causa principale dei gap assurdi che si vedono sulle chase card.

## Candidati valutati

| Fonte | Buyback OP? | Accesso | Prezzi vs CardRush | Note |
|---|---|---|---|---|
| **CardRush** | ✅ | Next.js JSON (già integrato) | — (riferimento) | Top di mercato |
| **Toretoku** (`kaitori-toretoku.jp`) | ✅ specialista 買取 | HTML statico, prezzi+codice in chiaro | ~simile a Yuyu-tei sulle mid; **alto sulle chase** (es. Roger OP09-118 ¥538.800) | Distingue le STAMPE (Pirate-Flag/Manga/SP) → aiuta la disambiguazione. ⚠️ niente URL per-set: pagina unica ~300+ carte da filtrare per codice |
| **Yuyu-tei** (attuale) | ✅ | HTML statico per-set | ~50-70% | Per-set comodo, ma matching grezzo → falsi 10x |
| **Suruga-ya** | ✅ | HTML, buy price online | tipicamente più basso | Retailer generalista, non enthusiast |
| **magi** | parziale | marketplace (prezzi di VENDITA) | n/a | Rischio di mescolare market e buyback |
| **Hareruya/hare2buy** | ❌ | — | — | Copre solo Pokémon |
| **Dorasuta** | ✅ | **403 anti-bot** | — | Serve browser headless, da evitare |

## Raccomandazione

1. **Priorità: risolvere la disambiguazione delle stampe** (OP01-120 = più carte). Senza questo,
   *qualsiasi* seconda fonte darà gap assurdi sulle chase card. È il vero fix.
2. **Sostituire Yuyu-tei con Toretoku** come seconda fonte One Piece: è un buyback specialista, dati
   in chiaro, distingue le stampe (aiuta il punto 1) e paga alto sulle chase. Costo: un nuovo
   `ToretokuAdapter`; siccome non ha URL per-set, si scarica la lista OP completa una volta e si
   filtra per codice (poche richieste).
3. Aspettativa realistica: CardRush resterà spesso il più alto. Va bene: il confronto serve a
   mostrare *di quanto* CardRush batte gli altri, non a trovare chi lo pareggia.

## Yu-Gi-Oh — verifica (set QCCU): Yuyu-tei VA BENE, non cambiare

Stesso controllo su Yu-Gi-Oh (set QCCU, 199 carte confrontate, prezzo d'acquisto):

| Carta | CardRush | Yuyu-tei | Toretoku |
|---|---:|---:|---:|
| QCCU-JP002 Black Magician Girl | ¥150.000 | **¥170.000** | ¥81.400 |
| QCCU-JP001 Black Magician | ¥11.000 | **¥12.000** | ¥1.500 (Ultimate!) |

- **CardRush vs Yuyu-tei: ratio mediana 1.3** (media 1.6); su molte carte Yuyu-tei paga *uguale o di più*.
  Yuyu-tei **insegue** CardRush → affidabile come seconda fonte YGO.
- **Toretoku peggiora**: su QCCU-JP001 mostra ¥1.500 (stampa **Ultimate**), non la Quarter Century
  Secret da ¥11-12k → introdurrebbe gli stessi mismatch multi-stampa che vogliamo evitare.
- Perché YGO funziona e OP no: QCCU ha **una stampa per numero** → niente ambiguità. (⚠️ I set YGO
  normali con più rarità per carta avrebbero lo stesso problema di OP: rivedere quando si aggiungono.)

**Decisione**: cambiare fonte **solo per One Piece** (→ Toretoku). Per **Yu-Gi-Oh tenere Yuyu-tei**.

## Matching One Piece — implementato (tier + confirmed-only + guard)

Lo stesso numero ha piu' STAMPE con prezzi 10-1000x diversi. Soluzione a strati:
1. **Tier** (base/parallel/super) dalla rarita' CardRush (`/P`,`/SP`) + marker `パラレル` in extra;
   il confronto tra fonti avviene PER TIER. Filtro **rumore** = solo special non-grezzi
   (serial/sigillati/esteri/promo); NON si filtra `illust:`/sfondi (arte legittima).
2. **Confirmed-only (solo OP)** in `export_web`: si mostrano solo i prezzi appena confermati →
   un tier senza match pulito non resta su un carry-forward vecchio (niente ¥650k fantasma).
3. **Guard 'stampa ambigua'**: se due fonti divergono >4x → `print_ambiguous` (la UI lo segnala),
   niente best/ratio fuorviante. Copre la coda irriducibile (arti esclusive di una fonte, es.
   `illust:Studio Vigor` solo su CardRush).

4. **PRECISIONE MASSIMA — match per-STAMPA** (`src/op_match.py` + `build_catalog.rebuild_onepiece_prints`):
   per ogni numero si RICONCILIANO le inserzioni CardRush↔Toretoku dentro ogni tier, accoppiando
   per SIMILARITA' dei token d'arte (`海賊旗背景`↔`海賊旗背景`, Jaccard; greedy globale sui pair piu'
   simili). Il catalogo OP diventa **una carta per STAMPA** (es. `OP01-016 (漫画絵/漫画背景)`), coi
   prezzi gia' agganciati alla stessa arte. Le stampe esclusive di una fonte (`illust:Studio Vigor`
   solo CardRush, `SP` solo Toretoku) restano single-fonte → niente confronto falso. Test:
   `op_match.reconcile` in `tests/test_onepiece_matching.py`.

Risultato (OP01, per-stampa): **20 coppie confrontate, mediana 1.53, max 2.7** (era 216x),
1 sola ambigua. Il ¥330k `illust:Studio Vigor` e il super ¥210k ora sono correttamente single-fonte.
Nota: si mostrano le stampe a 2 fonti + le single-fonte di valore (≥¥3.000); i comuni
sotto-soglia non vengono cataloghati (precisione, non copertura). Coprire i comuni = aggiungere
una 3ª fonte che li prezza (Toretoku non li pubblica).

## Fonti
- Toretoku One Piece: https://kaitori-toretoku.jp/onepiece , https://kaitori-toretoku.jp/buypricelist/onepiece
- Toretoku Yu-Gi-Oh: https://kaitori-toretoku.jp/buypricelist/yugioh
- CardRush One Piece: https://cardrush.media/onepiece/buying_prices
- Ranking buyback OP: https://oikura.jp/magazine/tips105/ , https://article.kaitori-value.jp/c-one-piece-card-purchase-recommendation/ , https://uridoki.net/tradingcard/kiji_217634/
