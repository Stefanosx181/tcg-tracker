"""
scrapers.py - Recupero buying price dai due siti, in 3 livelli separati e testabili.

Architettura (ogni livello e' isolato per poterlo testare offline):

    fetch  -> HttpClient.get()         rete: timeout, retry+backoff, User-Agent, rate-limit
    parse  -> parse_cardrush(text)     HTML/JSON grezzo -> lista di dict (NESSUNA rete)
              parse_hareruya(html)
    pick   -> pick_cardrush(items,..)  filtro model/pack + standard vs varianti -> (prezzo, stock)
              pick_hareruya(items,..)

Le funzioni pubbliche scrape_cardrush()/scrape_hareruya() restano invariate nella firma
e nel comportamento: sono solo wrapper su fetch+parse+pick.

Note sulle fonti (verificate su fixture reali, vedi tests/fixtures/):
  cardrush : app Next.js. I dati sono nello <script id="__NEXT_DATA__"> in
             props.pageProps.buyingPrices (lista di dict con 'amount',
             'model_number' tipo '262/172', 'pack_code', 'extra_difference').
             Mantiene anche il vecchio path JSON puro per retro-compatibilita'.
  hareruya : hare2buy.com e' il braccio BUYBACK (買取) di Hareruya: il prezzo
             mostrato (.selling_price/.price) e' l'OFFERTA DI ACQUISTO, non il
             prezzo di vendita (nome del selettore fuorviante, valore corretto).
             Ricerca per numero di collezione completo (es. '262/172'); i nomi
             prodotto hanno forma  アルセウスVSTAR(UR){無}〈262/172〉[S12a][EX00944].

LayoutError = la PAGINA c'e' ma la STRUTTURA attesa non c'e' piu' (es. sparito
__NEXT_DATA__, spariti i contenitori prodotto): segnala un cambio di layout, da
distinguere dal caso "pagina valida ma 0 risultati" (carta semplicemente assente).
"""
import re
import json
import time
import urllib.parse as urlparse
import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# Costanti di rete
# ----------------------------------------------------------------------
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "ja,en;q=0.8",
}
TIMEOUT = 20
RETRIES = 3            # tentativi totali su errori transitori (5xx/429/timeout/rete)
BACKOFF = 1.0          # secondi base del backoff esponenziale: BACKOFF * 2**tentativo
RATE_LIMIT = 1.0       # pausa minima tra una richiesta e la successiva (cortesia)


class LayoutError(Exception):
    """La pagina e' raggiungibile ma non ha la struttura attesa (layout cambiato)."""


# ----------------------------------------------------------------------
# Livello FETCH: client HTTP centralizzato (timeout, retry, UA, rate-limit)
# ----------------------------------------------------------------------
class HttpClient:
    """Client HTTP riusabile. Centralizza cio' che prima era sparso:
    User-Agent/headers, timeout, retry con backoff esponenziale, e il
    rate-limiting di cortesia (prima fatto da polite_sleep in run.py).
    """

    # status che vale la pena ritentare (errori lato server / rate-limit)
    _RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, timeout=TIMEOUT, retries=RETRIES, backoff=BACKOFF,
                 rate_limit=RATE_LIMIT, headers=None, session=None, sleep=time.sleep):
        self.timeout = timeout
        self.retries = max(1, retries)
        self.backoff = backoff
        self.rate_limit = rate_limit
        self.headers = headers or HEADERS
        self.session = session or requests.Session()
        self._sleep = sleep            # iniettabile nei test (niente attese vere)
        self._primed = False           # la prima richiesta non aspetta il rate-limit

    def get(self, url):
        """Ritorna una requests.Response con status 2xx, oppure solleva
        requests.RequestException dopo aver esaurito i tentativi."""
        if self._primed and self.rate_limit:
            self._sleep(self.rate_limit)
        self._primed = True

        last_exc = None
        for attempt in range(self.retries):
            if attempt:
                self._sleep(self.backoff * (2 ** (attempt - 1)))
            try:
                r = self.session.get(url, headers=self.headers, timeout=self.timeout)
            except requests.RequestException as e:
                last_exc = e
                continue
            if r.status_code in self._RETRYABLE_STATUS:
                last_exc = requests.HTTPError(f"status {r.status_code}", response=r)
                continue
            r.raise_for_status()       # 4xx non-retryable -> eccezione
            return r
        raise last_exc if last_exc else requests.RequestException("richiesta fallita")


