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
import adapters as ad

HERE = os.path.dirname(__file__)
DATA_DIR = os.path.join(HERE, "..", "dashboard", "data")
LEGACY_JSON = os.path.join(HERE, "..", "dashboard", "buylist_live.json")


def main():
    ap = argparse.ArgumentParser(description="TCG Tracker - scraping buying prices")
    sources = [a.source_code for a in ad.ADAPTERS]
    ap.add_argument("--set", help="filtra per pack_code, es. S12A")
    ap.add_argument("--game", help="filtra per gioco, es. pokemon / onepiece / yugioh")
    ap.add_argument("--limit", type=int, help="max carte (test)")
    ap.add_argument("--only", choices=sources, help="una sola fonte")
    ap.add_argument("--sleep", type=float, default=1.0, help="pausa secondi tra richieste")
    args = ap.parse_args()

    if not os.path.exists(db.DB_PATH):
        print("Database non trovato. Esegui prima:  python init_db.py")
        sys.exit(1)

    conn = db.get_conn()
    cards = db.fetch_cards(conn)
    if args.set:
        cards = [c for c in cards if c["pack_code"].upper() == args.set.upper()]
    if args.game:
        cards = [c for c in cards if c["game_code"].lower() == args.game.lower()]
    if args.limit:
        cards = cards[: args.limit]

    # Un solo client HTTP condiviso: centralizza timeout, retry+backoff,
    # User-Agent e rate-limiting (la pausa tra richieste e' --sleep).
    client = sc.HttpClient(rate_limit=args.sleep)

    # Adapter candidati (filtrati da --only). La fonte giusta per ogni carta si
    # sceglie poi per GIOCO (a.supports): es. Hareruya solo Pokémon, Yuyu-tei OP.
    candidates = ad.get_adapters(args.only)
    all_sources = [a.source_code for a in candidates]

    print(f"Carte da elaborare: {len(cards)}\n")
    # contatori per fonte: servono a capire se un sito ha smesso di rispondere
    tried = {s: 0 for s in all_sources}
    found = {s: 0 for s in all_sources}
    # errori di LAYOUT (struttura della pagina cambiata): distinti dal semplice
    # "carta non trovata", servono per un allarme piu' fine (vedi sotto).
    layout_err = {s: 0 for s in all_sources}

    for i, c in enumerate(cards, 1):
        print(f"[{i}/{len(cards)}] {c['card_code']}  ({c['pack_code']})")
        for a in candidates:
            if not a.supports(c["game_code"]):
                continue
            src = a.source_code
            try:
                offer = a.scrape(c, client)         # Offer | None
            except sc.LayoutError as e:
                layout_err[src] += 1
                offer = None
                print(f"    {src} : LAYOUT? {e}")
            price = offer.price if offer else None
            stock = offer.in_stock if offer else False
            db.save_price(conn, c["id"], src, price, stock)
            tried[src] += 1
            found[src] += price is not None
            print(f"    {src} : {price if price is not None else '—'}")

    n = db.export_web(conn, DATA_DIR)
    db.export_buylist_json(conn, LEGACY_JSON)   # retro-compatibilita' standalone
    conn.close()

    print(f"\nFatto. {n} righe esportate in dashboard/data/")
    for src in tried:
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
    for s in tried:
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
