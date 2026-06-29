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
POKE = (ROOT / "tests" / "fixtures" / "cardrush_pokemon_list.html").read_text(encoding="utf-8")


def _poke_fetch(page):
    """fetch_page iniettabile: serve la fixture CardRush per ogni pagina (offline)."""
    return POKE


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


def test_enrich_from_cardrush_offline(tmp_path):
    # da CardRush (fixture, client finto) riempie rarità + immagine HI-RES webp
    CR = (ROOT / "tests" / "fixtures" / "cardrush_op_OP01-001.html").read_text(encoding="utf-8")
    class Resp:
        def __init__(self, text=None, content=None): self.text = text; self.content = content
    class Client:
        def get(self, url):
            if "files.cardrush" in url or url.endswith(".webp"):
                return Resp(content=b"webp-bytes")
            return Resp(text=CR)
    conn = _fresh_v2()
    conn.execute("INSERT INTO tcg_game VALUES('onepiece','One Piece')")
    conn.execute("INSERT INTO tcg_set (id,game_code,set_code,set_name,display_order)"
                 " VALUES (1,'onepiece','OP01','ROMANCE DAWN',1)")
    conn.execute("INSERT INTO tcg_card (set_id,number,variant,name,cardrush_url)"
                 " VALUES (1,'OP01-001','','Zoro','http://x?model_number=OP01-001')")
    conn.commit()
    rar_n, img_n, tot = bc.enrich_from_cardrush(conn, "onepiece", "OP01",
                                                client=Client(), images_dir=str(tmp_path))
    assert rar_n == 1 and img_n == 1 and tot == 1
    rarity, image = conn.execute(
        "SELECT rarity, image_url FROM tcg_card WHERE number='OP01-001'").fetchone()
    assert rarity == "L" and image.endswith(".webp") and image.startswith("images/")


def test_pick_rarity_offline():
    # dalla pagina CardRush OP01-001 (fixture) ricava la rarita' della carta
    import scrapers as sc
    items = sc.parse_cardrush(
        (ROOT / "tests" / "fixtures" / "cardrush_op_OP01-001.html").read_text(encoding="utf-8"))
    rar = bc._pick_rarity(items, "OP01-001", "")
    assert rar == "L"


def test_run_senza_images_non_clobbera_path_locali(tmp_path):
    # regressione: prima scarico (path locale), poi un harvest SENZA images_dir
    # (es. solo --rarity) NON deve riportare image_url all'URL remoto.
    class FakeResp:
        content = b"\xff\xd8\xff\xe0fake"
    class FakeClient:
        def get(self, url): return FakeResp()
    conn = _fresh_v2()
    bc.harvest(conn, "onepiece", "OP01", "ROMANCE DAWN", html=OP01,
               client=FakeClient(), images_dir=str(tmp_path))
    before = conn.execute("SELECT image_url FROM tcg_card WHERE number='OP01-120'"
                          " AND variant='parallel'").fetchone()[0]
    assert before.startswith("images/")
    bc.harvest(conn, "onepiece", "OP01", "ROMANCE DAWN", html=OP01)  # niente images_dir
    after = conn.execute("SELECT image_url FROM tcg_card WHERE number='OP01-120'"
                         " AND variant='parallel'").fetchone()[0]
    assert after == before, "il path locale non deve essere sovrascritto dall'URL remoto"


def test_no_duplicati_dopo_cambio_rarita():
    # regressione: cambiare la rarita' (che e' nel vincolo UNIQUE) e ri-catalogare
    # NON deve creare duplicati. L'identita' carta e' (set, number, variant).
    conn = _fresh_v2()
    bc.harvest(conn, "onepiece", "OP01", "ROMANCE DAWN", html=OP01)
    n1 = conn.execute("SELECT COUNT(*) FROM tcg_card").fetchone()[0]
    conn.execute("UPDATE tcg_card SET rarity='SEC' WHERE number='OP01-120'")
    ins, skip, _, _ = bc.harvest(conn, "onepiece", "OP01", "ROMANCE DAWN", html=OP01)
    n2 = conn.execute("SELECT COUNT(*) FROM tcg_card").fetchone()[0]
    assert ins == 0 and n2 == n1            # nessuna carta nuova, nessun duplicato


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


# =====================================================================
#  POKEMON: catalogo completo dalla lista buyback CardRush (offline)
# =====================================================================
def test_harvest_pokemon_offline():
    # dalla fixture (1 pagina, 100 listing) cataloga le singole con prezzo+immagine
    conn = _fresh_v2()
    stats = bc.harvest_pokemon_cardrush(conn, fetch_page=_poke_fetch, max_pages=1)
    assert stats["catalog"] == 63           # singole distinte (set,number) nella pagina
    assert stats["inserted"] == 63 and stats["updated"] == 0
    assert stats["priced"] == 63
    # tutte le carte sono Pokemon e create
    n = conn.execute("SELECT COUNT(*) FROM tcg_card c JOIN tcg_set s ON s.id=c.set_id"
                     " WHERE s.game_code='pokemon'").fetchone()[0]
    assert n == 63
    # il prezzo CardRush e' salvato come 'confirmed'
    pr = conn.execute("""SELECT price_raw, price_status, source_code FROM tcg_price p
                         JOIN tcg_card c ON c.id=p.card_id WHERE c.number='026/PLAY'""").fetchone()
    assert pr is not None and pr[1] == "confirmed" and pr[2] == "cardrush"