_DEFAULT_CLIENT = None


def _default_client():
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = HttpClient()
    return _DEFAULT_CLIENT


# ----------------------------------------------------------------------
# CARDRUSH - parse (offline) + pick
# ----------------------------------------------------------------------
def parse_cardrush(text: str) -> list:
    """HTML/JSON grezzo di cardrush -> lista di item dict.

    Gestisce due formati:
      - JSON puro (vecchio endpoint)    -> lista o {buyingPrices|data|...}
      - HTML Next.js (endpoint attuale) -> <script id="__NEXT_DATA__">
                                           props.pageProps.buyingPrices

    Ritorna [] se la pagina e' valida ma senza risultati (carta assente).
    Solleva LayoutError se la struttura attesa non e' riconoscibile.
    """
    text = text or ""

    # 1) JSON puro (retro-compatibilita' vecchio endpoint)
    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            data = json.loads(text)
        except ValueError:
            pass
        else:
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("buyingPrices", "data", "buying_prices", "results"):
                    if key in data:
                        return data[key] or []
                raise LayoutError("JSON cardrush senza chiave prezzi nota")

    # 2) HTML Next.js: i dati sono nello script __NEXT_DATA__
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', text, re.S)
    if not m:
        raise LayoutError("cardrush: __NEXT_DATA__ non trovato (layout cambiato?)")
    try:
        nd = json.loads(m.group(1))
    except ValueError as e:
        raise LayoutError(f"cardrush: __NEXT_DATA__ non e' JSON valido: {e}")
    page = nd.get("props", {}).get("pageProps")
    if not isinstance(page, dict):
        raise LayoutError("cardrush: props.pageProps assente (layout cambiato?)")
    for key in ("buyingPrices", "data"):
        if key in page:
            return page[key] or []
    raise LayoutError("cardrush: pageProps senza 'buyingPrices' (layout cambiato?)")


