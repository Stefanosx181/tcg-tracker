"""
init_db.py - Crea il database SQLite (tcg_tracker.db) da schema + seed.

IMPORTANTE: e' IDEMPOTENTE. Se il database esiste gia' ed e' popolato, NON lo
tocca, cosi' lo storico dei prezzi (tabella tcg_price) non viene mai perso.
Questo serve in cloud (GitHub Actions): il DB viene committato nel repo e ogni
run deve solo AGGIUNGERE prezzi, non ricrearlo.

  python init_db.py            # crea solo se manca / vuoto (storico salvo)
  python init_db.py --force    # ricrea da zero (CANCELLA lo storico!)
"""
import os
import re
import sys
import sqlite3

HERE = os.path.dirname(__file__)
DB   = os.path.join(HERE, "..", "tcg_tracker.db")
SQL  = os.path.join(HERE, "..", "db")


def _card_count(path):
    """Numero di carte nel DB (0 se il DB non esiste o non ha le tabelle)."""
    if not os.path.exists(path):
        return 0
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM tcg_card").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def run(force=False):
    existing = _card_count(DB)
    if existing > 0 and not force:
        print(f"Database gia' presente con {existing} carte: storico preservato.")
        print("Usa  python init_db.py --force  per ricrearlo da zero (cancella lo storico).")
        return

    if os.path.exists(DB) and force:
        os.remove(DB)

    conn = sqlite3.connect(DB)
    conn.executescript(open(os.path.join(SQL, "schema_sqlite.sql"), encoding="utf-8").read())

    # Il seed e' scritto per MySQL: adattiamo le poche differenze di sintassi.
    seed = open(os.path.join(SQL, "02_seed_sets_cards.sql"), encoding="utf-8").read()
    seed = re.sub(r"USE\s+tcg_tracker\s*;", "", seed)
    conn.executescript(seed)
    conn.commit()

    n_sets  = conn.execute("SELECT COUNT(*) FROM tcg_set").fetchone()[0]
    n_cards = conn.execute("SELECT COUNT(*) FROM tcg_card").fetchone()[0]
    conn.close()
    print(f"Database creato: {os.path.abspath(DB)}")
    print(f"  set: {n_sets}  carte: {n_cards}")


if __name__ == "__main__":
    run(force="--force" in sys.argv)
