# -*- coding: utf-8 -*-
"""
Test della "intelligence prezzi" (Fase 3) in src/database.py:
  - price_status esplicito: confirmed / carried / absent + carry-forward LIMITATO;
  - rilevamento outlier vs mediana storica della carta;
  - vista NORMALIZZATA (anti-outlier) separata dall'indice ufficiale;
  - trend per carta 7/30/90 gg;
  - CONTRATTO: l'indice ufficiale resta == alla formula Excel (pesi fissi alla
    data base) su dati noti, e NON viene alterato dagli outlier.

Gira offline su un DB v2 temporaneo costruito dallo schema corrente: nessun
contatto col DB reale.
"""
import os
import sys
import json
import sqlite3
import pathlib
import datetime as dt

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import database as db  # noqa: E402

SCHEMA = (ROOT / "db" / "schema_sqlite.sql").read_text(encoding="utf-8")


def _make_v2(path, cards):
    """DB v2 minimale: 1 gioco, 2 fonti, 1 set, le carte indicate.
    `cards` = lista di (card_id, number)."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO tcg_game VALUES ('pokemon','Pokemon')")
    conn.execute("INSERT INTO tcg_source VALUES ('cardrush','CardRush')")
    conn.execute("INSERT INTO tcg_source VALUES ('hareruya','Hareruya')")
    conn.execute("INSERT INTO tcg_set (id,game_code,set_code,set_name,display_order)"
                 " VALUES (1,'pokemon','S12a','VSTAR Universe',1)")
    for cid, number in cards:
        conn.execute("""INSERT INTO tcg_card (id,set_id,number,name)
                        VALUES (?,?,?,?)""", (cid, 1, number, f"card{cid}"))
    conn.commit()
    return conn


def _d(s):
    return dt.datetime.strptime(s, "%Y-%m-%d")


# --------------------------------------------------------------------------
# 1) price_status + carry-forward limitato nel tempo
# --------------------------------------------------------------------------
def test_status_confirmed_carried_absent_and_time_limit(tmp_path):
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "001")])

    # prezzo trovato -> confirmed
    db.save_price(conn, 1, "cardrush", 1000, run_date="2026-01-01 00:00:00")
    # non trovato 20 gg dopo, ultimo confirmed entro 30 gg -> carried (riporta 1000)
    db.save_price(conn, 1, "cardrush", None, run_date="2026-01-21 00:00:00")
    # non trovato 40 gg dopo l'ULTIMO CONFIRMED -> oltre il limite -> absent
    db.save_price(conn, 1, "cardrush", None, run_date="2026-02-10 00:00:00")

    rows = conn.execute("""SELECT price_raw, in_stock, price_status
                           FROM tcg_price ORDER BY scraped_at""").fetchall()
    assert [r["price_status"] for r in rows] == ["confirmed", "carried", "absent"]
    # carried riporta il prezzo ma NON e' "in stock" (non confermato)
    assert rows[1]["price_raw"] == 1000 and rows[1]["in_stock"] == 0
    # absent non inventa un prezzo
    assert rows[2]["price_raw"] is None


def test_carry_forward_does_not_self_chain(tmp_path):
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "001")])
    db.save_price(conn, 1, "cardrush", 500, run_date="2026-01-01 00:00:00")
    db.save_price(conn, 1, "cardrush", None, run_date="2026-01-20 00:00:00")  # carried
    # 25 gg dopo il carried ma 44 gg dopo il CONFIRMED: il limite e' ancorato al
    # confirmed, quindi NON si riporta -> absent (il carry non si auto-prolunga).
    db.save_price(conn, 1, "cardrush", None, run_date="2026-02-14 00:00:00")
    last = conn.execute("""SELECT price_status, price_raw FROM tcg_price
                           ORDER BY scraped_at DESC LIMIT 1""").fetchone()
    assert last["price_status"] == "absent" and last["price_raw"] is None


def test_absent_when_no_history(tmp_path):
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "001")])
    db.save_price(conn, 1, "cardrush", None, run_date="2026-01-01 00:00:00")
    r = conn.execute("SELECT price_status, price_raw FROM tcg_price").fetchone()
    assert r["price_status"] == "absent" and r["price_raw"] is None


# --------------------------------------------------------------------------
# 2) rilevamento outlier vs mediana storica
# --------------------------------------------------------------------------
def test_outlier_flag_vs_median(tmp_path):
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "001")])
    # storico stabile (mediana ~100), serve >=3 punti per giudicare
    for i, p in enumerate((100, 110, 105)):
        db.save_price(conn, 1, "cardrush", p, run_date=f"2026-01-0{i+1} 00:00:00")
    # prezzo nella norma -> NON outlier
    db.save_price(conn, 1, "cardrush", 108, run_date="2026-01-04 00:00:00")
    # spike enorme -> outlier (|1000-105|/105 >> 0.5)
    db.save_price(conn, 1, "cardrush", 1000, run_date="2026-01-05 00:00:00")

    flags = [r[0] for r in conn.execute(
        "SELECT is_outlier FROM tcg_price ORDER BY scraped_at")]
    assert flags == [0, 0, 0, 0, 1]


def test_outlier_needs_min_history(tmp_path):
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "001")])
    # solo 2 punti di storico: non si giudica ancora -> niente flag sul 3o
    db.save_price(conn, 1, "cardrush", 100, run_date="2026-01-01 00:00:00")
    db.save_price(conn, 1, "cardrush", 100, run_date="2026-01-02 00:00:00")
    db.save_price(conn, 1, "cardrush", 9999, run_date="2026-01-03 00:00:00")
    flags = [r[0] for r in conn.execute(
        "SELECT is_outlier FROM tcg_price ORDER BY scraped_at")]
    assert flags == [0, 0, 0]


# --------------------------------------------------------------------------
# 3) CONTRATTO: indice ufficiale == formula Excel (pesi fissi alla data base)
# --------------------------------------------------------------------------
def test_official_index_matches_excel_formula(tmp_path):
    """Due carte, una fonte, due date, tutte presenti:
       pesi alla DATA BASE: total=400 -> wA=0.25, wB=0.75
       indice(d) = sum(prezzo(d)*peso)/sum(pesi presenti)
       d0: 100*.25 + 300*.75 = 250.0
       d1: 120*.25 + 270*.75 = 232.5
    """
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A"), (2, "B")])
    db.save_price(conn, 1, "cardrush", 100, run_date="2026-01-01 00:00:00")
    db.save_price(conn, 2, "cardrush", 300, run_date="2026-01-01 00:00:00")
    db.save_price(conn, 1, "cardrush", 120, run_date="2026-01-08 00:00:00")
    db.save_price(conn, 2, "cardrush", 270, run_date="2026-01-08 00:00:00")

    out = str(tmp_path / "data")
    db.export_web(conn, out)
    idx = json.load(open(os.path.join(out, "setindex.json"), encoding="utf-8"))
    assert idx["global"]["cardrush"] == [["2026-01-01", 250.0],
                                         ["2026-01-08", 232.5]]


def test_official_index_unaffected_by_outlier_but_normalized_excludes_it(tmp_path):
    """Stesso set, ma la carta A ha uno SPIKE outlier all'ultima data.
       - L'indice UFFICIALE include lo spike (numero che 'loro' si aspettano).
       - La vista NORMALIZZATA lo esclude -> valore diverso.
       Cosi' verifichiamo che le migliorie NON sostituiscono il numero ufficiale.
    """
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A"), (2, "B")])
    a = [100, 110, 105, 1000]   # d3 = outlier
    b = [300, 300, 300, 300]
    days = ["2026-01-01", "2026-01-08", "2026-01-15", "2026-01-22"]
    for day, pa, pb in zip(days, a, b):
        db.save_price(conn, 1, "cardrush", pa, run_date=f"{day} 00:00:00")
        db.save_price(conn, 2, "cardrush", pb, run_date=f"{day} 00:00:00")

    out = str(tmp_path / "data")
    db.export_web(conn, out)
    idx = json.load(open(os.path.join(out, "setindex.json"), encoding="utf-8"))

    # pesi base d0: total=400 -> wA=.25, wB=.75
    off = dict(idx["global"]["cardrush"])
    norm = dict(idx["global_norm"]["cardrush"])
    # UFFICIALE d3: 1000*.25 + 300*.75 = 475.0 (lo spike PASSA, come da contratto)
    assert off["2026-01-22"] == 475.0
    # NORMALIZZATO d3: A scartato (outlier) -> resta solo B: 300*.75 / .75 = 300.0
    assert norm["2026-01-22"] == 300.0
    # le date senza outlier coincidono tra ufficiale e normalizzato
    assert off["2026-01-01"] == norm["2026-01-01"]


# --------------------------------------------------------------------------
# 4) trend per carta 7/30/90 gg
# --------------------------------------------------------------------------
def test_per_card_trend_7_30_90(tmp_path):
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A")])
    # serie scelta perche' i punti cadono ESATTAMENTE su 7/30/90 gg fa
    pts = [("2026-01-10", 60), ("2026-03-11", 80),
           ("2026-04-03", 100), ("2026-04-10", 120)]
    for day, p in pts:
        db.save_price(conn, 1, "cardrush", p, run_date=f"{day} 00:00:00")

    out = str(tmp_path / "data")
    db.export_web(conn, out)
    buy = json.load(open(os.path.join(out, "buylist.json"), encoding="utf-8"))
    row = next(r for r in buy["rows"] if r["card_id"] == 1)
    t = row["trend"]["cardrush"]
    assert t["d7"] == 20.0     # (120-100)/100
    assert t["d30"] == 50.0    # (120-80)/80
    assert t["d90"] == 100.0   # (120-60)/60


# --------------------------------------------------------------------------
# 5) ensure_intelligence_columns idempotente
# --------------------------------------------------------------------------
def test_ensure_columns_idempotent(tmp_path):
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "001")])
    db.ensure_intelligence_columns(conn)   # gia' presenti dallo schema: no-op
    db.ensure_intelligence_columns(conn)   # secondo giro: ancora no-op
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tcg_price)")}
    assert {"price_status", "is_outlier"} <= cols