def cardrush_last_page(text: str):
    """Numero di pagine totali della lista buyback CardRush (pageProps.lastPage).

    Serve all'harvester del catalogo Pokemon (build_catalog) per sapere quante
    pagine paginare. Ritorna int oppure None se non e' una pagina-lista Next.js
    riconoscibile (in tal caso il chiamante puo' ripiegare su una pagina sola)."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', text or "", re.S)
    if not m:
        return None
    try:
        page = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
    except ValueError:
        return None
    lp = page.get("lastPage")
    try:
        return int(lp) if lp is not None else None
    except (TypeError, ValueError):
        return None


def pick_cardrush(items: list, want_model: str = "", want_pack: str = ""):
    """Da una lista di item cardrush sceglie il buying price della carta STANDARD.

    Filtra per model_number/pack_code (il server di solito filtra gia', ma ci
    tuteliamo). Distingue la carta standard dalle varianti (errore di stampa,
    ecc.) marcate con 'extra_difference' non vuoto e di solito piu' costose:
    preferiamo la standard, le varianti solo se non c'e' nessuna standard.

    Ritorna (buying_price:int|None, in_stock:bool).
    """
    want_model = (want_model or "").strip()
    want_pack = (want_pack or "").strip()
    standard, variant = [], []
    for it in items:
        if not isinstance(it, dict):
            continue
        amt = it.get("amount")
        if amt is None:
            continue
        model = str(it.get("model_number", ""))
        pack = str(it.get("pack_code", ""))
        # model_number puo' essere "262" oppure "262/172": confronta anche il prefisso
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

    chosen = standard or variant
    if not chosen:
        return None, False
    return max(chosen), True   # offerta di acquisto piu' alta della carta standard


def scrape_cardrush(url: str, client: "HttpClient | None" = None):
    """Ritorna (buying_price:int|None, in_stock:bool). url = colonna E dell'Excel.

    Errore di rete (dopo i retry) -> (None, False).
    Cambio di layout -> LayoutError (propagata, cosi' run.py la conta a parte).
    """
    if not url:
        return None, False
    client = client or _default_client()
    try:
        r = client.get(url)
    except requests.RequestException as e:
        print(f"  [cardrush] errore rete: {e}")
        return None, False

    items = parse_cardrush(r.text)     # puo' sollevare LayoutError

    qs = urlparse.parse_qs(urlparse.urlparse(url).query)
    want_model = (qs.get("model_number") or [""])[0].strip()
    want_pack = (qs.get("pack_code") or [""])[0].strip()
    return pick_cardrush(items, want_model, want_pack)


# ----------------------------------------------------------------------
# HARERUYA (hare2buy.com) - parse (offline) + pick
# ----------------------------------------------------------------------
HARERUYA_SEARCH = "https://www.hare2buy.com/product-list?keyword={q}"
HARERUYA_SELECTORS = {
    "item":   ".list_item_cell, [class*=list_item_]",   # contenitore prodotto
    "name":   ".goods_name, .item_name",                # nome carta
    "price":  ".selling_price, .price",                 # cella prezzo (= buyback)
    # anchor strutturali della pagina-risultati: se MANCANO tutti, il layout e'
    # cambiato; se ci sono ma senza item, e' una ricerca a 0 risultati.
    "anchor": ".itemlist, .itemlist_contents, .item_count, .all_items",
}
# numero di collezione tra parentesi angolari giapponesi o ascii: 〈262/172〉
_COLLECTOR_RE = re.compile(r"[〈<]\s*(\d+)\s*/\s*(\d+)\s*[〉>]")
# tag del set tra parentesi quadre: [S12a], [M4] ...
_PACK_RE = re.compile(r"\[([A-Za-z0-9]+)\]")


def _to_int_price(text: str):
    m = re.search(r"[\d,]+", text or "")
    return int(m.group().replace(",", "")) if m else None


def _collector_number(text: str):
    """Estrae '262/172' da un codice carta (es. 'S12a 262/172' o '262/172')."""
    m = re.search(r"(\d+)\s*/\s*(\d+)", text or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


def parse_hareruya(html: str) -> list:
    """HTML grezzo di hare2buy -> lista di {'name': str, 'price': int|None}.

    Ritorna [] se la pagina-risultati e' valida ma vuota (0 risultati).
    Solleva LayoutError se mancano sia gli item sia gli anchor strutturali
    (= non e' piu' la pagina-risultati che ci aspettiamo).
    """
    soup = BeautifulSoup(html or "", "html.parser")
    cells = soup.select(HARERUYA_SELECTORS["item"])
    if not cells:
        # Nessun item: distinguo "0 risultati" da "layout cambiato" guardando
        # se esiste ancora lo scheletro della pagina-risultati.
        if not soup.select_one(HARERUYA_SELECTORS["anchor"]):
            raise LayoutError("hareruya: nessun item ne' anchor di lista (layout cambiato?)")
        return []

    out = []
    for it in cells:
        name_el = it.select_one(HARERUYA_SELECTORS["name"])
        price_el = it.select_one(HARERUYA_SELECTORS["price"])
        if not (name_el and price_el):
            continue
        out.append({
            "name": name_el.get_text(strip=True),
            "price": _to_int_price(price_el.get_text()),
        })
    return out


def pick_hareruya(items: list, full_number: str = None, pack_code: str = None):
    """Da una lista di {'name','price'} sceglie il buyback della carta giusta.

    Filtra per numero di collezione 〈###/###〉 (esclude il buyback in blocco
    senza numero e le carte omonime di altri set) ed eventualmente per [pack].

    Ritorna (buying_price:int|None, in_stock:bool).
    """
    target_num = full_number.split("/")[0].lstrip("0") if full_number else None
    prices = []
    for it in items:
        name = it.get("name", "")
        if target_num is not None:
            cm = _COLLECTOR_RE.search(name)
            if not cm or cm.group(1).lstrip("0") != target_num:
                continue
            if pack_code:
                pm = _PACK_RE.search(name)
                if pm and pm.group(1).lower() != pack_code.lower():
                    continue
        p = it.get("price")
        if p:
            prices.append(p)
    if not prices:
        return None, False
    return max(prices), True


def scrape_hareruya(card_code: str, pack_code: str = None,
                    model_number: str = None, client: "HttpClient | None" = None):
    """Ritorna (buying_price:int|None, in_stock:bool).

    card_code   : codice completo dell'Excel, es. 'S12a 262/172'.
    pack_code   : sigla del set, es. 'S12a' (disambigua numeri uguali in set diversi).
    model_number: fallback se card_code non contiene un numero ###/###.

    Errore di rete (dopo i retry) -> (None, False).
    Cambio di layout -> LayoutError (propagata).
    """
    full = _collector_number(card_code) or _collector_number(model_number or "")
    query = full or (model_number or "")
    if not query:
        return None, False
    client = client or _default_client()
    url = HARERUYA_SEARCH.format(q=requests.utils.quote(query))
    try:
        r = client.get(url)
    except requests.RequestException as e:
        print(f"  [hareruya] errore rete: {e}")
        return None, False

    items = parse_hareruya(r.text)     # puo' sollevare LayoutError
    return pick_hareruya(items, full, pack_code)


# ----------------------------------------------------------------------
# YUYU-TEI (yuyu-tei.jp) - pagina-set buyback (買取), HTML statico
# ----------------------------------------------------------------------
# La pagina /buy/{seg}/s/{set} elenca tutte le carte del set in blocchi
# .card-product: numero in <span class="... border ...">, nome (con eventuale
# "(パラレル)") in <h4 class="text-primary ...">, prezzo buyback nel primo
# <strong> che contiene "円". Anchor strutturale: .cards-list.
YUYUTEI_SELECTORS = {
    "item":   ".card-product",
    "number": "span.border",
    "name":   "h4.text-primary",
    "anchor": ".cards-list",
}


def parse_yuyutei(html: str) -> list:
    """HTML grezzo di una pagina-set yuyu-tei -> lista di
    {'number','name','price','image'}.

    'image' = URL dell'immagine della carta sul CDN Yuyu-tei (card.yuyu-tei.jp),
    None se assente. [] se la pagina e' valida ma senza prodotti; LayoutError se
    mancano sia i prodotti sia l'anchor di lista (struttura cambiata)."""
    soup = BeautifulSoup(html or "", "html.parser")
    cells = soup.select(YUYUTEI_SELECTORS["item"])
    if not cells:
        if not soup.select_one(YUYUTEI_SELECTORS["anchor"]):
            raise LayoutError("yuyu-tei: nessun .card-product ne' anchor (layout cambiato?)")
        return []

    out = []
    for it in cells:
        num_el = it.select_one(YUYUTEI_SELECTORS["number"])
        name_el = it.select_one(YUYUTEI_SELECTORS["name"])
        if not (num_el and name_el):
            continue
        price = None
        for st in it.select("strong"):
            if "円" in st.get_text():
                price = _to_int_price(st.get_text())
                break
        image = None
        for im in it.select("img"):
            src = im.get("src") or im.get("data-src") or ""
            if src.startswith("https://card.yuyu-tei.jp"):
                image = src
                break
        out.append({
            "number": num_el.get_text(strip=True),
            "name": name_el.get_text(strip=True),
            "price": price,
            "image": image,
        })
    return out


