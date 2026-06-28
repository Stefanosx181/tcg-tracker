# -*- coding: utf-8 -*-
"""
Test dell'harvester di catalogo (src/build_catalog.py): dalla pagina-set Yuyu-tei
(fixture, offline) costruisce le carte nel DB v2.

Verifica: numero carte attese, distinzione standard/parallel, URL CardRush per
gioco, idempotenza (rilancio = 0 nuove). Nessun contatto di rete: usa le fixture
gia' presenti in tests/fixtures/.
"""
import sys
import sqlite3
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import build_catalog as bc  # noqa: E402

SCHEMA = (ROOT / "db" / "schema_sqlite.sql").read_text(encoding="utf-8")
OP01 = (ROOT / "tests" / "fixtures" / "yuyutei_opc_op01.html").read_text(encoding="utf-8")
QCCU = (ROOT / "tests" / "fixtures" / "yuyutei_ygo_qccu.html").read_text(encoding="utf-8")


def _fresh_v2():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


def test_harvest_onepiece_set_offline():
    conn = _fresh_v2()
    ins, skip, rows, imgs = bc.harvest(conn, "onepiece", "OP01", "ROMANCE DAWN", html=OP01)
    assert rows == 44                       # righe nella pagina-set
    assert ins == 43 and skip == 0          # 43 carte canoniche (1 dup collassato)
    n = conn.execute("SELECT COUNT(*) FROM tcg_card c JOIN tcg_set s ON s.id=c.set_id"
                     " WHERE s.game_code='onepiece'").fetchone()[0]
    assert n == 43


def test_standard_and_parallel_distinti():
    conn = _fresh_v2()
    bc.harvest(conn, "onepiece", "OP01", "ROMANCE DAWN", html=OP01)
    variants = {v for (v,) in conn.execute(
        "SELECT DISTINCT variant FROM tcg_card WHERE number='OP01-120'")}
    assert variants == {"", "parallel"}     # stesso numero: standard + parallel


def test_cardrush_url_per_gioco():
    conn = _fresh_v2()
    bc.harvest(conn, "onepiece", "OP01", "ROMANCE DAWN", html=OP01)
    url = conn.execute("SELECT cardrush_url FROM tcg_card WHERE number='OP01-024'"
                       " AND variant='' LIMIT 1").fetchone()[0]
    assert url == "https://cardrush.media/onepiece/buying_prices?model_number=OP01-024"


def test_idempotente():
    conn = _fresh_v2()
    bc.harvest(conn, "onepiece", "OP01", "ROMANCE DAWN", html=OP01)
    ins2, skip2, _, _ = bc.harvest(conn, "onepiece", "OP01", "ROMANCE DAWN", html=OP01)
    assert ins2 == 0 and skip2 == 43        # rilancio: niente di nuovo


def test_image_url_salvata_offline():
    # senza images_dir l'harvester salva comunque l'URL remoto dell'immagine
    conn = _fresh_v2()
    bc.harvest(conn, "onepiece", "OP01", "ROMANCE DAWN", html=OP01)
    url = conn.execute("SELECT image_url FROM tcg_card WHERE number='OP01-120'"
                       " AND variant='' LIMIT 1").fetchone()[0]
    assert url and url.startswith("https://card.yuyu-tei.jp")


def test_download_image_offline(tmp_path):
    # esercita il percorso di download con un client finto (nessuna rete):
    # le immagini finiscono in images_dir e image_url diventa un path locale.
    class FakeResp:
        content = b"\xff\xd8\xff\xe0fake-jpeg"
    class FakeClient:
        def get(self, url): return FakeResp()
    conn = _fresh_v2()
    ins, skip, rows, imgs = bc.harvest(conn, "onepiece", "OP01", "ROMANCE DAWN",
                                       html=OP01, client=FakeClient(),
                                       images_dir=str(tmp_path))
    assert imgs > 0
    files = list(tmp_path.glob("*.jpg"))
    assert files, "nessuna immagine scaricata"
    url = conn.execute("SELECT image_url FROM tcg_card WHERE number='OP01-120'"
                       " AND variant='parallel'").fetchone()[0]
    assert url.startswith("images/") and url.endswith(".jpg")


def test_pick_rarity_offline():
    # dalla pagina CardRush OP01-001 (fixture) ricava la rarita' della carta
    import scrapers as sc
    items = sc.parse_cardrush(
        (ROOT / "tests" / "fixtures" / "cardrush_op_OP01-001.html").read_text(encoding="utf-8"))
    rar = bc._pick_rarity(items, "OP01-001", "")
    assert rar == "L"


def test_short_rarity():
    assert bc._short_rarity("クォーターセンチュリーシークレット") == "QCSE"
    assert bc._short_rarity("SR/P") == "SR/P"   # gia' corta -> invariata
    assert bc._short_rarity("") == ""


def test_harvest_yugioh_offline():
    conn = _fresh_v2()
    ins, skip, rows, imgs = bc.harvest(conn, "yugioh", "QCCU", "Quarter Century", html=QCCU)
    assert ins == 1                         # la fixture YGO contiene una sola carta canonica
    src = {s for (s,) in conn.execute("SELECT source_code FROM tcg_source")}
    assert "yuyutei" in src                 # la sorgente Yuyu-tei viene registrata
