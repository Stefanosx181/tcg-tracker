# Come scrivere un SourceAdapter

Una **fonte buyback** (CardRush, Hareruya, e in futuro fonti One Piece / Yu-Gi-Oh)
è un `SourceAdapter` in [`src/adapters.py`](../src/adapters.py). `src/run.py` cicla
su un **registry** di adapter (`ADAPTERS`): aggiungere una fonte = aggiungere un
adapter al registry, senza toccare `run.py`.

Gli adapter si appoggiano al livello basso testabile di
[`src/scrapers.py`](../src/scrapers.py): `HttpClient` (timeout/retry/backoff/rate-limit),
i `parse_*` grezzo→struttura, e l'eccezione `LayoutError`.

## Il tipo `Offer` (normalizzato, indipendente dalla fonte)

```python
Offer(price: int, currency="JPY", condition="NM", variant="", in_stock=True)
```

- `price` — buying price grezzo nella valuta `currency`.
- `variant` — `""` = carta **standard**; non vuoto = variante (error card, ecc.).
  La selezione preferisce la standard e usa le varianti solo se non c'è una standard.
- `condition` — condizione (default `NM`; valorizzala se la fonte la espone).

`Offer` è ciò che `parse()` produce; `run.py` salva `price` e `in_stock` via
`database.save_price`. Gli altri campi sono già normalizzati per usi futuri.

## L'interfaccia

Sottoclassa `SourceAdapter` e implementa **tre** metodi (gli altri sono ereditati):

```python
class MyShopAdapter(SourceAdapter):
    source_code = "myshop"        # = tcg_source.source_code nel DB
    display_name = "My Shop"

    def build_query(self, card) -> Query:
        # card = riga di database.fetch_cards: pack_code, card_code,
        # model_number, full_name, cardrush_url, hareruya_url.
        # Costruisci l'URL e i criteri di match della carta.
        return Query(url="https://myshop/...", match={"number": card["card_code"]})

    def fetch(self, query, client) -> str:
        # USA il client condiviso: gestisce retry/backoff/rate-limit/UA.
        return client.get(query.url).text

    def parse(self, raw, query) -> list[Offer]:
        # Grezzo -> SOLO le offerte della carta giusta, NORMALIZZATE in Offer.
        # Filtra qui col contesto in query.match.
        # Se la STRUTTURA attesa non c'è più: solleva sc.LayoutError.
        ...
        return [Offer(price=1000)]
```

Metodi **ereditati** (non li riscrivi, salvo necessità):

- `select(offers) -> Offer | None` — preferisci `variant==""`, poi `max(price)`.
- `scrape(card, client) -> Offer | None` — orchestra `build_query → fetch → parse → select`.
  È ciò che chiama `run.py`.

## Convenzioni di errore (importanti)

| Situazione | Cosa fare | Effetto |
|---|---|---|
| Errore di **rete** (dopo i retry) | lascia propagare `requests.RequestException` da `fetch` | `scrape()` ritorna `None` (transitorio) |
| **Struttura** della pagina cambiata (manca lo scaffold atteso) | `raise sc.LayoutError(...)` da `parse` | `run.py` la conta: allarme rottura per-fonte |
| Carta semplicemente **assente** (pagina valida, 0 risultati) | ritorna `[]` da `parse` | nessun prezzo, nessun allarme |

Distinguere "0 risultati" da "layout cambiato" è il punto chiave: cerca un
**anchor strutturale** (un contenitore che esiste anche con 0 risultati) prima di
decidere che il layout è rotto — vedi `parse_hareruya` in `scrapers.py`.

## Registrare l'adapter

Aggiungi un'istanza al registry in `adapters.py`:

```python
ADAPTERS = [CardRushAdapter(), HareruyaAdapter(), MyShopAdapter()]
```

`run.py` lo includerà automaticamente; `--only myshop` lo seleziona da solo.
Inserisci anche la riga in `tcg_source` (lo fa la migrazione/seed) se vuoi i FK puliti.

## Testare offline (obbligatorio)

1. Salva una pagina **reale** della fonte in `tests/fixtures/` (vedi come sono
   stati creati i fixture CardRush/Hareruya).
2. In `tests/` scrivi test che:
   - `build_query(card)` produce l'URL/criteri attesi;
   - `parse(fixture, query)` ritorna gli `Offer` giusti (prezzo, variante);
   - `select(...)` sceglie l'offerta attesa (standard vs variante, max);
   - un input con struttura rotta solleva `LayoutError`.
3. I test devono girare **senza rete** (usa il fixture; per `scrape` inietta un
   client finto, vedi `tests/test_adapters.py`).

## Checklist

- [ ] `source_code` univoco e uguale al valore in `tcg_source`.
- [ ] `parse` filtra sulla carta e normalizza in `Offer`.
- [ ] `LayoutError` solo su struttura cambiata, **non** su 0 risultati.
- [ ] `fetch` usa il `client` condiviso (niente `requests.get` diretto).
- [ ] Aggiunto a `ADAPTERS` + test offline su fixture.