def test_pokemon_standard_preferito_su_variante():
    # 026/PLAY ha una STD a 9.000.000 e una 未開封 a 12.000.000: si sceglie la STD
    conn = _fresh_v2()
    bc.harvest_pokemon_cardrush(conn, fetch_page=_poke_fetch, max_pages=1)
    price = conn.execute("""SELECT p.price_raw FROM tcg_price p
                            JOIN tcg_card c ON c.id=p.card_id
                            WHERE c.number='026/PLAY' AND p.source_code='cardrush'""").fetchone()[0]
    assert price == 9000000


def test_pokemon_image_url_remota_di_default():
    # senza images_dir l'harvester salva l'URL remoto CDN CardRush (lazy, no git bloat)
    conn = _fresh_v2()
    bc.harvest_pokemon_cardrush(conn, fetch_page=_poke_fetch, max_pages=1)
    url = conn.execute("SELECT image_url FROM tcg_card WHERE number='026/PLAY'").fetchone()[0]
    assert url and url.startswith("https://files.cardrush.media")


def test_pokemon_pack_vuoto_va_in_altro_set():
    # i listing senza pack_code confluiscono nel set placeholder その他: nessun set ''
    conn = _fresh_v2()
    bc.harvest_pokemon_cardrush(conn, fetch_page=_poke_fetch, max_pages=1)
    sets = {s for (s,) in conn.execute("SELECT set_code FROM tcg_set WHERE game_code='pokemon'")}
    assert "" not in sets
    assert bc._POKEMON_OTHER_SET in sets


def test_pokemon_idempotente_e_no_dup_su_rarita():
    # rilancio = 0 nuove; cambiare la rarita' (nel vincolo UNIQUE) non crea duplicati
    conn = _fresh_v2()
    bc.harvest_pokemon_cardrush(conn, fetch_page=_poke_fetch, max_pages=1)
    n1 = conn.execute("SELECT COUNT(*) FROM tcg_card").fetchone()[0]
    conn.execute("UPDATE tcg_card SET rarity='ZZZ' WHERE number='026/PLAY'")
    stats = bc.harvest_pokemon_cardrush(conn, fetch_page=_poke_fetch, max_pages=1)
    n2 = conn.execute("SELECT COUNT(*) FROM tcg_card").fetchone()[0]
    assert stats["inserted"] == 0 and stats["updated"] == 63 and n2 == n1


def test_pokemon_preserva_id_e_storico_esistente():
    # una carta gia' presente con uno storico manuale: l'harvest aggiorna nome/rarita'
    # e AGGIUNGE un prezzo, senza cambiare id ne' cancellare lo storico precedente.
    conn = _fresh_v2()
    conn.execute("INSERT INTO tcg_game VALUES('pokemon','Pokemon')")
    conn.execute("INSERT INTO tcg_set (id,game_code,set_code,set_name,display_order)"
                 " VALUES (1,'pokemon','その他','Other',1)")
    conn.execute("INSERT INTO tcg_card (id,set_id,number,variant,rarity,name)"
                 " VALUES (77,1,'026/PLAY','','OLD','vecchio nome')")
    conn.execute("INSERT INTO tcg_source VALUES('cardrush','CardRush')")
    conn.execute("""INSERT INTO tcg_price (card_id,source_code,price_raw,price_norm,
                    currency,condition,in_stock,price_status,is_outlier,scraped_at)
                    VALUES (77,'cardrush',111,122.1,'JPY','NM',1,'confirmed',0,'2020-01-01 00:00:00')""")
    conn.commit()
    stats = bc.harvest_pokemon_cardrush(conn, fetch_page=_poke_fetch, max_pages=1)
    # nessun duplicato della carta 77, id preservato
    rows = conn.execute("SELECT id, rarity, name FROM tcg_card WHERE set_id=1 AND number='026/PLAY'"
                        " AND variant=''").fetchall()
    assert len(rows) == 1 and rows[0][0] == 77
    assert rows[0][1] == "-" or rows[0][1] == ""  # rarita' aggiornata da CardRush ('-' -> '')
    # lo storico vecchio resta + il nuovo prezzo
    prices = conn.execute("SELECT price_raw FROM tcg_price WHERE card_id=77 ORDER BY id").fetchall()
    assert prices[0][0] == 111 and len(prices) == 2 and prices[1][0] == 9000000
