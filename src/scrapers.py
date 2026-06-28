"""
scrapers.py - Recupero buying price dai due siti.

  cardrush : l'URL salvato nell'Excel (colonna E) puntava a un endpoint che un
             tempo restituiva JSON. Oggi cardrush.media e' una app Next.js che
             rende la pagina in HTML con i dati incorporati nello script
             <script id="__NEXT_DATA__">. Lo scraper estrae da li' la lista
             'buyingPrices' e legge il prezzo piu' alto (campo 'amount') tra i
             prodotti che combaciano per model_number / pack_code.
             (Mantiene anche il vecchio path JSON per retro-compatibilita'.)

  hareruya : (hare2buy.com) non espone JSON pubblico: si fa una ricerca per
             model number e si estrae il prezzo di acquisto dalla pagina HTML.
             I selettori vanno verificati/adeguati alla pagina reale: sono
             centralizzati in HARERUYA_SELECTORS per modifica rapida.
"""
import re
import json
import time
import urllib.parse as urlparse
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "ja,en;q=0.8",
}
TIMEOUT = 20

# ----------------------------------------------------------------------
# CARDRUSH
# ----------------------------------------------------------------------
def _extract_cardrush_items(resp):
    """Normalizza la risposta cardrush in una lista di dict {amount, model_number, ...}.

    Gestisce due formati:
      - JSON puro (vecchio endpoint)               -> lista o {data/buying_prices/...}
      - HTML Next.js (endpoint attuale)            -> <script id="__NEXT_DATA__">
                                                       props.pageProps.buyingPrices
    """
    # 1) tentativo JSON diretto (retro-compatibilita')
    try:
        data = resp.json()
        items = data if isinstance(data, list) else (
            data.get("buyingPrices") or data.get("data")
            or data.get("buying_prices") or data.get("results") or [])
        if items:
            return items
    except (ValueError, AttributeError):
        pass

    # 2) HTML Next.js: i dati sono nello script __NEXT_DATA__
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S)
    if not m:
        return []
    try:
        nd = json.loads(m.group(1))
    except ValueError:
        return []
    page = nd.get("props", {}).get("pageProps", {})
    return page.get("buyingPrices") or page.get("data") or []


def scrape_cardrush(url: str):
    """Ritorna (buying_price:int|None, in_stock:bool). url = colonna E dell'Excel."""
    if not url:
        return None, False
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        print(f"  [cardrush] errore: {e}")
        return None, False

    items = _extract_cardrush_items(r)

    # Filtri attesi dalla query (il server di solito filtra gia', ma ci tuteliamo
    # da risultati di altri set/carte che condividono lo stesso model_number).
    qs = urlparse.parse_qs(urlparse.urlparse(url).query)
    want_model = (qs.get("model_number") or [""])[0].strip()
    want_pack = (qs.get("pack_code") or [""])[0].strip()

    # Raccogliamo i prezzi distinguendo la carta STANDARD dalle varianti
    # (errore di stampa, ecc.): CardRush le marca con 'extra_difference' non
    # vuoto (es. "※表面加工エラー") e spesso costano molto di piu'. Vogliamo il
    # prezzo della carta normale, non della variante.
    standard, variant = [], []
    for it in items:
        if not isinstance(it, dict):
            continue
        amt = it.get("amount")
        if amt is None:
            continue
        model = str(it.get("model_number", ""))
        pack = str(it.get("pack_code", ""))
        # model_number puo' essere "114" oppure "114/083": confronta anche il prefisso
        if want_model and not (model == want_model or model.split("/")[0] == want_model):
            continue
        if want_pack and pack and pack.lower() != want_pack.lower():
            continue
        try:
            price = int(float(amt))
        except (TypeError, ValueError):
            continue
        extra = (it.get("extra_difference") or "").strip()
        (variant if extra else standard).append(price)

    # Preferiamo la carta standard; solo se non ce n'e' nessuna usiamo le varianti.
    chosen = standard or variant
    if not chosen:
        return None, False
    return max(chosen), True   # buying price = offerta di acquisto piu' alta (carta standard)


# ----------------------------------------------------------------------
# HARERUYA (hare2buy.com)
# ----------------------------------------------------------------------
# La ricerca avviene su /product-list col parametro `keyword`. La query va
# fatta col NUMERO DI COLLEZIONE COMPLETO (es. "114/083"): cercare solo "114"
# restituisce centinaia di carte di set diversi. I nomi prodotto hanno forma
#   メガゲッコウガex(SAR){水}〈114/083〉[M4][EX02235]
# quindi si filtra per numero 〈###/###〉 ed eventualmente per pack [M4].
HARERUYA_SEARCH = "https://www.hare2buy.com/product-list?keyword={q}"
HARERUYA_SELECTORS = {
    "item":  ".list_item_cell, [class*=list_item_]",   # contenitore prodotto
    "name":  ".goods_name, .item_name",                # nome carta
    "price": ".selling_price, .price",                 # cella prezzo (buying price)
}
# numero di collezione tra parentesi angolari giapponesi o ascii: 〈114/083〉
_COLLECTOR_RE = re.compile(r"[〈<]\s*(\d+)\s*/\s*(\d+)\s*[〉>]")
# tag del set tra parentesi quadre: [M4], [SV4a] ...
_PACK_RE = re.compile(r"\[([A-Za-z0-9]+)\]")

def _to_int_price(text: str):
    m = re.search(r"[\d,]+", text or "")
    return int(m.group().replace(",", "")) if m else None

def _collector_number(text: str):
    """Estrae '114/083' dal codice carta (es. 'M4 114/083' o '114')."""
    m = re.search(r"(\d+)\s*/\s*(\d+)", text or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None

def scrape_hareruya(card_code: str, pack_code: str | None = None,
                    model_number: str | None = None):
    """Ritorna (buying_price:int|None, in_stock:bool).

    card_code   : codice completo dell'Excel, es. 'M4 114/083' (per la ricerca
                  serve il numero di collezione '114/083').
    pack_code   : sigla del set, es. 'M4' (disambigua numeri uguali in set diversi).
    model_number: fallback se card_code non contiene un numero ###/###.
    """
    full = _collector_number(card_code) or _collector_number(model_number or "")
    query = full or (model_number or "")
    if not query:
        return None, False
    try:
        r = requests.get(HARERUYA_SEARCH.format(q=requests.utils.quote(query)),
                         headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        print(f"  [hareruya] errore: {e}")
        return None, False

    target_num = full.split("/")[0].lstrip("0") if full else None
    soup = BeautifulSoup(r.text, "html.parser")
    prices = []
    for it in soup.select(HARERUYA_SELECTORS["item"]):
        name_el = it.select_one(HARERUYA_SELECTORS["name"])
        price_el = it.select_one(HARERUYA_SELECTORS["price"])
        if not (name_el and price_el):
            continue
        name = name_el.get_text(strip=True)

        # filtra per numero di collezione, cosi' si escludono sia il "buyback in
        # blocco" (senza numero) sia carte omonime di altri set.
        if target_num is not None:
            cm = _COLLECTOR_RE.search(name)
            if not cm or cm.group(1).lstrip("0") != target_num:
                continue
            if pack_code:
                pm = _PACK_RE.search(name)
                if pm and pm.group(1).lower() != pack_code.lower():
                    continue

        p = _to_int_price(price_el.get_text())
        if p:
            prices.append(p)
    if not prices:
        return None, False
    return max(prices), True


def polite_sleep(sec=1.0):
    """Pausa tra le richieste per non sovraccaricare i siti."""
    time.sleep(sec)
