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


# Colonne "intelligence" (Fase 3) aggiunte a tcg_price DOPO lo schema v2.
#   price_status : confirmed | carried | absent (vedi save_price)
#   is_outlier   : 1 = scarto vs mediana storica oltre soglia
# Sono ADDITIVE: i DB v2 esistenti vengono aggiornati in-place senza perdere
# storico (ALTER TABLE ... ADD COLUMN). Idempotente.
_INTEL_COLUMNS = {
    "price_status": "TEXT NOT NULL DEFAULT 'confirmed'",
    "is_outlier":   "INTEGER NOT NULL DEFAULT 0",
}


def ensure_intelligence_columns(conn):
    """Aggiunge a tcg_price le colonne price_status/is_outlier se mancano.

    Idempotente e non distruttiva: i record storici esistenti ereditano il
    DEFAULT ('confirmed', 0). Va chiamata prima di scrivere/esportare prezzi.
    """
    cur = conn.cursor()
    existing = {r[1] for r in cur.execute("PRAGMA table_info(tcg_price)")}
    for col, decl in _INTEL_COLUMNS.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE tcg_price ADD COLUMN {col} {decl}")
    conn.commit()


def ensure_image_column(conn):
    """Aggiunge a tcg_card la colonna image_url se manca (idempotente).

    Serve a OP/YGO (le immagini arrivano da Yuyu-tei via build_catalog.py); per i
    Pokémon resta NULL e la UI ricostruisce il path locale come prima."""
    cur = conn.cursor()
    cols = {r[1] for r in cur.execute("PRAGMA table_info(tcg_card)")}
    if "image_url" not in cols:
        cur.execute("ALTER TABLE tcg_card ADD COLUMN image_url TEXT")
        conn.commit()


def fetch_cards(conn):
    """Tutte le carte da scrapare (codice + url cardrush + model number).

    Schema v2 (multi-gioco): le colonne v1 (pack_code/card_code/model_number/
    full_name) sono ricostruite via join + campi legacy, cosi' run.py resta invariato.
    """
    cur = conn.cursor()
    cur.execute("""SELECT c.id               AS id,
                          g.game_code         AS game_code,
                          s.set_code          AS pack_code,
                          c.legacy_card_code  AS card_code,
                          c.legacy_model_number AS model_number,
                          c.number            AS number,
                          c.variant           AS variant,
                          c.name              AS full_name,
                          c.cardrush_url      AS cardrush_url,
                          c.hareruya_url      AS hareruya_url
                   FROM tcg_card c
                   JOIN tcg_set  s ON s.id = c.set_id
                   JOIN tcg_game g ON g.game_code = s.game_code
                   ORDER BY c.id""")
    return cur.fetchall()


def fetch_cards_stale(conn, source, game=None, limit=None):
    """Come fetch_cards, ma ORDINATE per STALENESS rispetto a una fonte:
    prima le carte mai interrogate da `source`, poi quelle col prezzo piu' VECCHIO.

    Serve allo sharding di Hareruya (run.py --batch): piu' run notturni scaglionati
    chiamano questa con un limite e si dividono il catalogo SENZA sovrapporsi — una
    volta che una carta e' stata aggiornata, scende in fondo alla coda. Robusto a
    interruzioni: il run successivo riprende dalle piu' vecchie.
    """
    ph = "?" if isinstance(conn, sqlite3.Connection) else "%s"
    sql = f"""SELECT c.id               AS id,
                     g.game_code         AS game_code,
                     s.set_code          AS pack_code,
                     c.legacy_card_code  AS card_code,
                     c.legacy_model_number AS model_number,
                     c.number            AS number,
                     c.variant           AS variant,
                     c.name              AS full_name,
                     c.cardrush_url      AS cardrush_url,
                     c.hareruya_url      AS hareruya_url,
                     (SELECT MAX(p.scraped_at) FROM tcg_price p
                       WHERE p.card_id=c.id AND p.source_code={ph}) AS last_seen
              FROM tcg_card c
              JOIN tcg_set  s ON s.id = c.set_id
              JOIN tcg_game g ON g.game_code = s.game_code"""
    params = [source]
    if game:
        sql += f" WHERE g.game_code={ph}"
        params.append(game)
    # NULL (mai vista) prima, poi scraped_at crescente (piu' vecchia prima)
    sql += " ORDER BY (last_seen IS NULL) DESC, last_seen ASC, c.id"
    if limit:
        sql += f" LIMIT {ph}"
        params.append(limit)
    return conn.cursor().execute(sql, params).fetchall()


