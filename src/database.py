"""
database.py - Accesso al database del TCG Tracker.
Supporta SQLite (default, zero-config) e MySQL (opzionale).
La struttura rispecchia il foglio 'BuyList Pokemon' dell'Excel.
"""
import os
import sqlite3
import datetime as dt

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "tcg_tracker.db")


def get_conn(mysql_cfg: dict | None = None):
    """Ritorna una connessione. Se mysql_cfg e' fornito usa MySQL, altrimenti SQLite."""
    if mysql_cfg:
        import mysql.connector  # pip install mysql-connector-python
        return mysql.connector.connect(**mysql_cfg)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def fetch_cards(conn):
    """Tutte le carte da scrapare (codice + url cardrush + model number)."""
    cur = conn.cursor()
    cur.execute("""SELECT id, pack_code, card_code, model_number, full_name,
                          cardrush_url, hareruya_url
                   FROM tcg_card ORDER BY id""")
    return cur.fetchall()


def save_price(conn, card_id, source, buying_price, in_stock=True):
    """Inserisce un record di prezzo (storico). commission = prezzo * 1.10."""
    comm = round(buying_price * 1.10, 2) if buying_price is not None else None
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    placeholder = "?" if isinstance(conn, sqlite3.Connection) else "%s"
    sql = f"""INSERT INTO tcg_price
              (card_id, source, buying_price, price_with_commission, currency, in_stock, scraped_at)
              VALUES ({placeholder},{placeholder},{placeholder},{placeholder},'JPY',{placeholder},{placeholder})"""
    conn.cursor().execute(sql, (card_id, source, buying_price, comm,
                                1 if in_stock else 0, now))
    conn.commit()


def export_buylist_json(conn, out_path):
    """Esporta la vista v_buylist in JSON (lista) - compatibilita' col vecchio standalone."""
    import json
    cur = conn.cursor()
    cur.execute("SELECT * FROM v_buylist")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    json.dump(rows, open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, default=str)
    return len(rows)


def export_web(conn, out_dir):
    """Genera i due JSON che alimentano la dashboard statica (Cloudflare Pages):

      buylist.json  -> {generated_at, rows:[...]}   ultimo prezzo per carta
      history.json  -> {generated_at, series:{card_id:{source:[[data,prezzo],...]}}}
                       serie storica, UN punto al giorno (l'ultimo del giorno).
    """
    import os
    import json
    import datetime as dt

    os.makedirs(out_dir, exist_ok=True)
    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()

    # --- snapshot corrente ------------------------------------------------
    cur.execute("SELECT * FROM v_buylist")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    json.dump({"generated_at": generated_at, "rows": rows},
              open(os.path.join(out_dir, "buylist.json"), "w", encoding="utf-8"),
              ensure_ascii=False, default=str)

    # --- serie storica (1 punto/giorno) -----------------------------------
    cur.execute("""
        SELECT card_id, source, substr(scraped_at, 1, 10) AS d, buying_price
        FROM tcg_price
        WHERE id IN (SELECT MAX(id) FROM tcg_price
                     GROUP BY card_id, source, substr(scraped_at, 1, 10))
        ORDER BY card_id, source, d
    """)
    series = {}
    for card_id, source, day, price in cur.fetchall():
        series.setdefault(str(card_id), {}).setdefault(source, []).append([day, price])
    json.dump({"generated_at": generated_at, "series": series},
              open(os.path.join(out_dir, "history.json"), "w", encoding="utf-8"),
              ensure_ascii=False, default=str)

    return len(rows)
