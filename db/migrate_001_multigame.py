"""
migrate_001_multigame.py - Migrazione schema v1 (Pokémon-specifico) -> v2 (multi-gioco).

Porta nel nuovo schema TUTTE le carte Pokémon attuali e TUTTO lo storico tcg_price,
PRESERVANDO gli id (cosi' card_id resta stabile: storico prezzi, grafici, history.json).
Il contratto-output (buylist + indice) resta invariato grazie alle viste con alias v1.

Uso (su un file DB specifico, MAI di default sul reale):
    python db/migrate_001_multigame.py tcg_tracker.backup.db

Riusata anche da src/init_db.py: costruisce il v1 dal seed e poi chiama migrate(conn).

Sicurezza:
  - non parte se il DB e' gia' v2 (tabella tcg_game presente);
  - pre-check: sorgenti impreviste e collisioni d'identita' canonica -> ABORT;
  - tutto in un'unica transazione; stampa conteggi per-tabella prima/dopo.
"""
import os
import re
import sys
import sqlite3

HERE = os.path.dirname(__file__)
SCHEMA_V2 = os.path.join(HERE, "schema_sqlite.sql")

_NUM_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_SOURCE_NAMES = {"cardrush": "CardRush", "hareruya": "Hareruya"}


def _canonical_number(card_code, model_number):
    """Numero canonico nel set: '262/172' dal card_code se presente, altrimenti
    model_number, altrimenti il card_code grezzo. Nessuna assunzione sul gioco."""
    m = _NUM_RE.search(card_code or "")
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    if model_number:
        return str(model_number)
    return (card_code or "").strip()


def schema_version(conn):
    """2 se gia' multi-gioco (tcg_game), 1 se v1 (tcg_card con pack_code), 0 se vuoto."""
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "tcg_game" in names:
        return 2
    if "tcg_card" in names:
        return 1
    return 0


def _counts(conn, tables):
    out = {}
    for t in tables:
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = None
    return out


def _precheck(old_sets, old_cards, old_prices):
    """Solleva ValueError elencando i problemi bloccanti prima di scrivere."""
    problems = []

    # sorgenti impreviste (lo schema v2 le mette in tcg_source via FK)
    srcs = sorted({p["source"] for p in old_prices})
    unexpected = [s for s in srcs if s not in _SOURCE_NAMES]
    if unexpected:
        problems.append(f"sorgenti non previste in tcg_price: {unexpected}")

    # collisioni d'identita' canonica (set_code, number, lang='JP', rarity, variant='')
    seen = {}
    pack_by_card = {}  # non serve qui, ma utile per messaggi
    set_codes = {s["pack_code"] for s in old_sets}
    for c in old_cards:
        if c["pack_code"] not in set_codes:
            problems.append(f"carta id={c['id']} con pack_code orfano '{c['pack_code']}'")
        key = (c["pack_code"], _canonical_number(c["card_code"], c["model_number"]),
               "JP", c["rarity"], "")
        if key in seen:
            problems.append(f"collisione identita' {key}: carte id={seen[key]} e id={c['id']} "
                            f"(card_code '{c['card_code']}')")
        else:
            seen[key] = c["id"]

    if problems:
        raise ValueError("Pre-check fallito, migrazione annullata:\n  - " +
                         "\n  - ".join(problems))


