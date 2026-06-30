# -*- coding: utf-8 -*-
"""
Matching One Piece in export_web:
  - GUARD 'stampa ambigua': se due fonti divergono troppo (>4x) e' quasi certo un
    confronto tra STAMPE diverse -> print_ambiguous=True (la UI lo segnala);
  - CONFIRMED-ONLY (solo OP): i prezzi solo 'carried' (carry-forward) NON si mostrano,
    cosi' un tier senza match pulito non resta su un valore vecchio.
Gira offline su un DB v2 temporaneo.
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


def _op_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO tcg_game VALUES ('onepiece','One Piece')")
    conn.execute("INSERT INTO tcg_source VALUES ('cardrush','CardRush')")
    conn.execute("INSERT INTO tcg_source VALUES ('toretoku','Toretoku')")
    conn.execute("INSERT INTO tcg_set (id,game_code,set_code,set_name,display_order)"
                 " VALUES (1,'onepiece','OP01','ROMANCE DAWN',1)")
    conn.execute("INSERT INTO tcg_card (id,set_id,number,name) VALUES (1,1,'OP01-120','Shanks')")
    conn.execute("INSERT INTO tcg_card (id,set_id,number,name) VALUES (2,1,'OP01-003','Luffy')")
    conn.commit()
    return conn


def test_reconcile_matches_same_print():
    import op_match as om
    cr = [
        {"tier": "parallel", "art": frozenset({"海賊旗背景", "漫画絵"}), "price": 6000},
        {"tier": "parallel", "art": frozenset(), "price": 600},
        {"tier": "base", "art": frozenset({"illust:Studio Vigor"}), "price": 330000},
        {"tier": "base", "art": frozenset(), "price": 150},
    ]
    tt = [
        {"tier": "parallel", "art": frozenset({"海賊旗背景"}), "price": 3000},
        {"tier": "base", "art": frozenset(), "price": 4900},
    ]
    prints = om.reconcile(cr, tt)
    by = {(p["tier"], "/".join(sorted(p["art"])) or "plain"):
          (p["cardrush"], p["toretoku"]) for p in prints}
    # la parallel 海賊旗背景 si aggancia (6000 vs 3000)
    assert by[("parallel", "海賊旗背景/漫画絵")] == (6000, 3000)
    # la base plain si aggancia a Toretoku plain (150 vs 4900), NON il 330000
    assert by[("base", "plain")] == (150, 4900)
    # il 330000 (illust esclusivo CardRush) resta SINGLE-fonte
    assert by[("base", "illust:Studio Vigor")] == (330000, None)
    # la parallel plain CardRush senza pari -> single-fonte
    assert by[("parallel", "plain")] == (600, None)


def _rows(out):
    return {r["card_code"]: r for r in
            json.load(open(os.path.join(out, "buylist.json"), encoding="utf-8"))["rows"]}


def test_guard_flags_divergent_onepiece(tmp_path):
    conn = _op_db(str(tmp_path / "op.db"))
    db.save_price(conn, 1, "cardrush", 650000, run_date="2026-06-28 00:00:00")
    db.save_price(conn, 1, "toretoku", 3000, run_date="2026-06-28 00:00:00")
    db.save_price(conn, 2, "cardrush", 50000, run_date="2026-06-28 00:00:00")
    db.save_price(conn, 2, "toretoku", 33500, run_date="2026-06-28 00:00:00")
    out = str(tmp_path / "data")
    db.export_web(conn, out)
    rows = _rows(out)
    assert rows["OP01-120"].get("print_ambiguous") is True     # 650k vs 3k -> ambigua
    assert not rows["OP01-003"].get("print_ambiguous")          # 50k vs 33.5k -> coerente


def test_confirmed_only_drops_carried_onepiece(tmp_path):
    conn = _op_db(str(tmp_path / "op.db"))
    db.save_price(conn, 2, "cardrush", 50000, run_date="2026-06-01 00:00:00")
    db.save_price(conn, 2, "toretoku", 30000, run_date="2026-06-01 00:00:00")
    db.save_price(conn, 2, "cardrush", 50000, run_date="2026-06-28 00:00:00")
    db.save_price(conn, 2, "toretoku", None,  run_date="2026-06-28 00:00:00")  # -> carried
    out = str(tmp_path / "data")
    db.export_web(conn, out)
    # toretoku carried viene scartato (confirmed-only OP) -> resta solo cardrush ->
    # carta a FONTE SINGOLA -> ESCLUSA dalla buylist (filtro comparabilita').
    # (se il carried NON fosse scartato, avrebbe 2 fonti e comparirebbe.)
    assert "OP01-003" not in _rows(out)