TORETOKU_SELECTORS = {
    "item":  ".item",
    "price": ".item__price .price",   # contiene "買取価格" + "￥33,500"
    "name":  ".item__name",           # "<nome>(stampa) <CODICE> <RARITA'>"
    "image": ".item__image img",
}
# numerazione One Piece su Toretoku: OP/EB/ST/PRB + nn-nnn, oppure promo P-nnn
_OPC_CODE_RE = re.compile(r"\b((?:OP|EB|ST|PRB)\d{2}-\d{3}|P-\d{2,})\b")


def parse_toretoku(html: str) -> list:
    """HTML della lista buyback Toretoku (One Piece) ->
    lista di {'number','name','rarity','price','image'}.

    Il prezzo e' il BUYBACK (買取価格), cioe' quanto Toretoku PAGA. LayoutError se
    manca del tutto la struttura `.item` (pagina cambiata); [] se non ci sono carte
    riconoscibili."""
    soup = BeautifulSoup(html or "", "html.parser")
    items = soup.select(TORETOKU_SELECTORS["item"])
    if not items:
        raise LayoutError("toretoku: nessun .item (layout cambiato?)")
    out = []
    for it in items:
        name_el = it.select_one(TORETOKU_SELECTORS["name"])
        price_el = it.select_one(TORETOKU_SELECTORS["price"])
        if not (name_el and price_el):
            continue
        price = _to_int_price(price_el.get_text())
        if not price:
            continue
        txt = name_el.get_text(" ", strip=True)
        m = _OPC_CODE_RE.search(txt)
        if not m:
            continue
        number = m.group(1)
        after = txt[m.end():].strip()
        rarity = after.split()[0] if after else ""     # token dopo il codice
        name = txt[:m.start()].strip()                 # testo prima del codice
        img_el = it.select_one(TORETOKU_SELECTORS["image"])
        image = (img_el.get("src") or img_el.get("data-src")) if img_el else None
        out.append({"number": number, "name": name, "rarity": rarity,
                    "price": price, "image": image})
    return out


