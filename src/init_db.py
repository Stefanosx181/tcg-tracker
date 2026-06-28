"""
init_db.py - Crea/aggiorna il database SQLite (tcg_tracker.db).

IMPORTANTE: e' IDEMPOTENTE e NON perde mai lo storico (tabella tcg_price).
  - DB mancante/vuoto -> costruisce lo schema v1 dal seed e lo MIGRA a v2
    (multi-gioco), cosi' "fresh" == "migrato" (un solo percorso di verita').
  - DB esistente v1    -> lo AGGIORNA a v2 in-place, storico preservato.
  - DB esistente v2    -> non fa nulla.

Serve in cloud (GitHub Actions): il DB e' committato nel repo e ogni run deve
solo AGGIUNGERE prezzi.

  python init_db.py            # crea se manca / aggiorna v1->v2 (storico salvo)
  python init_db.py --force    # ricrea da zero (CANCELLA lo storico!)
"""
import os
import re
import sys
import sqlite3

HERE = os.path.dirname(__file__)
DB   = os.path.join(HERE, "..", "tcg_tracker.db")
SQL  = os.path.join(HERE, "..", "db")

sys.path.insert(0, SQL)
sys.path.insert(0, HERE)
import migrate_001_multigame as mig  # noqa: E402
import database as db  # noqa: E402


def _build_v1_with_seed(conn):
    """Crea lo schema v1 e applica il seed (263 carte Pokémon)."""
    conn.executescript(open(os.path.join(SQL, "schema_v1_sqlite.sql"), encoding="utf-8").read())
    # Il seed e' scritto per MySQL: adattiamo le poche differenze di sintassi.
    seed = open(os.path.join(SQL, "02_seed_sets_cards.sql"), encoding="utf-8").read()
    seed = re.sub(r"USE\s+tcg_tracker\s*;", "", seed)
    conn.executescript(seed)
    conn.commit()


def run(force=False):
    if os.path.exists(DB) and force:
        os.remove(DB)

    fresh = not os.path.exists(DB)
    conn = sqlite3.connect(DB)
    try:
        ver = mig.schema_version(conn)

        if ver == 2:
            db.ensure_intelligence_columns(conn)  # colonne Fase 3 se mancano
            n = conn.execute("SELECT COUNT(*) FROM tcg_card").fetchone()[0]
            print(f"Database gia' v2 con {n} carte: colonne aggiornate (storico preservato).")
            return

        if ver == 1:
            print("Database v1 esistente: aggiorno a v2 (storico preservato)...")
            mig.migrate(conn)
            db.ensure_intelligence_columns(conn)
            print(f"Aggiornato: {os.path.abspath(DB)}")
            return

        # ver == 0: DB mancante/vuoto -> bootstrap v1 dal seed, poi migra a v2
        _build_v1_with_seed(conn)
        mig.migrate(conn)
        db.ensure_intelligence_columns(conn)
        n_sets  = conn.execute("SELECT COUNT(*) FROM tcg_set").fetchone()[0]
        n_cards = conn.execute("SELECT COUNT(*) FROM tcg_card").fetchone()[0]
        print(f"Database creato ({'nuovo' if fresh else 'rigenerato'}): {os.path.abspath(DB)}")
        print(f"  set: {n_sets}  carte: {n_cards}")
    finally:
        conn.close()


if __name__ == "__main__":
    run(force="--force" in sys.argv)