def _parse_dt(value):
    """'YYYY-MM-DD HH:MM:SS' (o datetime) -> datetime. None se non parsabile."""
    if isinstance(value, dt.datetime):
        return value
    if not value:
        return None
    try:
        return dt.datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return dt.datetime.strptime(str(value)[:10], "%Y-%m-%d")
        except ValueError:
            return None


def _median(values):
    """Mediana di una lista di numeri (None se vuota)."""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return None
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _last_known_price(conn, card_id, source):
    """Ultimo (price_raw, scraped_at) NON nullo per questa carta+fonte (o None).

    Considera SOLO i prezzi 'confirmed': un carry-forward non rigenera se stesso
    (la catena di riporti non si auto-prolunga oltre l'ultimo prezzo reale)."""
    ph = "?" if isinstance(conn, sqlite3.Connection) else "%s"
    row = conn.cursor().execute(
        f"""SELECT price_raw, scraped_at FROM tcg_price
            WHERE card_id={ph} AND source_code={ph} AND price_raw IS NOT NULL
              AND price_status='confirmed'
            ORDER BY scraped_at DESC, id DESC LIMIT 1""",
        (card_id, source)).fetchone()
    return (row[0], row[1]) if row else None


def _confirmed_prices(conn, card_id, source):
    """Tutti i price_raw 'confirmed' (per la mediana storica)."""
    ph = "?" if isinstance(conn, sqlite3.Connection) else "%s"
    rows = conn.cursor().execute(
        f"""SELECT price_raw FROM tcg_price
            WHERE card_id={ph} AND source_code={ph} AND price_raw IS NOT NULL
              AND price_status='confirmed'""",
        (card_id, source)).fetchall()
    return [r[0] for r in rows]


def save_price(conn, card_id, source, buying_price, in_stock=True, *,
               run_date=None, max_carry_days=30, outlier_threshold=0.5,
               min_history_for_outlier=3):
    """Inserisce un record di prezzo (storico). price_norm = prezzo * 1.10.

    Stato esplicito (colonna price_status):
      - 'confirmed': prezzo trovato in questa passata. Si calcola is_outlier
        confrontandolo con la MEDIANA storica (confirmed) della carta+fonte:
        is_outlier=1 se |prezzo - mediana| / mediana > outlier_threshold
        (serve almeno min_history_for_outlier prezzi storici per giudicare).
      - 'carried': carta non trovata MA esiste un ultimo prezzo confermato
        recente (entro max_carry_days). Si riporta quel prezzo, in_stock=0.
        Carry-forward ESPLICITO e LIMITATO NEL TEMPO: oltre il limite NON si
        riporta piu' (la carta risulta 'absent'), cosi' un delisting non resta
        mascherato all'infinito.
      - 'absent': carta non trovata e nessun prezzo recente -> price_raw NULL.

    is_outlier e lo stato sono SOLO informativi/per la vista normalizzata:
    l'indice UFFICIALE (export_web) continua a usare price_raw cosi' com'e'.
    """
    ensure_intelligence_columns(conn)
    now_dt = _parse_dt(run_date) or dt.datetime.now()
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    is_outlier = 0

    if buying_price is not None:
        status = "confirmed"
        hist = _confirmed_prices(conn, card_id, source)
        med = _median(hist)
        if med and len(hist) >= min_history_for_outlier:
            if abs(buying_price - med) / med > outlier_threshold:
                is_outlier = 1
    else:
        last = _last_known_price(conn, card_id, source)
        last_dt = _parse_dt(last[1]) if last else None
        if last and last_dt and (now_dt - last_dt).days <= max_carry_days:
            buying_price = last[0]
            in_stock = False
            status = "carried"
        else:
            in_stock = False
            status = "absent"

    comm = round(buying_price * 1.10, 2) if buying_price is not None else None
    ph = "?" if isinstance(conn, sqlite3.Connection) else "%s"
    sql = f"""INSERT INTO tcg_price
              (card_id, source_code, price_raw, price_norm, currency, condition,
               in_stock, price_status, is_outlier, scraped_at)
              VALUES ({ph},{ph},{ph},{ph},'JPY','NM',{ph},{ph},{ph},{ph})"""
    conn.cursor().execute(sql, (card_id, source, buying_price, comm,
                                1 if in_stock else 0, status, is_outlier, now))
    conn.commit()


