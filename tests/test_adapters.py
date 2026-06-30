# -*- coding: utf-8 -*-
"""
Test offline dei SourceAdapter (CardRush, Hareruya) sulle fixtures reali.
Verificano che gli adapter riproducano il comportamento Pokémon attuale e che
il registry sia quello atteso. Nessuna rete (client finto per scrape()).
"""
import sys
import pathlib
import pytest
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import scrapers as sc       # noqa: E402
import adapters as ad       # noqa: E402

FIX = pathlib.Path(__file__).resolve().parent / "fixtures"
CARDRUSH_HTML = (FIX / "cardrush_262.html").read_text(encoding="utf-8")
HARERUYA_HTML = (FIX / "hareruya_262.html").read_text(encoding="utf-8")

# carta 262/172 (Arceus VSTAR) come in fetch_cards
CARD = {
    "id": 1,
    "pack_code": "S12a",
    "card_code": "S12a 262/172",
    "model_number": "262",
    "full_name": "アルセウスVSTAR",
    "cardrush_url": ("https://cardrush.media/pokemon/buying_prices?"
                     "model_number=262&pack_code=S12a&page=1"),
    "hareruya_url": "https://www.hare2buy.com/product-list?keyword=262/172",
}


class _FakeClient:
    """Client finto: ritorna sempre lo stesso grezzo, senza rete."""
    def __init__(self, raw):
        self.raw = raw
        self.last_url = None

    def get(self, url):
        self.last_url = url
        class _R:  # mimica requests.Response per il solo .text
            pass
        r = _R()
        r.text = self.raw
        return r


# ====================================================================
# Registry
# ====================================================================
def test_registry_sources_and_game_routing():
    codes = [a.source_code for a in ad.ADAPTERS]
    assert codes == ["cardrush", "hareruya", "yuyutei", "toretoku"]
    assert ad.get_adapters("hareruya")[0].source_code == "hareruya"
    # routing per gioco: Pokémon = cardrush+hareruya; One Piece = cardrush+TORETOKU
    # (Yuyu-tei OP dismessa, vedi docs/SOURCES_BUYBACK_OP_YGO.md); Yu-Gi-Oh = cardrush+yuyutei
    assert [a.source_code for a in ad.get_adapters(game="pokemon")] == ["cardrush", "hareruya"]
    assert [a.source_code for a in ad.get_adapters(game="onepiece")] == ["cardrush", "toretoku"]


# ====================================================================
# CardRush adapter
# ====================================================================
def test_cardrush_build_query_extracts_model_and_pack():
    a = ad.CardRushAdapter()
    q = a.build_query(CARD)
    assert q.match["model"] == "262"
    assert q.match["pack"] == "S12a"


def test_cardrush_parse_offers_from_fixture():
    a = ad.CardRushAdapter()
    q = a.build_query(CARD)
    offers = a.parse(CARDRUSH_HTML, q)
    assert offers and all(isinstance(o, ad.Offer) for o in offers)
    assert offers[0].price == 16000
    assert offers[0].currency == "JPY"
    assert offers[0].variant == ""        # standard


def test_cardrush_scrape_fixture_via_fake_client():
    a = ad.CardRushAdapter()
    offer = a.scrape(CARD, _FakeClient(CARDRUSH_HTML))
    assert offer.price == 16000 and offer.in_stock is True


def test_cardrush_select_prefers_standard_over_variant():
    a = ad.CardRushAdapter()
    offers = [ad.Offer(price=99000, variant="※エラー"), ad.Offer(price=16000, variant="")]
    assert a.select(offers).price == 16000


def test_cardrush_select_variant_only_when_no_standard():
    a = ad.CardRushAdapter()
    offers = [ad.Offer(price=99000, variant="err")]
    assert a.select(offers).price == 99000


def test_cardrush_parse_layout_error_propagates():
    a = ad.CardRushAdapter()
    q = a.build_query(CARD)
    with pytest.raises(sc.LayoutError):
        a.parse("<html>niente __NEXT_DATA__</html>", q)


