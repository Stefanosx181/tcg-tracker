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
    assert codes == ["cardrush", "hareruya", "yuyutei"]
    assert ad.get_adapters("hareruya")[0].source_code == "hareruya"
    # routing per gioco: Pokémon = cardrush+hareruya; One Piece = cardrush+yuyutei
    assert [a.source_code for a in ad.get_adapters(game="pokemon")] == ["cardrush", "hareruya"]
    assert [a.source_code for a in ad.get_adapters(game="onepiece")] == ["cardrush", "yuyutei"]


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


def test_scrape_network_error_returns_none():
    assert ad.CardRushAdapter().scrape(CARD, _BoomClient()) is None
    assert ad.HareruyaAdapter().scrape(CARD, _BoomClient()) is None


def test_build_query_empty_when_no_number():
    a = ad.HareruyaAdapter()
    card = dict(CARD, card_code="senza numero", model_number="")
    q = a.build_query(card)
    assert q.url == ""
    # scrape con url vuoto -> None senza neppure chiamare il client
    assert a.scrape(card, _BoomClient()) is None


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


def test_cardrush_op_standard_picks_extra_difference_empty():
    a = ad.CardRushAdapter()
    offer = a.scrape(OP_CARD_STD, _FakeClient(CARDRUSH_OP_HTML))
    # la standard (extra_difference vuoto) per OP01-001 e' la carta base
    assert offer is not None and offer.variant == ""
    assert offer.price == 100


def test_cardrush_op_parallel_picks_parallel_listing():
    a = ad.CardRushAdapter()
    offer = a.scrape(OP_CARD_PARALLEL, _FakeClient(CARDRUSH_OP_HTML))
    # la variante 'parallel' deve selezionare il listing con 'パラレル'
    assert offer is not None and "パラレル" in offer.variant
    assert offer.price == 30000


def test_cardrush_supports_all_games_hareruya_only_pokemon():
    assert ad.CardRushAdapter().supports("onepiece") is True
    assert ad.HareruyaAdapter().supports("onepiece") is False
    assert ad.YuyuteiAdapter().supports("onepiece") is True
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