# =====================================================================
#  SEGNALI AZIONABILI (movers.json) — Fase 3.2
#  Trasformano il confronto tra negozi in segnali semplici e spiegabili:
#    - spread: quanto il MIGLIOR buyback paga in piu' del secondo (per carta);
#    - movers: buyback salito/sceso molto nell'ultima settimana.
#  Si AGGANCIANO all'anti-outlier/stale della 3.1: i segnali usano SOLO prezzi
#  affidabili (confirmed + non-outlier) e la serie NORMALIZZATA, per non
#  generare falsi allarmi da carry-forward o spike. Nessuna logica di
#  budget/rivendita: restiamo nello slice prezzi+trend.
# =====================================================================
def _change(points, ndays):
    """Variazione % dell'ultimo punto vs il piu' recente <= ndays giorni fa.

    points: [[YYYY-MM-DD, prezzo], ...] ordinati. Ritorna dict
    {pct, base, to, base_day, last_day} oppure None se non calcolabile."""
    pts = [(d, p) for d, p in points if p is not None]
    if len(pts) < 2:
        return None
    last_day = dt.date.fromisoformat(pts[-1][0])
    last_val = pts[-1][1]
    cutoff = last_day - dt.timedelta(days=ndays)
    base, base_day = None, None
    for d, p in pts:
        if dt.date.fromisoformat(d) <= cutoff:
            base, base_day = p, d
        else:
            break
    if not base or base <= 0:
        return None
    return {"pct": round((last_val - base) / base * 100, 1),
            "base": base, "to": last_val, "base_day": base_day,
            "last_day": pts[-1][0]}


def compute_alerts(reliable, meta, series_norm, move_pct=15.0, spread_pct=20.0):
    """Calcola movers + spreads da prezzi AFFIDABILI (gia' filtrati a monte).

    reliable    : {card_id(str): {source: prezzo}}  (solo confirmed+non-outlier)
    meta        : {card_id(str): {name, set, game}}
    series_norm : {card_id(str): {source: [[day, price], ...]}}  (serie normalizzata)
    move_pct    : soglia |variazione 7gg| per essere "mover"
    spread_pct  : soglia spread% best-vs-second per l'alert di divergenza

    Ritorna {"movers": [...], "spreads": [...]} ordinati per intensita'.
    """
    movers, spreads = [], []
    for cid, rp in reliable.items():
        ranked = sorted(rp.items(), key=lambda kv: kv[1], reverse=True)
        best_s, best_v = ranked[0]
        m = meta.get(cid, {})
        base_info = {"card_id": cid, "name": m.get("name"),
                     "set": m.get("set"), "game": m.get("game")}

        # SPREAD: divergenza tra negozi (serve >=2 fonti affidabili).
        if len(ranked) >= 2:
            second_s, second_v = ranked[1]
            if second_v > 0:
                pct = round((best_v - second_v) / second_v * 100, 1)
                if pct >= spread_pct:
                    spreads.append({**base_info,
                                    "best_source": best_s, "best_price": best_v,
                                    "second_source": second_s, "second_price": second_v,
                                    "spread_abs": round(best_v - second_v, 2),
                                    "spread_pct": pct})

        # MOVER: variazione 7gg della MIGLIOR fonte sulla serie NORMALIZZATA.
        ch = _change(series_norm.get(cid, {}).get(best_s, []), 7)
        if ch and abs(ch["pct"]) >= move_pct:
            movers.append({**base_info, "source": best_s,
                           "pct_7d": ch["pct"], "from": ch["base"], "to": ch["to"],
                           "from_day": ch["base_day"], "to_day": ch["last_day"],
                           "direction": "up" if ch["pct"] > 0 else "down"})

    movers.sort(key=lambda x: abs(x["pct_7d"]), reverse=True)
    spreads.sort(key=lambda x: x["spread_pct"], reverse=True)
    return {"movers": movers, "spreads": spreads}


