# -*- coding: utf-8 -*-
"""
Test offline degli scraper: girano SENZA rete, leggendo le fixture in
tests/fixtures/ (pagine reali salvate da CardRush e Hareruya).

Falliscono se il parsing si rompe (struttura attesa cambiata) o se cambia il
comportamento garantito: standard vs varianti, filtro model/pack, carta
normale preferita, e semantica buyback di Hareruya.
"""
import os
import sys
import json
import pathlib
import pytest
import requests

# rende importabile src/ senza installazione
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import scrapers as sc  # noqa: E402

FIX = pathlib.Path(__file__).resolve().parent / "fixtures"
CARDRUSH_HTML = (FIX / "cardrush_262.html").read_text(encoding="utf-8")
HARERUYA_HTML = (FIX / "hareruya_262.html").read_text(encoding="utf-8")


# ====================================================================
# CARDRUSH - parse
# ====================================================================
def test_cardrush_parse_real_fixture():
    items = sc.parse_cardrush(CARDRUSH_HTML)
    assert isinstance(items, list) and items, "buyingPrices vuoto: layout cambiato?"
    it = items[0]
    assert it["amount"] == 16000
    assert it["pack_code"] == "S12a"
    assert it["model_number"].split("/")[0] == "262"


def test_cardrush_parse_pure_json_list():
    items = sc.parse_cardrush(json.dumps([{"amount": 5, "model_number": "1"}]))
    assert items == [{"amount": 5, "model_number": "1"}]


def test_cardrush_parse_pure_json_wrapped():
    items = sc.parse_cardrush(json.dumps({"buyingPrices": [{"amount": 7}]}))
    assert items == [{"amount": 7}]


def test_cardrush_parse_empty_results_is_not_layout_error():
    # pagina valida ma 0 risultati (carta assente) -> [] , NON LayoutError
    html = '<html><script id="__NEXT_DATA__">%s</script></html>' % json.dumps(
        {"props": {"pageProps": {"buyingPrices": []}}})
    assert sc.parse_cardrush(html) == []


def test_cardrush_parse_layout_error_no_next_data():
    with pytest.raises(sc.LayoutError):
        sc.parse_cardrush("<html><body>nessuno script qui</body></html>")


def test_cardrush_parse_layout_error_missing_pageprops():
    html = '<script id="__NEXT_DATA__">%s</script>' % json.dumps({"props": {}})
    with pytest.raises(sc.LayoutError):
        sc.parse_cardrush(html)


# ====================================================================
# CARDRUSH - pick (standard vs varianti, filtro model/pack)
# ====================================================================
def test_cardrush_pick_real_fixture():
    items = sc.parse_cardrush(CARDRUSH_HTML)
    price, stock = sc.pick_cardrush(items, want_model="262", want_pack="S12a")
    assert (price, stock) == (16000, True)


def test_cardrush_pick_prefers_standard_over_variant():
    items = [
        {"amount": 99000, "model_number": "262", "extra_difference": "※表面加工エラー"},
        {"amount": 16000, "model_number": "262", "extra_difference": ""},
    ]
    # la variante costa di piu' ma va ignorata: vince la standard
    assert sc.pick_cardrush(items, "262") == (16000, True)


def test_cardrush_pick_variant_only_when_no_standard():
    items = [{"amount": 99000, "model_number": "262", "extra_difference": "err"}]
    assert sc.pick_cardrush(items, "262") == (99000, True)


def test_cardrush_pick_model_prefix_match():
    # want_model '262' deve combaciare con model_number '262/172'
    items = [{"amount": 100, "model_number": "262/172", "extra_difference": ""}]
    assert sc.pick_cardrush(items, "262") == (100, True)


def test_cardrush_pick_filters_wrong_model_and_pack():
    items = [
        {"amount": 100, "model_number": "999", "pack_code": "S12a"},
        {"amount": 200, "model_number": "262", "pack_code": "WRONG"},
    ]
    assert sc.pick_cardrush(items, want_model="262", want_pack="S12a") == (None, False)