# ====================================================================
# Hareruya adapter
# ====================================================================
def test_hareruya_build_query_uses_collector_number():
    a = ad.HareruyaAdapter()
    q = a.build_query(CARD)
    assert "262/172" in q.url
    assert q.match["full"] == "262/172"
    assert q.match["pack"] == "S12a"


def test_hareruya_scrape_fixture_is_buyback_10000():
    a = ad.HareruyaAdapter()
    offer = a.scrape(CARD, _FakeClient(HARERUYA_HTML))
    assert offer.price == 10000 and offer.in_stock is True


def test_hareruya_parse_filters_wrong_number():
    a = ad.HareruyaAdapter()
    wrong = dict(CARD, card_code="S12a 999/172", model_number="999",
                 hareruya_url="https://www.hare2buy.com/product-list?keyword=999/172")
    q = a.build_query(wrong)
    assert a.parse(HARERUYA_HTML, q) == []


def test_hareruya_parse_layout_error_propagates():
    a = ad.HareruyaAdapter()
    q = a.build_query(CARD)
    with pytest.raises(sc.LayoutError):
        a.parse("<html>pagina irriconoscibile</html>", q)


# ====================================================================
# Comportamento condiviso: errore di rete -> None (non LayoutError)
# ====================================================================
class _BoomClient:
    def get(self, url):
        raise requests.ConnectionError("boom")


def test_scrape_network_error_propagates():
    # contratto aggiornato: l'errore di rete/HTTP (es. 403) PROPAGA -> run.py lo conta
    # come blocco (distinto da 'carta non trovata'). Non piu' silenziato a None.
    with pytest.raises(requests.RequestException):
        ad.CardRushAdapter().scrape(CARD, _BoomClient())
    with pytest.raises(requests.RequestException):
        ad.HareruyaAdapter().scrape(CARD, _BoomClient())


def test_cardrush_pokemon_uses_full_spa_url():
    # anti-403: per i Pokemon l'URL CardRush e' la forma COMPLETA della SPA
    a = ad.CardRushAdapter()
    q = a.build_query(dict(CARD, game_code="pokemon"))
    assert "associations" in q.url and "display_category" in q.url and "is_hot" in q.url
    assert q.match["model"] == "262" and q.match["pack"] == "S12a"


def test_build_query_empty_when_no_number():
    a = ad.HareruyaAdapter()
    card = dict(CARD, card_code="senza numero", model_number="")
    q = a.build_query(card)
    assert q.url == ""
    # scrape con url vuoto -> None senza neppure chiamare il client
    assert a.scrape(card, _BoomClient()) is None


# --- FIX collisione catalogo: numero PIENO dal campo canonico `number` --------
def _hareruya_html(rows):
    """Costruisce una pagina-risultati hare2buy minima da [(name, price_text), ...]."""
    cells = "".join(
        f'<div class="list_item_cell"><span class="goods_name">{n}</span>'
        f'<span class="selling_price">{p}</span></div>'
        for n, p in rows
    )
    return f'<div class="itemlist">{cells}</div>'


# carta di CATALOGO (harvested): niente card_code legacy, solo numero canonico
CATALOG_CARD = {
    "id": 58, "game_code": "pokemon", "pack_code": "SV2a",
    "card_code": None, "model_number": "058", "number": "058/165",
    "full_name": "ガーディ",
}


def test_hareruya_build_query_uses_canonical_number_for_catalog():
    # prima del fix: full=None -> cercava solo "058" e prendeva il max sbagliato.
    a = ad.HareruyaAdapter()
    q = a.build_query(CATALOG_CARD)
    assert q.match["full"] == "058/165"
    assert "058/165" in q.url