# ----------------------------------------------------------------------
# Stampe One Piece: tier canonico + filtro rumore (solo OP)
# ----------------------------------------------------------------------
# Una stessa carta (numero) ha piu' STAMPE con prezzi diversissimi. Per un
# confronto buyback sensato le riconduciamo a 3 TIER canonici e scartiamo le
# inserzioni "rumore" (serial/sigillati/esteri/illust alternative), che non sono
# la carta grezza standard. Vedi docs/SOURCES_BUYBACK_OP_YGO.md.
PRINT_TIERS = ("base", "parallel", "super")
# SOLO special che NON sono la carta grezza standard: serial/sigillati/esteri/promo.
# NB: 'illust:' (credito illustratore) e gli sfondi (漫画背景 ecc.) NON sono rumore:
# sono arte legittima di stampe normali; filtrarli scartava parallel valide.
_NOISE_TOKENS = ("シリアル", "未開封", "開封品", "中国版", "英語版", "アジア", "Asia",
                 "NOT FOR SALE", "ノーマル仕様")


def is_noise_listing(marker: str) -> bool:
    """Inserzione da SCARTARE nel confronto OP (serial/sigillato/estero/illust)."""
    s = marker or ""
    return any(tok in s for tok in _NOISE_TOKENS)


def print_tier_cardrush(rarity: str, extra: str = "") -> str:
    """Tier di una stampa CardRush combinando rarita' + extra_difference.
    CardRush e' incoerente: a volte la parallel e' nel suffisso rarita' ('/P','/SP'),
    a volte SOLO in extra ('パラレル') con rarita' base. Regola:
      super    = rarita' .../SP
      parallel = rarita' .../P  OPPURE 'パラレル' nell'extra
      base     = altrimenti."""
    r = (rarity or "").upper()
    e = extra or ""
    if r.endswith("/SP"):
        return "super"
    if r.endswith("/P") or "パラレル" in e:
        return "parallel"
    return "base"


# compat: vecchio nome (solo rarita')
def print_tier_from_rarity(rarity: str) -> str:
    return print_tier_cardrush(rarity, "")


def print_tier_from_name(name: str) -> str:
    """Tier dal nome (Toretoku/Yuyu-tei): SP/漫画/スーパー->super, パラレル->parallel."""
    n = name or ""
    if "SP" in n or "漫画" in n or "スーパー" in n:
        return "super"
    if "パラレル" in n:
        return "parallel"
    return "base"


def polite_sleep(sec=1.0):
    """Deprecata: il rate-limiting e' ora in HttpClient. Mantenuta per compat."""
    time.sleep(sec)
