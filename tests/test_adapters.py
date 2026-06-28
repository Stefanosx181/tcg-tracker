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
def test_registry_has_both_sources():
    codes = [a.source_code for a in ad.ADAPTERS]
    assert codes == ["cardrush", "hareruya"]
    assert ad.get_adapters("hareruya")[0].source_code == "hareruya"
    assert len(ad.get_adapters()) == 2


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