def dispatch_alerts(payload, hook=None):
    """Punto di aggancio per NOTIFICHE FUTURE (email/Telegram/webhook).

    Di default e' no-op: i segnali vengono solo scritti in movers.json. Se
    `hook` e' un callable e ci sono segnali, lo chiama col payload — cosi' un
    notifier futuro si innesta SENZA modificare export_web. Ritorna il payload.
    """
    if hook is not None and (payload.get("movers") or payload.get("spreads")):
        hook(payload)
    return payload


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


def export_web(conn, out_dir, *, move_pct=15.0, spread_pct=20.0, alert_hook=None):
    """Genera i JSON che alimentano la dashboard statica (Cloudflare Pages):

      buylist.json  -> {generated_at, rows:[...]}   ultimo prezzo per carta
      history.json  -> {generated_at, series:{card_id:{source:[[data,prezzo],...]}}}
                       serie storica, UN punto al giorno (l'ultimo del giorno).
      setindex.json -> indice ufficiale + vista normalizzata (vedi sotto).
      movers.json   -> segnali azionabili (spread tra negozi + movers 7gg).

    move_pct/spread_pct: soglie dei segnali (vedi compute_alerts).
    alert_hook: callable opzionale per notifiche future (vedi dispatch_alerts).
    """
    import os
    import json
    import datetime as dt

    os.makedirs(out_dir, exist_ok=True)
    ensure_intelligence_columns(conn)
    ensure_image_column(conn)
    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()

    # --- snapshot corrente ------------------------------------------------
    cur.execute("SELECT * FROM v_buylist")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Buylist MULTI-FONTE: oltre alle colonne legacy (cardrush_*/hareruya_*, che
    # restano per la retro-compat) aggiungiamo per ogni carta una mappa generica
    # 'prices' {source_code: {price, comm, stock}} e il 'game', cosi' i giochi con
    # una seconda fonte diversa (es. One Piece: cardrush + yuyutei) compaiono nella
    # buylist. best_price/best_source vengono RICALCOLATI su tutte le fonti presenti
    # (per Pokémon = stesse due fonti -> valori invariati).
    cur.execute("""SELECT card_id, source_code, price_raw, price_norm, in_stock,
                          price_status, is_outlier
                   FROM v_latest_price""")
    prices_by_card = {}
    for cid, src, raw, norm, stock, status, outlier in cur.fetchall():
        prices_by_card.setdefault(cid, {})[src] = {
            "price": raw, "comm": norm, "stock": stock,
            "status": status, "outlier": outlier}
    cur.execute("""SELECT c.id, g.game_code, c.number, c.image_url FROM tcg_card c
                   JOIN tcg_set s ON s.id = c.set_id
                   JOIN tcg_game g ON g.game_code = s.game_code""")
    meta_by_card = {cid: (game, number, image)
                    for cid, game, number, image in cur.fetchall()}
    # ordine di preferenza fonti (per il tie-break di best_source, come il v1)
    src_order = ["cardrush", "hareruya", "yuyutei", "toretoku"]
    # Fonti CORRENTI per gioco (dal registry adapter): cosi' i prezzi di una fonte
    # DISMESSA per un gioco (es. Yuyu-tei per One Piece, ora -> Toretoku) restano
    # nello storico ma NON vengono mostrati. Niente cancellazione di storico.
    import adapters as _ad
    _allowed_cache = {}

    def _allowed(game):
        if game not in _allowed_cache:
            _allowed_cache[game] = ({a.source_code for a in _ad.ADAPTERS if a.supports(game)}
                                    if game else None)
        return _allowed_cache[game]

    for r in rows:
        cid = r["card_id"]
        game, number, image = meta_by_card.get(cid, (None, None, None))
        pr = prices_by_card.get(cid, {})
        allow = _allowed(game)
        if allow is not None:
            pr = {s: v for s, v in pr.items() if s in allow}
        # One Piece: mostra SOLO i prezzi appena confermati (no carry-forward
        # stantio), cosi' un tier senza match pulito non resta su un prezzo vecchio.
        if game == "onepiece":
            pr = {s: v for s, v in pr.items() if v.get("status") == "confirmed"}
        r["prices"] = pr
        r["game"] = game
        # OP/YGO non hanno il card_code legacy: esponi il numero canonico
        # (es. OP01-120) come codice, cosi' la carta resta identificabile nella UI.
        if not r.get("card_code"):
            r["card_code"] = number
        # immagine locale (OP/YGO da Yuyu-tei); per i Pokémon resta None e la UI
        # ricostruisce il path dalle colonne legacy come prima.
        if image:
            r["image"] = image
        best_src, best_val = None, 0
        for src in sorted(pr, key=lambda s: src_order.index(s) if s in src_order else 99):
            v = pr[src]["price"] or 0
            if v > best_val:
                best_val, best_src = v, src
        r["best_price"] = best_val
        r["best_source"] = best_src
        # GUARD stampa ambigua (One Piece): se due fonti divergono troppo, quasi
        # certamente confrontano STAMPE diverse dello stesso numero -> non spacciare
        # un "migliore"/ratio fuorviante; la UI lo segnala.
        vals = [v["price"] for v in pr.values() if v.get("price")]
        if game == "onepiece" and len(vals) >= 2 and min(vals) > 0 \
                and max(vals) / min(vals) > 4.0:
            r["print_ambiguous"] = True

    # --- serie storica (1 punto/giorno) -----------------------------------
    # UFFICIALE: ultimo prezzo del giorno per carta+fonte, price_raw cosi' com'e'
    # (include i 'carried'). E' la base dell'indice ufficiale: NON va filtrata.
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

    # NORMALIZZATA (vista AGGIUNTIVA, anti-outlier): stessa granularita' ma SOLO
    # prezzi 'confirmed' e non-outlier. Non tocca la serie/indice ufficiale.
    cur.execute("""
        SELECT card_id, source_code AS source, substr(scraped_at, 1, 10) AS d, price_raw
        FROM tcg_price
        WHERE id IN (SELECT MAX(id) FROM tcg_price
                     GROUP BY card_id, source_code, substr(scraped_at, 1, 10))
          AND price_raw IS NOT NULL AND price_status='confirmed' AND is_outlier=0
        ORDER BY card_id, source_code, d
    """)
    series_norm = {}
    for card_id, source, day, price in cur.fetchall():
        series_norm.setdefault(str(card_id), {}).setdefault(source, []).append([day, price])

    json.dump({"generated_at": generated_at, "series": series},
              open(os.path.join(out_dir, "history.json"), "w", encoding="utf-8"),
              ensure_ascii=False, default=str)

    # --- trend per carta (7/30/90 gg) -------------------------------------
    # Variazione % dell'ultimo prezzo rispetto al piu' recente <= N giorni fa,
    # per fonte. Usa la serie UFFICIALE (il prezzo che la dashboard mostra).
    def _trend(points):
        pts = [(d, p) for d, p in points if p is not None]
        if not pts:
            return None
        last_day = dt.date.fromisoformat(pts[-1][0])
        last_val = pts[-1][1]
        out = {}
        for n, key in ((7, "d7"), (30, "d30"), (90, "d90")):
            cutoff = last_day - dt.timedelta(days=n)
            base = None
            for d, p in pts:
                if dt.date.fromisoformat(d) <= cutoff:
                    base = p
                else:
                    break
            out[key] = round((last_val - base) / base * 100, 1) if base else None
        return out

    for r in rows:
        cid = str(r["card_id"])
        r["trend"] = {src: _trend(pts) for src, pts in series.get(cid, {}).items()}

    json.dump({"generated_at": generated_at, "rows": rows},
              open(os.path.join(out_dir, "buylist.json"), "w", encoding="utf-8"),
              ensure_ascii=False, default=str)

    # --- segnali azionabili (movers + spread) -----------------------------
    # Solo prezzi AFFIDABILI (confirmed + non-outlier + >0): l'aggancio 3.1
    # evita falsi segnali da carry-forward/spike. I movers usano series_norm.
    reliable, meta = {}, {}
    for r in rows:
        cid = str(r["card_id"])
        rp = {s: d["price"] for s, d in r["prices"].items()
              if d.get("status") == "confirmed" and not d.get("outlier")
              and (d.get("price") or 0) > 0}
        if rp:
            reliable[cid] = rp
        meta[cid] = {"name": r.get("full_name") or r.get("card_code"),
                     "set": r.get("set_name"), "game": r.get("game")}
    alerts = compute_alerts(reliable, meta, series_norm,
                            move_pct=move_pct, spread_pct=spread_pct)
    payload = {"generated_at": generated_at,
               "thresholds": {"move_pct": move_pct, "spread_pct": spread_pct},
               "movers": alerts["movers"], "spreads": alerts["spreads"]}
    dispatch_alerts(payload, alert_hook)   # hook notifiche future (no-op di default)
    json.dump(payload,
              open(os.path.join(out_dir, "movers.json"), "w", encoding="utf-8"),
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

    def _collect(card_ids, src_series):
        """{source: {date: {card_id: price}}} per i card_id indicati, da una
        serie data (ufficiale o normalizzata). Le fonti sono dinamiche
        (cardrush/hareruya per Pokémon, cardrush/yuyutei per One Piece, ecc.)."""
        acc = {}
        for cid in card_ids:
            for src, pts in src_series.get(cid, {}).items():
                for day, price in pts:
                    if price is None:
                        continue
                    acc.setdefault(src, {}).setdefault(day, {})[cid] = price
        return acc

    def _index_entry(acc):
        """Indice per ciascuna fonte presente in acc -> {source: serie}."""
        entry = {}
        for src, by_date in acc.items():
            s = _index(by_date)
            if s:
                entry[src] = s
        return entry

    by_set = {}
    for cid, sname in card_set.items():
        by_set.setdefault(sname, []).append(cid)

    def _build_index(src_series):
        """sets + global per una serie data."""
        si = {}
        for sname, cids in by_set.items():
            entry = _index_entry(_collect(cids, src_series))
            if entry:
                si[sname] = entry
        gl = _index_entry(_collect(list(card_set), src_series))
        return si, gl

    # UFFICIALE (contratto): pesi fissi alla data base, su price_raw com'e'.
    set_index, glob = _build_index(series)
    # NORMALIZZATO (vista aggiuntiva): stesso calcolo ma su serie senza outlier
    # e senza prezzi non-confermati. Chiavi distinte -> non sostituisce l'ufficiale.
    set_index_norm, glob_norm = _build_index(series_norm)

    json.dump({"generated_at": generated_at,
               "sets": set_index, "global": glob,
               "sets_norm": set_index_norm, "global_norm": glob_norm},
              open(os.path.join(out_dir, "setindex.json"), "w", encoding="utf-8"),
              ensure_ascii=False, default=str)

    return len(rows)