def test_hareruya_full_number_match_rejects_cross_set_collision():
    # ricerca '058' su hareruya restituisce piu' carte con numeratore 058:
    # solo 058/165[SV2a] e' la nostra; 058/100[XY] (cara) NON deve essere agganciata.
    a = ad.HareruyaAdapter()
    q = a.build_query(CATALOG_CARD)
    html = _hareruya_html([
        ("ガーディ(C){炎}〈058/165〉[SV2a][EX1]", "10円"),
        ("べつのカード(SR)〈058/100〉[XY][EX2]", "230,000円"),
    ])
    offers = a.parse(html, q)
    assert [o.price for o in offers] == [10]      # niente 230000
    assert a.select(offers, q).price == 10


def test_hareruya_ambiguity_guard_drops_divergent_prices():
    # due item con LO STESSO numero pieno e STESSO nome ma prezzi assurdamente
    # divergenti (collisione non distinguibile) -> nessun prezzo, non il max.
    a = ad.HareruyaAdapter()
    q = a.build_query(CATALOG_CARD)
    html = _hareruya_html([
        ("ガーディ(C)〈058/165〉[SV2a]", "10円"),
        ("ガーディ(SR)〈058/165〉[SV2a]", "90,000円"),
    ])
    assert a.parse(html, q) == []


def test_hareruya_name_disambiguates_same_number_different_card():
    # caso REALE 013/023: stesso numero per DUE carte diverse (Quick Ball vs
    # Evolution Incense) in sotto-set ([SA-gM]/[SA-frM], tag inaffidabili).
    # Il nome JP discrimina -> deve prendere la Quick Ball (2500), non il max.
    a = ad.HareruyaAdapter()
    qb = {"id": 13, "game_code": "pokemon", "pack_code": "sA",
          "card_code": None, "model_number": "013", "number": "013/023",
          "full_name": "クイックボール"}
    q = a.build_query(qb)
    assert q.match["full"] == "013/023"
    html = _hareruya_html([
        ("クイックボール:ミラー(D){グッズ}〈013/023〉[SA-gM]", "2,500円"),
        ("しんかのおこう:ミラー(D){グッズ}〈013/023〉[SA-frM]", "700円"),
    ])
    offer = a.select(a.parse(html, q), q)
    assert offer is not None and offer.price == 2500


def test_hareruya_no_price_when_our_card_absent():
    # caso REALE: la NOSTRA carta non e' su Hareruya, ma il numero aggancia una
    # carta DIVERSA (es. nostro コイル 001/015 -> Hareruya ha solo ピカチュウV 001/015).
    # Il nome NON combacia -> NESSUN prezzo, NON la carta sbagliata (no fallback).
    a = ad.HareruyaAdapter()
    magnemite = {"id": 1, "game_code": "pokemon", "pack_code": "PH-I",
                 "card_code": None, "model_number": "001", "number": "001/015",
                 "full_name": "コイル"}
    q = a.build_query(magnemite)
    html = _hareruya_html([("ピカチュウV(D){雷}〈001/015〉[S8a-G]", "100,000円")])
    assert a.parse(html, q) == []
    assert a.scrape(magnemite, _FakeClient(html)) is None


# ==== KILLER FIXTURES: porte identita' (numero pieno + set + nome + veto mirror) ====
import json as _json   # noqa: E402

KABUTOPS = {"id": 141, "game_code": "pokemon", "pack_code": "SV2a", "card_code": None,
            "model_number": "141", "number": "141/165", "variant": "", "full_name": "カブトプス"}


def _cardrush_html(items):
    nd = {"props": {"pageProps": {"buyingPrices": items}}}
    return ('<script id="__NEXT_DATA__" type="application/json">'
            + _json.dumps(nd, ensure_ascii=False) + '</script>')


def _cr(name, model, pack, amount, extra="", rarity=""):
    return {"name": name, "model_number": model, "pack_code": pack, "amount": amount,
            "extra_difference": extra, "rarity": rarity}


def test_cardrush_pokemon_veto_mirror_picks_base():
    # KILLER: Kabutops 141/165 SV2a = 3 righe (base 10, monster 400, master 1700).
    # La carta base deve dare 10, MAI il max 1700 della mirror.
    a = ad.CardRushAdapter()
    html = _cardrush_html([
        _cr("カブトプス", "141/165", "SV2a", 10),
        _cr("カブトプス:モンスターボールミラー", "141/165", "SV2a", 400),
        _cr("カブトプス:マスターボールミラー", "141/165", "SV2a", 1700),
    ])
    offer = a.scrape(KABUTOPS, _FakeClient(html))
    assert offer is not None and offer.price == 10