def migrate(conn, game_code="pokemon", game_name="Pokémon", verbose=True):
    """Migra in-place la connessione (deve essere v1). Ritorna (before, after)."""
    if schema_version(conn) != 1:
        raise RuntimeError("migrate(): il DB non e' v1 (gia' migrato o vuoto).")

    conn.row_factory = sqlite3.Row
    tables_v1 = ["tcg_set", "tcg_card", "tcg_price"]
    before = _counts(conn, tables_v1)

    # 1) leggi TUTTO il v1 in memoria PRIMA di ricreare lo schema
    old_sets = conn.execute(
        "SELECT pack_code, set_name, display_order FROM tcg_set").fetchall()
    old_cards = conn.execute(
        """SELECT id, pack_code, card_code, model_number, full_name, name_en,
                  rarity, cardrush_url, hareruya_url, row_index
           FROM tcg_card ORDER BY id""").fetchall()
    old_prices = conn.execute(
        """SELECT id, card_id, source, buying_price, price_with_commission,
                  currency, in_stock, scraped_at
           FROM tcg_price ORDER BY id""").fetchall()

    # 2) pre-check bloccanti
    _precheck(old_sets, old_cards, old_prices)

    # 3) ricrea lo schema v2 (le DROP del file azzerano le tabelle v1)
    conn.executescript(open(SCHEMA_V2, encoding="utf-8").read())

    cur = conn.cursor()
    # 4) gioco
    cur.execute("INSERT INTO tcg_game (game_code, display_name) VALUES (?,?)",
                (game_code, game_name))

    # 5) set (id nuovi) + mappa pack_code -> set_id
    set_id = {}
    for s in old_sets:
        cur.execute("""INSERT INTO tcg_set (game_code, set_code, set_name, display_order)
                       VALUES (?,?,?,?)""",
                    (game_code, s["pack_code"], s["set_name"], s["display_order"]))
        set_id[s["pack_code"]] = cur.lastrowid

    # 6) sorgenti
    for src in sorted({p["source"] for p in old_prices}):
        cur.execute("INSERT INTO tcg_source (source_code, display_name) VALUES (?,?)",
                    (src, _SOURCE_NAMES.get(src, src.title())))

    # 7) carte (id PRESERVATI)
    for c in old_cards:
        cur.execute("""INSERT INTO tcg_card
            (id, set_id, number, language, rarity, variant, name, name_en,
             cardrush_url, hareruya_url, legacy_card_code, legacy_model_number, row_index)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (c["id"], set_id[c["pack_code"]],
             _canonical_number(c["card_code"], c["model_number"]),
             "JP", c["rarity"], "", c["full_name"], c["name_en"],
             c["cardrush_url"], c["hareruya_url"], c["card_code"],
             c["model_number"], c["row_index"]))

    # 8) prezzi (id PRESERVATI, price_norm NON ricalcolato = storia identica)
    for p in old_prices:
        cur.execute("""INSERT INTO tcg_price
            (id, card_id, source_code, price_raw, price_norm, currency, condition,
             in_stock, scraped_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (p["id"], p["card_id"], p["source"], p["buying_price"],
             p["price_with_commission"], p["currency"], "NM",
             p["in_stock"], p["scraped_at"]))

    conn.commit()

    after = _counts(conn, ["tcg_game", "tcg_set", "tcg_source", "tcg_card", "tcg_price"])
    if verbose:
        _print_report(before, after)
    return before, after


def _print_report(before, after):
    print("\nConfronto conteggi righe (v1 -> v2):")
    print(f"  tcg_set   : {before['tcg_set']:>6}  ->  {after['tcg_set']:>6}")
    print(f"  tcg_card  : {before['tcg_card']:>6}  ->  {after['tcg_card']:>6}")
    print(f"  tcg_price : {before['tcg_price']:>6}  ->  {after['tcg_price']:>6}   (DEVE coincidere)")
    print(f"  tcg_game  :      -  ->  {after['tcg_game']:>6}   (nuova)")
    print(f"  tcg_source:      -  ->  {after['tcg_source']:>6}   (nuova)")
    ok = (before["tcg_set"] == after["tcg_set"]
          and before["tcg_card"] == after["tcg_card"]
          and before["tcg_price"] == after["tcg_price"])
    print("  ESITO:", "OK (nessuna perdita)" if ok else "!!! DISCREPANZA CONTEGGI !!!")


def main(argv):
    if len(argv) != 2:
        print("Uso: python db/migrate_001_multigame.py <file.db>")
        print("ATTENZIONE: passa esplicitamente il file (es. tcg_tracker.backup.db).")
        return 2
    path = argv[1]
    if not os.path.exists(path):
        print(f"File non trovato: {path}")
        return 1
    conn = sqlite3.connect(path)
    try:
        ver = schema_version(conn)
        if ver == 2:
            print(f"{path}: gia' schema v2, nulla da fare.")
            return 0
        if ver == 0:
            print(f"{path}: DB vuoto/sconosciuto, niente da migrare.")
            return 1
        print(f"Migrazione di {path} (v1 -> v2)...")
        migrate(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
