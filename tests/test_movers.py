# -*- coding: utf-8 -*-
"""
Test dei SEGNALI AZIONABILI (Fase 3.2) in src/database.py:
  - compute_alerts: spread best-vs-second tra negozi + movers 7gg (unit, puri);
  - aggancio anti-outlier/stale 3.1: un prezzo outlier/carried NON genera segnali;
  - dispatch_alerts: hook chiamato solo se ci sono segnali (predisposizione notifiche);
  - movers.json prodotto da export_web su un DB v2 sintetico.

Offline, DB v2 temporaneo dallo schema corrente: nessun contatto col DB reale.
"""
import os
import sys
import json
import sqlite3
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import database as db  # noqa: E402

SCHEMA = (ROOT / "db" / "schema_sqlite.sql").read_text(encoding="utf-8")


def _make_v2(path, cards):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO tcg_game VALUES ('pokemon','Pokemon')")
    conn.execute("INSERT INTO tcg_source VALUES ('cardrush','CardRush')")
    conn.execute("INSERT INTO tcg_source VALUES ('hareruya','Hareruya')")
    conn.execute("INSERT INTO tcg_set (id,game_code,set_code,set_name,display_order)"
                 " VALUES (1,'pokemon','S12a','VSTAR Universe',1)")
    for cid, number in cards:
        conn.execute("INSERT INTO tcg_card (id,set_id,number,name) VALUES (?,?,?,?)",
                     (cid, 1, number, f"card{cid}"))
    conn.commit()
    return conn


# --------------------------------------------------------------------------
# compute_alerts (puro)
# --------------------------------------------------------------------------
def test_spread_detected_above_threshold():
    reliable = {"1": {"cardrush": 1200, "hareruya": 1000}}
    meta = {"1": {"name": "Arceus", "set": "S12a", "game": "pokemon"}}
    out = db.compute_alerts(reliable, meta, {}, move_pct=15, spread_pct=20)
    assert len(out["spreads"]) == 1
    s = out["spreads"][0]
    assert s["best_source"] == "cardrush" and s["second_source"] == "hareruya"
    assert s["spread_pct"] == 20.0 and s["spread_abs"] == 200


def test_spread_below_threshold_ignored():
    reliable = {"2": {"cardrush": 1050, "hareruya": 1000}}
    out = db.compute_alerts(reliable, {}, {}, spread_pct=20)
    assert out["spreads"] == []


def test_single_source_no_spread_but_mover_ok():
    reliable = {"1": {"cardrush": 1200}}
    series_norm = {"1": {"cardrush": [["2026-01-01", 1000], ["2026-01-08", 1200]]}}
    out = db.compute_alerts(reliable, {}, series_norm, move_pct=15, spread_pct=20)
    assert out["spreads"] == []            # serve >=2 fonti affidabili
    assert len(out["movers"]) == 1
    m = out["movers"][0]
    assert m["pct_7d"] == 20.0 and m["direction"] == "up"
    assert m["from"] == 1000 and m["to"] == 1200


def test_mover_below_threshold_ignored():
    reliable = {"1": {"cardrush": 1080}}
    series_norm = {"1": {"cardrush": [["2026-01-01", 1000], ["2026-01-08", 1080]]}}
    out = db.compute_alerts(reliable, {}, series_norm, move_pct=15)
    assert out["movers"] == []             # +8% < 15%


def test_movers_sorted_by_magnitude():
    reliable = {"1": {"cardrush": 1200}, "2": {"cardrush": 700}}
    series_norm = {
        "1": {"cardrush": [["2026-01-01", 1000], ["2026-01-08", 1200]]},   # +20%
        "2": {"cardrush": [["2026-01-01", 1000], ["2026-01-08", 700]]},    # -30%
    }
    out = db.compute_alerts(reliable, {}, series_norm, move_pct=15)
    assert [m["card_id"] for m in out["movers"]] == ["2", "1"]   # |30| prima di |20|
    assert out["movers"][0]["direction"] == "down"


# --------------------------------------------------------------------------
# dispatch_alerts (hook notifiche)
# --------------------------------------------------------------------------
def test_dispatch_hook_called_only_with_signals():
    seen = []
    empty = {"movers": [], "spreads": []}
    db.dispatch_alerts(empty, hook=seen.append)
    assert seen == []                       # nessun segnale -> hook NON chiamato
    payload = {"movers": [{"card_id": "1"}], "spreads": []}
    db.dispatch_alerts(payload, hook=seen.append)
    assert seen == [payload]                 # con segnali -> hook chiamato una volta


def test_dispatch_no_hook_is_noop():
    payload = {"movers": [{"card_id": "1"}], "spreads": []}
    assert db.dispatch_alerts(payload) is payload   # nessun hook -> no-op, ritorna payload


# --------------------------------------------------------------------------
# Integrazione: export_web -> movers.json, con aggancio anti-outlier 3.1
# --------------------------------------------------------------------------
def _seed_signals(conn):
    # card 1: mover (+20% in 7gg) E spread (cardrush 1200 vs hareruya 1000 = 20%)
    db.save_price(conn, 1, "cardrush", 1000, run_date="2026-01-01 00:00:00")
    db.save_price(conn, 1, "cardrush", 1200, run_date="2026-01-08 00:00:00")
    db.save_price(conn, 1, "hareruya", 1000, run_date="2026-01-08 00:00:00")
    # card 2: lo "spike" piu' recente e' un OUTLIER -> NON deve generare segnali
    for i, p in enumerate((100, 110, 105)):
        db.save_price(conn, 2, "cardrush", p, run_date=f"2026-01-0{i+1} 00:00:00")
    db.save_price(conn, 2, "cardrush", 1000, run_date="2026-01-08 00:00:00")  # outlier


def test_export_movers_json_and_outlier_filtered(tmp_path):
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A"), (2, "B")])
    _seed_signals(conn)
    out = str(tmp_path / "data")
    db.export_web(conn, out)
    mv = json.load(open(os.path.join(out, "movers.json"), encoding="utf-8"))

    assert mv["thresholds"] == {"move_pct": 15.0, "spread_pct": 20.0}
    # un solo mover: card 1 (+20%). Lo spike outlier di card 2 e' filtrato.
    assert [m["card_id"] for m in mv["movers"]] == ["1"]
    assert mv["movers"][0]["pct_7d"] == 20.0 and mv["movers"][0]["direction"] == "up"
    # uno spread: card 1. Card 2 ha solo cardrush (outlier escluso) -> niente spread.
    assert [s["card_id"] for s in mv["spreads"]] == ["1"]
    assert mv["spreads"][0]["spread_pct"] == 20.0


def test_export_custom_thresholds(tmp_path):
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A"), (2, "B")])
    _seed_signals(conn)
    out = str(tmp_path / "data")
    # soglie piu' alte dello spread/mover effettivo (20%) -> nessun segnale
    db.export_web(conn, out, move_pct=25, spread_pct=25)
    mv = json.load(open(os.path.join(out, "movers.json"), encoding="utf-8"))
    assert mv["movers"] == [] and mv["spreads"] == []


def test_export_alert_hook_invoked(tmp_path):
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A"), (2, "B")])
    _seed_signals(conn)
    out = str(tmp_path / "data")
    captured = []
    db.export_web(conn, out, alert_hook=captured.append)
    assert len(captured) == 1
    assert captured[0]["movers"] and captured[0]["spreads"]
