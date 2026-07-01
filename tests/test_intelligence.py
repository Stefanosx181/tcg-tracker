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
    # 'global' e' PER-GIOCO: l'aggregato Pokémon (contratto = foglio Charts)
    assert idx["global"]["pokemon"]["cardrush"] == [["2026-01-01", 250.0],
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

    # pesi base FISSI d0 (prima data di ogni carta): wA=100, wB=300 (scala
    # irrilevante nella media normalizzata) -> indice(d0)= (100*100+300*300)/400 =250
    off = dict(idx["global"]["pokemon"]["cardrush"])
    norm = dict(idx["global_norm"]["pokemon"]["cardrush"])
    # UFFICIALE d3: (1000*100 + 300*300)/400 = 475.0 (lo spike PASSA, come da contratto)
    assert off["2026-01-22"] == 475.0
    # NORMALIZZATO d3: A e' outlier a d3 -> escluso dalla serie norm, ma A resta nel
    # basket col suo ULTIMO prezzo sano (105 a d2, carry-forward nell'indice):
    # (105*100 + 300*300)/400 = 251.2  (!= 475.0 ufficiale: la norma esclude lo spike)
    assert norm["2026-01-22"] == 251.2
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
    # seconda fonte: la carta deve essere COMPARABILE per comparire in buylist
    db.save_price(conn, 1, "hareruya", 110, run_date="2026-04-10 00:00:00")

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
def test_buylist_only_comparable_and_excludes_rejected(tmp_path):
    # buylist = solo carte con prezzo da >=2 fonti; 'rejected' escluso ovunque.
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A"), (2, "B"), (3, "C")])
    db.save_price(conn, 1, "cardrush", 100, run_date="2026-06-28 00:00:00")
    db.save_price(conn, 1, "hareruya", 120, run_date="2026-06-28 00:00:00")   # 2 fonti -> resta
    db.save_price(conn, 2, "cardrush", 100, run_date="2026-06-28 00:00:00")   # solo CR -> esclusa
    # card3: CR + un HR poi marcato 'rejected' (garbage) -> NON comparabile -> esclusa
    db.save_price(conn, 3, "cardrush", 100, run_date="2026-06-28 00:00:00")
    db.save_price(conn, 3, "hareruya", 999999, run_date="2026-06-29 00:00:00")
    conn.execute("UPDATE tcg_price SET price_status='rejected' WHERE card_id=3 AND source_code='hareruya'")
    conn.commit()
    out = str(tmp_path / "data")
    db.export_web(conn, out)
    buy = json.load(open(os.path.join(out, "buylist.json"), encoding="utf-8"))
    assert {r["card_id"] for r in buy["rows"]} == {1}
    # l'indice ufficiale NON include il prezzo 'rejected' (999999) di card3
    si = json.load(open(os.path.join(out, "setindex.json"), encoding="utf-8"))
    blob = json.dumps(si)
    assert "999999" not in blob


def test_new_card_enters_from_its_first_day_others_carried(tmp_path):
    # Carta nuova B aggiunta DOPO: ENTRA nell'indice dal suo primo giorno col suo
    # peso base (=999), NON resta esclusa. La carta A, non scrapata quel giorno,
    # resta nel basket col suo ultimo prezzo (carry-forward nell'indice). Niente
    # crollo a zero: il peso e' fisso, non dipende da cosa e' stato scrapato.
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A"), (2, "B")])
    db.save_price(conn, 1, "cardrush", 100, run_date="2026-01-01 00:00:00")  # A: base 01-01
    db.save_price(conn, 1, "cardrush", 120, run_date="2026-01-08 00:00:00")
    db.save_price(conn, 2, "cardrush", 999, run_date="2026-01-15 00:00:00")  # B: base 01-15
    out = str(tmp_path / "data")
    db.export_web(conn, out)
    si = json.load(open(os.path.join(out, "setindex.json"), encoding="utf-8"))
    serie = dict(si["sets"]["VSTAR Universe"]["cardrush"])
    vals = list(serie.values())
    assert 0 not in vals                       # nessun punto a zero
    # tutte e 3 le date presenti: la nuova NON viene saltata
    assert set(serie) == {"2026-01-01", "2026-01-08", "2026-01-15"}
    assert serie["2026-01-01"] == 100.0        # solo A: media = suo prezzo
    assert serie["2026-01-08"] == 120.0        # A sale, peso base fisso (100)
    # 01-15: B entra (peso 999) + A riportata (120): (120*100 + 999*999)/(100+999)
    assert serie["2026-01-15"] == 919.0


def test_sources_aligned_on_union_dates_carry_forward(tmp_path):
    # Una notte gira SOLO Hareruya (giorno "in piu'"): CardRush deve RIPORTARE il
    # prezzo del giorno prima per le carte mancanti, cosi' le due serie dell'indice
    # restano allineate sulle stesse date (niente giorni scoperti su CR).
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A")])
    db.save_price(conn, 1, "cardrush", 100, run_date="2026-01-01 00:00:00")
    db.save_price(conn, 1, "hareruya", 90,  run_date="2026-01-01 00:00:00")
    db.save_price(conn, 1, "cardrush", 120, run_date="2026-01-08 00:00:00")
    db.save_price(conn, 1, "hareruya", 110, run_date="2026-01-08 00:00:00")
    # 01-15: SOLO hareruya
    db.save_price(conn, 1, "hareruya", 130, run_date="2026-01-15 00:00:00")

    out = str(tmp_path / "data")
    db.export_web(conn, out)
    si = json.load(open(os.path.join(out, "setindex.json"), encoding="utf-8"))
    cr = dict(si["sets"]["VSTAR Universe"]["cardrush"])
    hr = dict(si["sets"]["VSTAR Universe"]["hareruya"])
    # entrambe le fonti hanno un punto anche il 15 (griglia unione)
    assert "2026-01-15" in cr and "2026-01-15" in hr
    # CR il 15 = RIPORTO del giorno prima (120), non scomparsa
    assert cr["2026-01-15"] == 120.0
    assert hr["2026-01-15"] == 130.0


def test_noise_buckets_excluded_from_index(tmp_path):
    # I bucket grab-bag その他/乱 (prezzi harvest inaffidabili) NON entrano
    # nell'indice ne' nell'aggregato per-gioco; lo storico NON viene cancellato.
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A")])
    conn.execute("INSERT INTO tcg_set (id,game_code,set_code,set_name,display_order)"
                 " VALUES (2,'pokemon','その他','Other',99)")
    conn.execute("INSERT INTO tcg_card (id,set_id,number,name) VALUES (2,2,'026','junk')")
    conn.commit()
    db.save_price(conn, 1, "cardrush", 100, run_date="2026-01-01 00:00:00")
    db.save_price(conn, 1, "hareruya", 120, run_date="2026-01-01 00:00:00")
    db.save_price(conn, 2, "cardrush", 9000000, run_date="2026-01-01 00:00:00")  # garbage
    out = str(tmp_path / "data")
    db.export_web(conn, out)
    si = json.load(open(os.path.join(out, "setindex.json"), encoding="utf-8"))
    # il bucket 'Other' non ha una serie d'indice; il prezzo 9M non e' nell'aggregato
    assert "Other" not in si["sets"]
    assert "9000000" not in json.dumps(si)
    # ma il prezzo garbage e' ancora nello storico (non cancellato)
    n = conn.execute("SELECT COUNT(*) FROM tcg_price WHERE price_raw=9000000").fetchone()[0]
    assert n == 1


def test_history_fills_per_card_gaps_across_sources(tmp_path):
    # una notte gira solo Hareruya (01-01), un'altra solo CardRush (01-15): nel grafico
    # storico CR e HR devono avere un punto su TUTTE le date della carta, riportando il
    # prezzo dal giorno PRIMA (o dal giorno DOPO per i buchi iniziali). La serie GREZZA
    # (indice/trend) NON va toccata: solo history.json.
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A")])
    db.save_price(conn, 1, "hareruya", 90,  run_date="2026-01-01 00:00:00")   # solo HR
    db.save_price(conn, 1, "cardrush", 120, run_date="2026-01-08 00:00:00")
    db.save_price(conn, 1, "hareruya", 110, run_date="2026-01-08 00:00:00")
    db.save_price(conn, 1, "cardrush", 130, run_date="2026-01-15 00:00:00")   # solo CR
    out = str(tmp_path / "data")
    db.export_web(conn, out)
    s = json.load(open(os.path.join(out, "history.json"), encoding="utf-8"))["series"]["1"]
    # entrambe le fonti hanno un punto su tutte e 3 le date (griglia unione della carta)
    assert [d for d, _ in s["cardrush"]] == ["2026-01-01", "2026-01-08", "2026-01-15"]
    assert [d for d, _ in s["hareruya"]] == ["2026-01-01", "2026-01-08", "2026-01-15"]
    # CR: buco INIZIALE 01-01 = primo prezzo noto (120, giorno dopo); 01-15 reale (130)
    assert dict(s["cardrush"]) == {"2026-01-01": 120, "2026-01-08": 120, "2026-01-15": 130}
    # HR: 01-15 mancante = riporto del giorno PRIMA (110)
    assert dict(s["hareruya"]) == {"2026-01-01": 90, "2026-01-08": 110, "2026-01-15": 110}


def test_history_smooths_isolated_spike_without_touching_db(tmp_path):
    # un prezzo HR palesemente sbagliato (25000) smentito dal giorno DOPO (3000) e dalla
    # CROSS-fonte stesso giorno (CR 4000) viene EQUILIBRATO col valore del giorno dopo
    # (3000). Lo storico grezzo NON viene toccato ne' marcato (resta 25000 confirmed).
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A")])
    db.save_price(conn, 1, "cardrush", 4000,  run_date="2026-06-29 00:00:00")
    db.save_price(conn, 1, "hareruya", 25000, run_date="2026-06-29 00:00:00")   # spike
    db.save_price(conn, 1, "hareruya", 3000,  run_date="2026-06-30 00:00:00")
    out = str(tmp_path / "data")
    db.export_web(conn, out)
    s = json.load(open(os.path.join(out, "history.json"), encoding="utf-8"))["series"]["1"]
    assert dict(s["hareruya"])["2026-06-29"] == 3000       # equilibrato, non 25000
    # lo storico grezzo resta intatto (niente rejected, niente overwrite nel DB)
    raw = conn.execute("""SELECT price_raw, price_status FROM tcg_price WHERE card_id=1
        AND source_code='hareruya' AND substr(scraped_at,1,10)='2026-06-29'""").fetchone()
    assert raw[0] == 25000 and raw[1] == "confirmed"
    # lo spike non compare nell'indice
    si = json.load(open(os.path.join(out, "setindex.json"), encoding="utf-8"))
    assert "25000" not in json.dumps(si)


def test_smoothing_keeps_real_moves_and_charts_window(tmp_path):
    # NON deve equilibrare un movimento REALE: se le due fonti CONCORDANO su un valore
    # alto (non c'e' cross-fonte piu' bassa), il prezzo resta. E la finestra Charts
    # (senza spike) resta identica alla formula Excel.
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A"), (2, "B")])
    db.save_price(conn, 1, "cardrush", 100, run_date="2026-01-01 00:00:00")
    db.save_price(conn, 2, "cardrush", 300, run_date="2026-01-01 00:00:00")
    db.save_price(conn, 1, "cardrush", 120, run_date="2026-01-08 00:00:00")
    db.save_price(conn, 2, "cardrush", 270, run_date="2026-01-08 00:00:00")
    out = str(tmp_path / "data")
    db.export_web(conn, out)
    idx = json.load(open(os.path.join(out, "setindex.json"), encoding="utf-8"))
    assert idx["global"]["pokemon"]["cardrush"] == [["2026-01-01", 250.0],
                                                    ["2026-01-08", 232.5]]


def test_gap_fill_does_not_touch_official_index(tmp_path):
    # il riempimento buchi e' SOLO per history.json: l'indice ufficiale (setindex)
    # resta byte-identico alla formula Excel (pesi fissi).
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A"), (2, "B")])
    db.save_price(conn, 1, "cardrush", 100, run_date="2026-01-01 00:00:00")
    db.save_price(conn, 2, "cardrush", 300, run_date="2026-01-01 00:00:00")
    db.save_price(conn, 1, "cardrush", 120, run_date="2026-01-08 00:00:00")
    db.save_price(conn, 2, "cardrush", 270, run_date="2026-01-08 00:00:00")
    out = str(tmp_path / "data")
    db.export_web(conn, out)
    idx = json.load(open(os.path.join(out, "setindex.json"), encoding="utf-8"))
    assert idx["global"]["pokemon"]["cardrush"] == [["2026-01-01", 250.0],
                                                    ["2026-01-08", 232.5]]


def test_health_json_written(tmp_path):
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "A")])
    db.save_price(conn, 1, "cardrush", 100, run_date="2026-06-28 00:00:00")
    db.save_price(conn, 1, "hareruya", 120, run_date="2026-06-28 00:00:00")
    out = str(tmp_path / "data")
    db.export_web(conn, out)
    h = json.load(open(os.path.join(out, "health.json"), encoding="utf-8"))
    assert "sources" in h and h["sources"].get("cardrush", {}).get("confirmed") == 1
    assert h["total_cards"] == 1 and h["comparable_cards"] == 1


def test_ensure_columns_idempotent(tmp_path):
    conn = _make_v2(str(tmp_path / "t.db"), [(1, "001")])
    db.ensure_intelligence_columns(conn)   # gia' presenti dallo schema: no-op
    db.ensure_intelligence_columns(conn)   # secondo giro: ancora no-op
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tcg_price)")}
    assert {"price_status", "is_outlier"} <= cols
