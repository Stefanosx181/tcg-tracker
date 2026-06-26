"""
run.py - ESEGUIBILE PRINCIPALE del TCG Tracker.

Cosa fa:
  1. Legge le carte dal database (set + codici + URL), che a sua volta
     deriva dall'Excel SENZA modificarlo.
  2. Per ogni carta recupera il buying price da cardrush e da hareruya.
  3. Salva i prezzi nel database (storico) e aggiorna il JSON della schermata.

Uso:
  python run.py                # scrape di tutte le carte (SQLite)
  python run.py --set S12A     # solo un set
  python run.py --limit 10     # primi 10 (test)
  python run.py --only cardrush
  python run.py --sleep 1.5    # pausa tra richieste

Per compilarlo in .exe vedere build/build_exe.bat
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(__file__))
import database as db
import scrapers as sc

HERE = os.path.dirname(__file__)
DATA_DIR = os.path.join(HERE, "..", "dashboard", "data")
LEGACY_JSON = os.path.join(HERE, "..", "dashboard", "buylist_live.json")


def main():
    ap = argparse.ArgumentParser(description="TCG Tracker - scraping buying prices")
    ap.add_argument("--set", help="filtra per pack_code, es. S12A")
    ap.add_argument("--limit", type=int, help="max carte (test)")
    ap.add_argument("--only", choices=["cardrush", "hareruya"], help="un solo sito")
    ap.add_argument("--sleep", type=float, default=1.0, help="pausa secondi tra richieste")
    args = ap.parse_args()

    if not os.path.exists(db.DB_PATH):
        print("Database non trovato. Esegui prima:  python init_db.py")
        sys.exit(1)

    conn = db.get_conn()
    cards = db.fetch_cards(conn)
    if args.set:
        cards = [c for c in cards if c["pack_code"].upper() == args.set.upper()]
    if args.limit:
        cards = cards[: args.limit]

    print(f"Carte da elaborare: {len(cards)}\n")
    # contatori per fonte: servono a capire se un sito ha smesso di rispondere
    tried = {"cardrush": 0, "hareruya": 0}
    found = {"cardrush": 0, "hareruya": 0}

    for i, c in enumerate(cards, 1):
        print(f"[{i}/{len(cards)}] {c['card_code']}  ({c['pack_code']})")

        if args.only != "hareruya":
            price, stock = sc.scrape_cardrush(c["cardrush_url"])
            db.save_price(conn, c["id"], "cardrush", price, stock)
            tried["cardrush"] += 1
            found["cardrush"] += price is not None
            print(f"    cardrush : {price if price is not None else '—'}")
            sc.polite_sleep(args.sleep)

        if args.only != "cardrush":
            price, stock = sc.scrape_hareruya(c["card_code"], c["pack_code"], c["model_number"])
            db.save_price(conn, c["id"], "hareruya", price, stock)
            tried["hareruya"] += 1
            found["hareruya"] += price is not None
            print(f"    hareruya : {price if price is not None else '—'}")
            sc.polite_sleep(args.sleep)

    n = db.export_web(conn, DATA_DIR)
    db.export_buylist_json(conn, LEGACY_JSON)   # retro-compatibilita' standalone
    conn.close()

    print(f"\nFatto. {n} righe esportate in dashboard/data/")
    for src in ("cardrush", "hareruya"):
        if tried[src]:
            print(f"  {src}: {found[src]}/{tried[src]} con prezzo")

    # Rilevamento rotture: se un sito interrogato non ha dato NESSUN prezzo,
    # probabilmente ha cambiato layout o ci sta bloccando. Usciamo con errore
    # cosi' in GitHub Actions il workflow fallisce e arriva la notifica.
    broken = [s for s in ("cardrush", "hareruya") if tried[s] and found[s] == 0]
    if broken:
        print(f"\nATTENZIONE: nessun prezzo trovato per: {', '.join(broken)}.")
        print("Possibile cambio layout del sito o blocco IP. Controllare scrapers.py.")
        sys.exit(2)


if __name__ == "__main__":
    main()