def test_cardrush_pick_takes_highest_standard():
    items = [
        {"amount": 100, "model_number": "262", "extra_difference": ""},
        {"amount": 300, "model_number": "262", "extra_difference": ""},
    ]
    assert sc.pick_cardrush(items, "262") == (300, True)


# ====================================================================
# HARERUYA - parse + pick
# ====================================================================
def test_hareruya_parse_real_fixture():
    items = sc.parse_hareruya(HARERUYA_HTML)
    assert items, "nessun item: layout Hareruya cambiato?"
    names = [it["name"] for it in items]
    assert any("262/172" in n for n in names)


def test_hareruya_pick_real_fixture_is_buyback_10000():
    # D6: hare2buy.com e' il BUYBACK di Hareruya; il prezzo mostrato e'
    # l'offerta di acquisto. Valore bloccato sulla fixture reale.
    items = sc.parse_hareruya(HARERUYA_HTML)
    price, stock = sc.pick_hareruya(items, full_number="262/172", pack_code="S12a")
    assert (price, stock) == (10000, True)


def test_hareruya_pick_filters_wrong_collector_number():
    items = sc.parse_hareruya(HARERUYA_HTML)
    # numero inesistente -> nessun match
    assert sc.pick_hareruya(items, full_number="999/172") == (None, False)


def test_hareruya_pick_synthetic_picks_max_matching():
    items = [
        {"name": "X 〈262/172〉[S12a]", "price": 8000},
        {"name": "X 〈262/172〉[S12a]", "price": 12000},
        {"name": "altro 〈99/172〉[S12a]", "price": 50000},
    ]
    assert sc.pick_hareruya(items, "262/172", "S12a") == (12000, True)


def test_hareruya_pick_pack_disambiguation():
    items = [{"name": "carta 〈262/172〉[OTHER]", "price": 7000}]
    assert sc.pick_hareruya(items, "262/172", "S12a") == (None, False)


def test_hareruya_parse_zero_results_with_anchor_is_empty():
    html = '<div class="itemlist"><div class="item_count">0</div></div>'
    assert sc.parse_hareruya(html) == []


def test_hareruya_parse_layout_error_no_items_no_anchor():
    with pytest.raises(sc.LayoutError):
        sc.parse_hareruya("<html><body>pagina irriconoscibile</body></html>")


def test_to_int_price():
    assert sc._to_int_price("¥10,000") == 10000
    assert sc._to_int_price("nessun numero") is None


def test_collector_number():
    assert sc._collector_number("S12a 262/172") == "262/172"
    assert sc._collector_number("solo testo") is None


# ====================================================================
# HttpClient - retry / backoff (con sessione finta, niente rete ne' attese)
# ====================================================================
class _FakeResp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}", response=self)


class _FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)   # ognuno: _FakeResp o Exception
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o


def _client(session):
    # sleep iniettato a no-op: i test non aspettano davvero
    return sc.HttpClient(retries=3, backoff=0.01, rate_limit=0,
                         session=session, sleep=lambda *_: None)


def test_httpclient_retries_then_succeeds():
    sess = _FakeSession([
        _FakeResp(503),
        requests.ConnectionError("boom"),
        _FakeResp(200, "ok"),
    ])
    r = _client(sess).get("http://x")
    assert r.text == "ok"
    assert sess.calls == 3


def test_httpclient_raises_after_exhausting_retries():
    sess = _FakeSession([_FakeResp(500), _FakeResp(502), _FakeResp(503)])
    with pytest.raises(requests.RequestException):
        _client(sess).get("http://x")
    assert sess.calls == 3


def test_httpclient_4xx_not_retried():
    sess = _FakeSession([_FakeResp(404)])
    with pytest.raises(requests.HTTPError):
        _client(sess).get("http://x")
    assert sess.calls == 1   # 404 non si ritenta


def test_scrape_cardrush_network_error_returns_none():
    # client che fallisce sempre -> scrape_cardrush deve degradare a (None, False)
    sess = _FakeSession([requests.ConnectionError("x")] * 3)
    price, stock = sc.scrape_cardrush(
        "https://cardrush.media/x?model_number=262&pack_code=S12a", client=_client(sess))
    assert (price, stock) == (None, False)