def test_cardrush_pokemon_full_number_not_numerator():
    # KILLER #1: stesso numeratore, set/denominatore diversi -> il numero PIENO scarta 141/100.
    a = ad.CardRushAdapter()
    html = _cardrush_html([
        _cr("カブトプス", "141/165", "SV2a", 10),
        _cr("べつのカード", "141/100", "XY", 99999),
    ])
    offer = a.scrape(KABUTOPS, _FakeClient(html))
    assert offer is not None and offer.price == 10


def test_hareruya_veto_mirror_only_base_abstains():
    # KILLER #2: per la carta base esistono SOLO le mirror -> astensione (no 1800).
    a = ad.HareruyaAdapter()
    q = a.build_query(KABUTOPS)
    html = _hareruya_html([
        ("カブトプス:モンスターボールミラー〈141/165〉[SV2a-Mo]", "100円"),
        ("カブトプス:マスターボールミラー〈141/165〉[SV2a-Ma]", "1,800円"),
    ])
    assert a.parse(html, q) == []


def test_hareruya_set_gate_picks_right_set_078_070():
    # KILLER #3: 078/070 = 4 carte diverse su 4 set. Gate set + nome isolano la nostra.
    a = ad.HareruyaAdapter()
    happiny = {"id": 1, "game_code": "pokemon", "pack_code": "S6K", "card_code": None,
               "model_number": "078", "number": "078/070", "variant": "", "full_name": "ハピナスV"}
    q = a.build_query(happiny)
    html = _hareruya_html([
        ("ハピナスV(RR){無}〈078/070〉[S6K]", "250円"),
        ("アーマーガアV(RR){無}〈078/070〉[S5R]", "350円"),
        ("ポケモンブリーダー(R)〈078/070〉[S2a]", "700円"),
        ("ガラルファイヤーV:SA(SR){悪}〈078/070〉[S5a]", "26,000円"),
    ])
    offer = a.select(a.parse(html, q), q)
    assert offer is not None and offer.price == 250


def test_hareruya_set_page_mode_matches_within_set_and_caches():
    # SPEEDUP: modalita' pagina-set. Una richiesta per set (cache), match dentro il
    # set noto. Seconda carta stesso set -> cache, nessuna nuova richiesta.
    a = ad.HareruyaAdapter()
    a.use_set_pages = True
    card = dict(CATALOG_CARD)   # ガーディ 058/165 SV2a -> sid 144
    q = a.build_query(card)
    assert q.match.get("sid") == 144 and "product-list/144" in q.url
    page1 = _hareruya_html([
        ("ガーディ(C){炎}〈058/165〉[SV2a]", "10円"),
        ("リザードンex(SAR){炎}〈198/165〉[SV2a]", "5,000円"),
    ])
    empty = '<div class="itemlist"></div>'

    class _PageClient:
        def __init__(self):
            self.calls = 0

        def get(self, url):
            self.calls += 1

            class _R:
                pass
            r = _R()
            r.text = page1 if "page=1" in url else empty
            return r

    cli = _PageClient()
    offer = a.scrape(card, cli)
    assert offer is not None and offer.price == 10
    n_after_first = cli.calls
    card2 = dict(CATALOG_CARD, number="198/165", full_name="リザードンex")
    offer2 = a.scrape(card2, cli)
    assert offer2 is not None and offer2.price == 5000
    assert cli.calls == n_after_first   # cache hit: nessuna nuova richiesta HTTP


def test_hareruya_set_page_disabled_by_default_uses_per_card():
    # default OFF: niente sid, usa la ricerca per-carta (path di fallback invariato)
    a = ad.HareruyaAdapter()
    q = a.build_query(dict(CATALOG_CARD))
    assert "sid" not in q.match and "keyword=" in q.url


