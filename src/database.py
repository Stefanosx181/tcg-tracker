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
    """Tutte le carte da scrapare (codice + url cardrush + model number).

    Schema v2 (multi-gioco): le colonne v1 (pack_code/card_code/model_number/
    full_name) sono ricostruite via join + campi legacy, cosi' run.py resta invariato.
    """
    cur = conn.cursor()
    cur.execute("""SELECT c.id               AS id,
                          s.set_code          AS pack_code,
                          c.legacy_card_code  AS card_code,
                          c.legacy_model_number AS model_number,
                          c.name              AS full_name,
                          c.cardrush_url      AS cardrush_url,
                          c.hareruya_url      AS hareruya_url
                   FROM tcg_card c JOIN tcg_set s ON s.id = c.set_id
                   ORDER BY c.id""")
    return cur.fetchall()


def _last_known_price(conn, card_id, source):
    """Ultimo price_raw NON nullo registrato per questa carta+fonte (o None)."""
    ph = "?" if isinstance(conn, sqlite3.Connection) else "%s"
    row = conn.cursor().execute(
        f"""SELECT price_raw FROM tcg_price
            WHERE card_id={ph} AND source_code={ph} AND price_raw IS NOT NULL
            ORDER BY scraped_at DESC, id DESC LIMIT 1""",
        (card_id, source)).fetchone()
    return row[0] if row else None


def save_price(conn, card_id, source, buying_price, in_stock=True):
    """Inserisce un record di prezzo (storico). commission = prezzo * 1.10.

    Carry-forward: se la carta NON e' stata trovata (buying_price None) si
    riporta l'ULTIMO prezzo noto per quella carta+fonte. Cosi' il prezzo resta
    l'ultimo valido finche' il sito non rintraccia la carta. Questi record
    riportati sono marcati in_stock=0 (prezzo non confermato in questa passata).
    Se non esiste alcun prezzo precedente, resta None.
    """
    if buying_price is None:
        carried = _last_known_price(conn, card_id, source)
        if carried is not None:
            buying_price = carried
            in_stock = False
    comm = round(buying_price * 1.10, 2) if buying_price is not None else None
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    placeholder = "?" if isinstance(conn, sqlite3.Connection) else "%s"
    ph = placeholder
    sql = f"""INSERT INTO tcg_price
              (card_id, source_code, price_raw, price_norm, currency, condition, in_stock, scraped_at)
              VALUES ({ph},{ph},{ph},{ph},'JPY','NM',{ph},{ph})"""
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
        SELECT card_id, source_code AS source, substr(scraped_at, 1, 10) AS d, price_raw
        FROM tcg_price
        WHERE id IN (SELECT MAX(id) FROM tcg_price
                     GROUP BY card_id, source_code, substr(scraped_at, 1, 10))
        ORDER BY card_id, source_code, d
    """)
    series = {}
    for card_id, source, day, price in cur.fetchall():
        series.setdefault(str(card_id), {}).setdefault(source, []).append([day, price])
    json.dump({"generated_at": generated_at, "series": series},
              open(os.path.join(out_dir, "history.json"), "w", encoding="utf-8"),
              ensure_ascii=False, default=str)

    # --- indice di prezzo per set (media ponderata a pesi fissi) ----------
    # Peso carta = prezzo / totale set alla DATA BASE (prima data del set),
    # fissato; indice(data) = somma(prezzo(data) * peso_base). Stesso calcolo
    # del foglio "Charts" (verificato). Si calcola anche un aggregato globale.
    card_set = {str(r["card_id"]): r["set_name"] for r in rows}

    def _index(price_by_date):
        """price_by_date: {date: {card_id: price}} -> [[date, indice], ...]."""
        dates = sorted(price_by_date)
        if not dates:
            return []
        base = price_by_date[dates[0]]
        total_base = sum(base.values())
        if not total_base:
            return []
        weights = {c: p / total_base for c, p in base.items()}
        out = []
        for d in dates:
            present = price_by_date[d]
            # rinormalizza sui pesi delle carte presenti in questa data: evita
            # cali artificiali quando una carta manca (buchi nello storico).
            num = sum(present.get(c, 0) * w for c, w in weights.items())
            den = sum(w for c, w in weights.items() if c in present)
            out.append([d, round(num / den, 1) if den else 0])
        return out

    def _collect(card_ids):
        """{source: {date: {card_id: price}}} per i card_id indicati."""
        acc = {"cardrush": {}, "hareruya": {}}
        for cid in card_ids:
            for src, pts in series.get(cid, {}).items():
                for day, price in pts:
                    if price is None:
                        continue
                    acc[src].setdefault(day, {})[cid] = price
        return acc

    set_index = {}
    by_set = {}
    for cid, sname in card_set.items():
        by_set.setdefault(sname, []).append(cid)
    for sname, cids in by_set.items():
        acc = _collect(cids)
        entry = {}
        for src in ("cardrush", "hareruya"):
            s = _index(acc[src])
            if s:
                entry[src] = s
        if entry:
            set_index[sname] = entry

    glob = {}
    acc_all = _collect(list(card_set))
    for src in ("cardrush", "hareruya"):
        s = _index(acc_all[src])
        if s:
            glob[src] = s

    json.dump({"generated_at": generated_at, "sets": set_index, "global": glob},
              open(os.path.join(out_dir, "setindex.json"), "w", encoding="utf-8"),
              ensure_ascii=False, default=str)

    return len(rows)
