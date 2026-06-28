# -*- coding: utf-8 -*-
"""
Test della migrazione schema v1 -> v2 (db/migrate_001_multigame.py).
Gira offline su un piccolo DB v1 in memoria/temporaneo: nessun contatto col DB reale.
"""
import os
import sys
import sqlite3
import pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "db"))
sys.path.insert(0, str(ROOT / "src"))

import migrate_001_multigame as mig  # noqa: E402

V1_SCHEMA = (ROOT / "db" / "schema_v1_sqlite.sql").read_text(encoding="utf-8")


def _make_v1(path):
    conn = sqlite3.connect(path)
    conn.executescript(V1_SCHEMA)
    conn.execute("INSERT INTO tcg_set VALUES ('S12a','VSTAR Universe',1)")
    conn.execute("INSERT INTO tcg_set VALUES ('SV1V','Violet ex',2)")
    cards = [
        (10, 'S12a', 'S12a 262/172', '262', 'アルセウスVSTAR', 'Arceus VSTAR', 'UR'),
        (11, 'S12a', 'S12a 261/172', '261', 'ギラティナVSTAR', 'Giratina VSTAR', 'UR'),
        (20, 'SV1V', 'SV1V 105/078', '105', 'ミライドンex', 'Miraidon ex', 'SAR'),
    ]
    for cid, pack, code, model, full, en, rar in cards:
        conn.execute("""INSERT INTO tcg_card
            (id,pack_code,card_code,model_number,full_name,name_en,rarity,cardrush_url,hareruya_url,row_index)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid, pack, code, model, full, en, rar, f"http://cr/{model}", f"http://hr/{model}", cid))
    # prezzi: due snapshot per la carta 10, uno per le altre
    prices = [
        (10, 'cardrush', 16000, 17600.0, '2026-04-07 00:00:00'),
        (10, 'cardrush', 15000, 16500.0, '2026-06-28 00:00:00'),
        (10, 'hareruya', 10000, 11000.0, '2026-06-28 00:00:00'),
        (11, 'cardrush', 28000, 30800.0, '2026-06-28 00:00:00'),
        (20, 'hareruya', None, None, '2026-06-28 00:00:00'),
    ]
    for card_id, src, raw, comm, ts in prices:
        conn.execute("""INSERT INTO tcg_price
            (card_id,source,buying_price,price_with_commission,currency,in_stock,scraped_at)
            VALUES (?,?,?,?,'JPY',1,?)""", (card_id, src, raw, comm, ts))
    conn.commit()
    return conn


def test_migration_preserves_counts_and_ids(tmp_path):
    path = str(tmp_path / "v1.db")
    conn = _make_v1(path)
    before, after = mig.migrate(conn, verbose=False)

    assert before["tcg_set"] == after["tcg_set"] == 2
    assert before["tcg_card"] == after["tcg_card"] == 3
    assert before["tcg_price"] == after["tcg_price"] == 5
    assert after["tcg_game"] == 1
    assert after["tcg_source"] == 2

    # id carte PRESERVATI (card_id stabile per storico/grafici)
    ids = [r[0] for r in conn.execute("SELECT id FROM tcg_card ORDER BY id")]
    assert ids == [10, 11, 20]
    # prezzi della carta 10 tutti preservati (2 cardrush + 1 hareruya)
    n = conn.execute("SELECT COUNT(*) FROM tcg_price WHERE card_id=10").fetchone()[0]
    assert n == 3


def test_migration_canonical_identity_and_legacy(tmp_path):
    path = str(tmp_path / "v1.db")
    conn = _make_v1(path)
    mig.migrate(conn, verbose=False)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM tcg_card WHERE id=10").fetchone()
    assert r["number"] == "262/172"          # numero canonico dal card_code
    assert r["language"] == "JP"
    assert r["variant"] == ""
    assert r["legacy_card_code"] == "S12a 262/172"
    assert r["legacy_model_number"] == "262"  # serve all'immagine
    # set collegato al gioco
    g = conn.execute("""SELECT g.game_code FROM tcg_card c
                        JOIN tcg_set s ON s.id=c.set_id
                        JOIN tcg_game g ON g.game_code=s.game_code
                        WHERE c.id=10""").fetchone()
    assert g["game_code"] == "pokemon"


def test_migration_v_buylist_keeps_v1_columns_and_latest_by_date(tmp_path):
    path = str(tmp_path / "v1.db")
    conn = _make_v1(path)
    mig.migrate(conn, verbose=False)
    conn.row_factory = sqlite3.Row
    rows = {r["card_id"]: r for r in conn.execute("SELECT * FROM v_buylist")}
    # nomi di colonna v1 ancora presenti
    for col in ("pack_code", "card_code", "model_number", "full_name", "name_en",
                "cardrush_price", "hareruya_price", "best_price", "best_source"):
        assert col in rows[10].keys()
    # latest by DATE: per la carta 10 cardrush vince lo snapshot 2026-06-28 (15000),
    # non quello piu' vecchio 2026-04-07 (16000)
    assert rows[10]["cardrush_price"] == 15000
    assert rows[10]["pack_code"] == "S12a"


def test_migration_precheck_blocks_identity_collision(tmp_path):
    path = str(tmp_path / "v1.db")
    conn = _make_v1(path)
    # inserisco una carta che collide su (set,number,rarity,lang,variant)
    conn.execute("""INSERT INTO tcg_card
        (id,pack_code,card_code,model_number,full_name,name_en,rarity,cardrush_url,hareruya_url,row_index)
        VALUES (99,'S12a','S12a 262/172 dup','262','dup','dup','UR','x','y',99)""")
    conn.commit()
    with pytest.raises(ValueError):
        mig.migrate(conn, verbose=False)


def test_migration_refuses_non_v1(tmp_path):
    path = str(tmp_path / "v2.db")
    conn = _make_v1(path)
    mig.migrate(conn, verbose=False)         # ora e' v2
    with pytest.raises(RuntimeError):
        mig.migrate(conn, verbose=False)     # secondo giro -> rifiuta