# ====================================================================
# ONE PIECE — CardRush OP (numerazione OP01-001 + varianti) e Yuyu-tei
# ====================================================================
CARDRUSH_OP_HTML = (FIX / "cardrush_op_OP01-001.html").read_text(encoding="utf-8")
YUYUTEI_OP_HTML = (FIX / "yuyutei_opc_op01.html").read_text(encoding="utf-8")

OP_CARD_STD = {
    "id": 100, "game_code": "onepiece", "pack_code": "OP01",
    "card_code": "OP01-001", "model_number": "OP01-001", "number": "OP01-001",
    "variant": "", "full_name": "ロロノア・ゾロ",
    "cardrush_url": "https://cardrush.media/onepiece/buying_prices?model_number=OP01-001",
    "hareruya_url": None,
}
OP_CARD_PARALLEL = dict(OP_CARD_STD, id=101, variant="parallel")


def test_cardrush_op_base_tier_excludes_noise():
    a = ad.CardRushAdapter()
    offer = a.scrape(OP_CARD_STD, _FakeClient(CARDRUSH_OP_HTML))
    # tier base: max delle stampe NON-rumore (escluso il 40000 marcato 未開封) -> 35000
    assert offer is not None and offer.price == 35000


def test_cardrush_op_parallel_tier():
    a = ad.CardRushAdapter()
    offer = a.scrape(OP_CARD_PARALLEL, _FakeClient(CARDRUSH_OP_HTML))
    # tier parallel (rarita' L/P) -> 30000
    assert offer is not None and offer.price == 30000


def test_cardrush_op_pokemon_unaffected_by_tier_logic():
    # la logica tier vale SOLO per One Piece: i Pokemon restano sul percorso classico
    a = ad.CardRushAdapter()
    offer = a.scrape(CARD, _FakeClient(CARDRUSH_HTML))
    assert offer is not None and offer.price > 0


def test_cardrush_supports_all_games_hareruya_only_pokemon():
    assert ad.CardRushAdapter().supports("onepiece") is True
    assert ad.HareruyaAdapter().supports("onepiece") is False
    assert ad.YuyuteiAdapter().supports("onepiece") is False   # OP -> Toretoku ora
    assert ad.ToretokuAdapter().supports("onepiece") is True
    assert ad.ToretokuAdapter().supports("yugioh") is False     # YGO resta Yuyu-tei
    assert ad.YuyuteiAdapter().supports("pokemon") is False


def test_yuyutei_build_query_set_url_opc():
    a = ad.YuyuteiAdapter()
    q = a.build_query(OP_CARD_STD)
    assert q.url == "https://yuyu-tei.jp/buy/opc/s/op01"
    assert q.match["number"] == "OP01-001"


def test_yuyutei_op_standard_and_parallel():
    a = ad.YuyuteiAdapter()
    std = a.scrape(OP_CARD_STD, _FakeClient(YUYUTEI_OP_HTML))
    par = a.scrape(OP_CARD_PARALLEL, _FakeClient(YUYUTEI_OP_HTML))
    assert std is not None and std.variant == "" and std.price > 0
    assert par is not None and "パラレル" in par.variant and par.price > 0
    # la parallel costa piu' della standard (atteso su OP01-001)
    assert par.price >= std.price


def test_yuyutei_parse_layout_error():
    a = ad.YuyuteiAdapter()
    q = a.build_query(OP_CARD_STD)
    with pytest.raises(sc.LayoutError):
        a.parse("<html>pagina irriconoscibile</html>", q)


# --- Toretoku (nuova fonte buyback One Piece, al posto di Yuyu-tei) ---
TORETOKU_OP_HTML = (FIX / "toretoku_onepiece.html").read_text(encoding="utf-8")


def test_toretoku_parse_buyback_prices():
    items = sc.parse_toretoku(TORETOKU_OP_HTML)
    assert len(items) > 50
    luffy = [it for it in items if it["number"] == "OP01-003"]
    assert luffy and luffy[0]["price"] == 33500       # 買取価格 (acquisto)
    assert "パラレル" in luffy[0]["name"] and luffy[0]["rarity"] == "L"


