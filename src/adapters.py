"""
adapters.py - Astrazione delle fonti buyback come SourceAdapter intercambiabili.

Ogni fonte (CardRush, Hareruya, e in futuro fonti One Piece / Yu-Gi-Oh) implementa
la stessa interfaccia, cosi' run.py cicla su un REGISTRY invece di chiamare funzioni
hard-coded. Si appoggia al livello basso testabile di scrapers.py (HttpClient,
parse_*, LayoutError): qui sopra c'e' solo orchestrazione + normalizzazione in Offer.

Interfaccia (vedi docs/ADAPTERS.md per scriverne una nuova):
    build_query(card) -> Query           costruisce URL + criteri di match
    fetch(query, client) -> str          scarica il grezzo (usa HttpClient)
    parse(raw, query) -> list[Offer]     grezzo -> offerte NORMALIZZATE e filtrate
  + select(offers) -> Offer | None       scelta condivisa (standard, poi max)
  + scrape(card, client) -> Offer | None orchestra i 4 passi (lo chiama run.py)

Offer e' normalizzata e indipendente dalla fonte: (price, currency, condition,
variant, in_stock). variant='' = carta standard; le varianti (error card, ecc.)
hanno variant non vuoto e sono preferite solo se non c'e' la standard.

Convenzioni di errore (come scrapers.py):
  - errore di RETE (dopo i retry)  -> scrape() ritorna None (transitorio);
  - struttura della pagina cambiata -> LayoutError propagata (run.py la conta).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import urllib.parse as urlparse
import requests

import scrapers as sc


# ----------------------------------------------------------------------
# Tipi normalizzati
# ----------------------------------------------------------------------
@dataclass
class Offer:
    """Una singola offerta di acquisto, normalizzata e indipendente dalla fonte."""
    price: int                       # buying price grezzo (valuta in `currency`)
    currency: str = "JPY"
    condition: str = "NM"            # condizione (default NM: storicamente non distinta)
    variant: str = ""                # '' = standard; altrimenti chiave variante
    in_stock: bool = True


@dataclass
class Query:
    """Cosa scaricare (url) e con quali criteri filtrare gli item della carta."""
    url: str
    match: dict = field(default_factory=dict)


def _field(card, key, default=None):
    """Legge un campo della carta sia da dict sia da sqlite3.Row (niente .get())."""
    try:
        v = card[key]
    except (KeyError, IndexError):
        return default
    return v if v is not None else default


# ----------------------------------------------------------------------
# Interfaccia
# ----------------------------------------------------------------------
class SourceAdapter(ABC):
    source_code: str = ""            # es. 'cardrush' (= tcg_source.source_code)
    display_name: str = ""

    @abstractmethod
    def build_query(self, card) -> Query:
        """Dalla carta (riga di fetch_cards) costruisce URL + criteri di match."""

    @abstractmethod
    def fetch(self, query: Query, client: "sc.HttpClient") -> str:
        """Scarica il grezzo (HTML/JSON) della query. Puo' sollevare RequestException."""

    @abstractmethod
    def parse(self, raw: str, query: Query) -> list:
        """Grezzo -> lista di Offer NORMALIZZATE e gia' filtrate sulla carta.
        Solleva sc.LayoutError se la struttura attesa non e' riconoscibile."""

    # --- comportamento condiviso -------------------------------------
    def select(self, offers: list):
        """Sceglie l'offerta finale: preferisci la STANDARD (variant==''), poi il
        prezzo piu' alto. Le varianti si usano solo se non c'e' nessuna standard."""
        if not offers:
            return None
        standard = [o for o in offers if not o.variant]
        pool = standard or offers
        return max(pool, key=lambda o: o.price)

    def scrape(self, card, client: "sc.HttpClient | None" = None):
        """Orchestra build_query -> fetch -> parse -> select. Ritorna Offer|None.
        Errore di rete -> None. LayoutError -> propagata (la gestisce run.py)."""
        client = client or sc._default_client()
        q = self.build_query(card)
        if not q or not q.url:
            return None
        try:
            raw = self.fetch(q, client)
        except requests.RequestException as e:
            print(f"  [{self.source_code}] errore rete: {e}")
            return None
        offers = self.parse(raw, q)          # puo' sollevare LayoutError
        return self.select(offers)


# ----------------------------------------------------------------------
# CardRush
# ----------------------------------------------------------------------
class CardRushAdapter(SourceAdapter):
    source_code = "cardrush"
    display_name = "CardRush"

    def build_query(self, card) -> Query:
        url = _field(card, "cardrush_url", "")
        qs = urlparse.parse_qs(urlparse.urlparse(url).query)
        return Query(url=url, match={
            "model": (qs.get("model_number") or [""])[0].strip(),
            "pack":  (qs.get("pack_code") or [""])[0].strip(),
        })

    def fetch(self, query: Query, client) -> str:
        return client.get(query.url).text

    def parse(self, raw: str, query: Query) -> list:
        items = sc.parse_cardrush(raw)        # puo' sollevare LayoutError
        want_model = query.match.get("model", "")
        want_pack = query.match.get("pack", "")
        offers = []
        for it in items:
            if not isinstance(it, dict):
                continue
            amt = it.get("amount")
            if amt is None:
                continue
            model = str(it.get("model_number", ""))
            pack = str(it.get("pack_code", ""))
            # model_number puo' essere "262" o "262/172": confronta anche il prefisso
            if want_model and not (model == want_model or model.split("/")[0] == want_model):
                continue
            if want_pack and pack and pack.lower() != want_pack.lower():
                continue
            try:
                price = int(float(amt))
            except (TypeError, ValueError):
                continue
            variant = (it.get("extra_difference") or "").strip()
            offers.append(Offer(price=price, variant=variant))
        return offers


# ----------------------------------------------------------------------
# Hareruya (hare2buy.com)
# ----------------------------------------------------------------------
class HareruyaAdapter(SourceAdapter):
    source_code = "hareruya"
    display_name = "Hareruya"

    def build_query(self, card) -> Query:
        model = _field(card, "model_number", "")
        full = (sc._collector_number(_field(card, "card_code", ""))
                or sc._collector_number(model))
        query = full or model
        if not query:
            return Query(url="", match={})
        url = sc.HARERUYA_SEARCH.format(q=requests.utils.quote(query))
        return Query(url=url, match={"full": full, "pack": _field(card, "pack_code")})

    def fetch(self, query: Query, client) -> str:
        return client.get(query.url).text

    def parse(self, raw: str, query: Query) -> list:
        items = sc.parse_hareruya(raw)        # puo' sollevare LayoutError
        full = query.match.get("full")
        pack = query.match.get("pack")
        target_num = full.split("/")[0].lstrip("0") if full else None
        offers = []
        for it in items:
            name = it.get("name", "")
            if target_num is not None:
                cm = sc._COLLECTOR_RE.search(name)
                if not cm or cm.group(1).lstrip("0") != target_num:
                    continue
                if pack:
                    pm = sc._PACK_RE.search(name)
                    if pm and pm.group(1).lower() != pack.lower():
                        continue
            p = it.get("price")
            if p:
                offers.append(Offer(price=p))
        return offers


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------
ADAPTERS = [CardRushAdapter(), HareruyaAdapter()]


def get_adapters(only: str = None):
    """Adapter del registry, eventualmente filtrati per source_code (flag --only)."""
    if only:
        return [a for a in ADAPTERS if a.source_code == only]
    return list(ADAPTERS)
