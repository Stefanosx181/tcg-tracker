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

    # Un solo client HTTP condiviso: centralizza timeout, retry+backoff,
    # User-Agent e rate-limiting (la pausa tra richieste e' --sleep).
    client = sc.HttpClient(rate_limit=args.sleep)

    print(f"Carte da elaborare: {len(cards)}\n")
    # contatori per fonte: servono a capire se un sito ha smesso di rispondere
    tried = {"cardrush": 0, "hareruya": 0}
    found = {"cardrush": 0, "hareruya": 0}
    # errori di LAYOUT (struttura della pagina cambiata): distinti dal semplice
    # "carta non trovata", servono per un allarme piu' fine (vedi sotto).
    layout_err = {"cardrush": 0, "hareruya": 0}

    def _scrape(src, fn):
        """Esegue lo scrape di una fonte gestendo il LayoutError separatamente.
        Ritorna (price, stock); su layout cambiato ritorna (None, False) ma
        incrementa layout_err[src]."""
        try:
            return fn()
        except sc.LayoutError as e:
            layout_err[src] += 1
            print(f"    {src} : LAYOUT? {e}")
            return None, False

    for i, c in enumerate(cards, 1):
        print(f"[{i}/{len(cards)}] {c['card_code']}  ({c['pack_code']})")

        if args.only != "hareruya":
            price, stock = _scrape("cardrush",
                lambda: sc.scrape_cardrush(c["cardrush_url"], client=client))
            db.save_price(conn, c["id"], "cardrush", price, stock)
            tried["cardrush"] += 1
            found["cardrush"] += price is not None
            print(f"    cardrush : {price if price is not None else '—'}")

        if args.only != "cardrush":
            price, stock = _scrape("hareruya",
                lambda: sc.scrape_hareruya(c["card_code"], c["pack_code"],
                                           c["model_number"], client=client))
            db.save_price(conn, c["id"], "hareruya", price, stock)
            tried["hareruya"] += 1
            found["hareruya"] += price is not None
            print(f"    hareruya : {price if price is not None else '—'}")

    n = db.export_web(conn, DATA_DIR)
    db.export_buylist_json(conn, LEGACY_JSON)   # retro-compatibilita' standalone
    conn.close()

    print(f"\nFatto. {n} righe esportate in dashboard/data/")
    for src in ("cardrush", "hareruya"):
        if tried[src]:
            le = f", layout? {layout_err[src]}" if layout_err[src] else ""
            print(f"  {src}: {found[src]}/{tried[src]} con prezzo{le}")

    # Rilevamento rotture (due segnali, piu' fine del solo conteggio a zero):
    #   1) NESSUN prezzo trovato per una fonte interrogata (blocco totale);
    #   2) molte pagine con STRUTTURA cambiata (LayoutError oltre una soglia):
    #      cattura le rotture PARZIALI che prima passavano inosservate.
    # In entrambi i casi usciamo con errore: in GitHub Actions il workflow
    # fallisce e arriva la notifica.
    LAYOUT_FRACTION = 0.30   # >30% delle pagine di una fonte con layout rotto
    broken = []
    for s in ("cardrush", "hareruya"):
        if not tried[s]:
            continue
        if found[s] == 0:
            broken.append(f"{s} (0 prezzi)")
        elif layout_err[s] >= max(3, LAYOUT_FRACTION * tried[s]):
            broken.append(f"{s} ({layout_err[s]}/{tried[s]} layout cambiato)")
    if broken:
        print(f"\nATTENZIONE: possibile rottura scraper: {', '.join(broken)}.")
        print("Possibile cambio layout del sito o blocco IP. Controllare scrapers.py.")
        sys.exit(2)


if __name__ == "__main__":
    main()