def test_toretoku_build_query_single_list():
    a = ad.ToretokuAdapter()
    q = a.build_query(OP_CARD_STD)
    assert q.url == "https://kaitori-toretoku.jp/buypricelist/onepiece"
    assert q.match["number"] == "OP01-001"


def test_toretoku_adapter_scrape_op_parallel():
    a = ad.ToretokuAdapter()
    par = a.scrape(OP_CARD_PARALLEL, _FakeClient(TORETOKU_OP_HTML))
    # tier parallel di OP01-001 su Toretoku -> 16400 (買取)
    assert par is not None and par.price == 16400


def test_toretoku_super_tier_separato_dal_parallel():
    # OP01-016: il tier 'super' (パラレル/SP, 漫画) non deve finire nel tier 'parallel'
    a = ad.ToretokuAdapter()
    op16 = dict(OP_CARD_PARALLEL, number="OP01-016", card_code="OP01-016")
    op16_sp = dict(op16, variant="super")
    par = a.scrape(op16, _FakeClient(TORETOKU_OP_HTML))
    sup = a.scrape(op16_sp, _FakeClient(TORETOKU_OP_HTML))
    assert par is not None and sup is not None
    assert sup.price > par.price        # il super costa piu' del parallel


def test_toretoku_parse_layout_error():
    with pytest.raises(sc.LayoutError):
        sc.parse_toretoku("<html>nessun item</html>")


# ====================================================================
# YU-GI-OH — CardRush YGO (model_number = set code, es. QCCU-JP002) e Yuyu-tei
# ====================================================================
CARDRUSH_YGO_HTML = (FIX / "cardrush_ygo_QCCU-JP002.html").read_text(encoding="utf-8")
YUYUTEI_YGO_HTML = (FIX / "yuyutei_ygo_qccu.html").read_text(encoding="utf-8")

YGO_CARD = {
    "id": 200, "game_code": "yugioh", "pack_code": "QCCU",
    "card_code": "QCCU-JP002", "model_number": "QCCU-JP002", "number": "QCCU-JP002",
    "variant": "", "full_name": "ブラック・マジシャン・ガール",
    "cardrush_url": "https://cardrush.media/yugioh/buying_prices?model_number=QCCU-JP002",
    "hareruya_url": None,
}


def test_routing_yugioh_is_cardrush_plus_yuyutei():
    assert [a.source_code for a in ad.get_adapters(game="yugioh")] == ["cardrush", "yuyutei"]
    assert ad.HareruyaAdapter().supports("yugioh") is False
    assert ad.YuyuteiAdapter().supports("yugioh") is True


def test_cardrush_ygo_standard_picks_max_listing():
    a = ad.CardRushAdapter()
    offer = a.scrape(YGO_CARD, _FakeClient(CARDRUSH_YGO_HTML))
    # extra_difference None per tutti -> tutte standard; vince il prezzo piu' alto
    assert offer is not None and offer.variant == ""
    assert offer.price == 150000


def test_yuyutei_ygo_build_query_and_parse():
    a = ad.YuyuteiAdapter()
    q = a.build_query(YGO_CARD)
    assert q.url == "https://yuyu-tei.jp/buy/ygo/s/qccu"
    offer = a.scrape(YGO_CARD, _FakeClient(YUYUTEI_YGO_HTML))
    assert offer is not None and offer.price == 170000


def test_yuyutei_fetch_caches_set_page():
    a = ad.YuyuteiAdapter()

    class _CountClient:
        def __init__(self, raw):
            self.raw = raw
            self.calls = 0

        def get(self, url):
            self.calls += 1
            class _R: pass
            r = _R(); r.text = self.raw; return r

    cli = _CountClient(YUYUTEI_OP_HTML)
    a.scrape(OP_CARD_STD, cli)
    a.scrape(OP_CARD_PARALLEL, cli)   # stesso set -> deve riusare la cache
    assert cli.calls == 1
