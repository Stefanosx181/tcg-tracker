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
import time
import random
import argparse
import requests

sys.path.insert(0, os.path.dirname(__file__))
import database as db
import scrapers as sc
import adapters as ad
import build_catalog as bc

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
    ap.add_argument("--harvest-pokemon", action="store_true",
                    help="cataloga TUTTE le singole Pokemon da CardRush "
                         "(catalogo + prezzi CardRush in una passata) ed esci")
    ap.add_argument("--images", action="store_true",
                    help="con --harvest-pokemon: scarica le immagini in locale "
                         "(default: salva solo l'URL remoto CDN, niente git bloat)")
    ap.add_argument("--batch", type=int,
                    help="processa solo N carte scelte per STALENESS della fonte "
                         "(--only): sharding notturno di Hareruya su piu' run")
    ap.add_argument("--jitter", type=float, default=0.0,
                    help="secondi casuali extra [0,jitter] tra una carta e l'altra (credibilita')")
    ap.add_argument("--no-set-pages", action="store_true",
                    help="Hareruya: disabilita la modalita' pagina-set (torna alla "
                         "ricerca per-carta, lenta). Default: pagina-set abilitata.")
    ap.add_argument("--set-gap", type=float, default=0.0,
                    help="pausa casuale extra [0,set_gap] al cambio di set")
    args = ap.parse_args()

    if not os.path.exists(db.DB_PATH):
        print("Database non trovato. Esegui prima:  python init_db.py")
        sys.exit(1)

    conn = db.get_conn()
    # registra le sorgenti del registry (FK di tcg_price) se mancano: cosi'
    # aggiungere un adapter (es. Toretoku) non rompe save_price.
    for a in ad.ADAPTERS:
        conn.execute("INSERT OR IGNORE INTO tcg_source (source_code, display_name) VALUES (?,?)",
                     (a.source_code, a.display_name))
    conn.commit()

    # Un solo client HTTP condiviso: centralizza timeout, retry+backoff,
    # User-Agent e rate-limiting (la pausa tra richieste e' --sleep).
    client = sc.HttpClient(rate_limit=args.sleep)

    # --- HARVEST Pokemon: catalogo + prezzi CardRush in una sola passata -------
    # La lista buyback CardRush e' fonte di catalogo E di prezzo: una scansione
    # paginata da' tutte le singole con prezzo+immagine. Sostituisce le fetch
    # per-carta su CardRush (Hareruya resta per-carta, shardato con --batch).
    if args.harvest_pokemon:
        images_dir = os.path.join(HERE, "..", "dashboard", "images") if args.images else None
        print("Harvest CardRush Pokemon (catalogo + prezzi)...")
        # NB: l'endpoint-LISTA di CardRush blocca gli IP datacenter (GitHub Actions, 403):
        # da li' l'harvest funziona solo via PROXY residenziale (env SCRAPER_PROXY) o dal PC.
        # Gestione con grazia: niente traceback; in CI esce 2 per notificare (vedi sotto).
        _proxy = os.environ.get("SCRAPER_PROXY")
        hclient = sc.HttpClient(rate_limit=args.sleep,
                                proxies={"http": _proxy, "https": _proxy} if _proxy else None)
        if _proxy:
            print("  (uso SCRAPER_PROXY per l'endpoint-lista)")
        try:
            stats = bc.harvest_pokemon_cardrush(
                conn, client=hclient, images_dir=images_dir,
                progress=lambda p, last: (p % 10 == 0 or p == last)
                and print(f"  pagina {p}/{last}"))
        except (requests.RequestException, sc.LayoutError) as e:
            conn.close()
            print(f"\nHarvest SALTATO: la lista buyback CardRush non e' raggiungibile da qui ({e}).")
            # In CI (job di scoperta) un blocco e' un ERRORE da notificare; in locale
            # (PC) e' un'uscita pulita (li' la lista funziona, un blip non deve sporcare).
            if os.environ.get("CI"):
                print("In CI l'endpoint-lista risulta bloccato (403?): esco con codice 2 per notificare.")
                sys.exit(2)
            print("Probabile blocco IP datacenter: eseguilo dal PC -> py src/run.py --harvest-pokemon")
            return
        n = db.export_web(conn, DATA_DIR)
        db.export_buylist_json(conn, LEGACY_JSON)
        conn.close()
        print(f"\nCatalogo: {stats['catalog']} singole "
              f"({stats['inserted']} nuove, {stats['updated']} aggiornate), "
              f"prezzi CR {stats['priced']}, immagini {stats['images']}.")
        print(f"{n} righe esportate in dashboard/data/.")
        return

    # --- selezione carte da scrapare ------------------------------------------
    # --batch + --only -> selezione per STALENESS della fonte (sharding notturno);
    # altrimenti elenco completo con i filtri classici.
    if args.batch and args.only:
        cards = db.fetch_cards_stale(conn, args.only, args.game, args.batch)
        if args.set:
            cards = [c for c in cards if c["pack_code"].upper() == args.set.upper()]
    else:
        cards = db.fetch_cards(conn)
        if args.set:
            cards = [c for c in cards if c["pack_code"].upper() == args.set.upper()]
        if args.game:
            cards = [c for c in cards if c["game_code"].lower() == args.game.lower()]
        if args.batch:
            cards = cards[: args.batch]
        if args.limit:
            cards = cards[: args.limit]

    # Adapter candidati (filtrati da --only). La fonte giusta per ogni carta si
    # sceglie poi per GIOCO (a.supports): es. Hareruya solo Pokémon, Yuyu-tei OP.
    candidates = ad.get_adapters(args.only)
    # Hareruya: modalita' PAGINA-SET (una richiesta per espansione, in cache) invece
    # della ricerca per-carta -> da ~ore a minuti. Fallback automatico per-carta sui
    # set non mappati. Si puo' disabilitare con --no-set-pages.
    if not getattr(args, "no_set_pages", False):
        for a in candidates:
            if getattr(a, "source_code", "") == "hareruya":
                a.use_set_pages = True
    all_sources = [a.source_code for a in candidates]

    print(f"Carte da elaborare: {len(cards)}\n")
    # contatori per fonte: servono a capire se un sito ha smesso di rispondere
    tried = {s: 0 for s in all_sources}
    found = {s: 0 for s in all_sources}
    # errori di LAYOUT (struttura della pagina cambiata) e di RETE/HTTP (403, timeout):
    # distinti dal "carta non trovata" (risposta pulita ma nessun buyback). L'allarme
    # rottura si basa su QUESTI, non su "0 prezzi": col catalogo completo molte carte
    # low-value non sono ricomprate da una fonte (0 prezzi LEGITTIMO), mentre un blocco
    # 403 alza il tasso di ERRORI.
    layout_err = {s: 0 for s in all_sources}
    net_err = {s: 0 for s in all_sources}

    prev_pack = None
    for i, c in enumerate(cards, 1):
        # pacing credibile: pausa piu' lunga quando cambia il set (traffico "umano")
        if args.set_gap and prev_pack is not None and c["pack_code"] != prev_pack:
            time.sleep(random.uniform(0, args.set_gap))
        prev_pack = c["pack_code"]
        print(f"[{i}/{len(cards)}] {c['card_code'] or c['number']}  ({c['pack_code']})")
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
            except requests.RequestException as e:
                net_err[src] += 1
                offer = None
                print(f"    {src} : errore rete {e}")
            price = offer.price if offer else None
            stock = offer.in_stock if offer else False
            db.save_price(conn, c["id"], src, price, stock)
            tried[src] += 1
            found[src] += price is not None
            print(f"    {src} : {price if price is not None else '—'}")
        # jitter tra una carta e l'altra (oltre al rate-limit fisso del client)
        if args.jitter:
            time.sleep(random.uniform(0, args.jitter))

    n = db.export_web(conn, DATA_DIR)
    db.export_buylist_json(conn, LEGACY_JSON)   # retro-compatibilita' standalone
    conn.close()

    print(f"\nFatto. {n} righe esportate in dashboard/data/")
    for src in tried:
        if tried[src]:
            extra = []
            if net_err[src]:
                extra.append(f"errori rete {net_err[src]}")
            if layout_err[src]:
                extra.append(f"layout? {layout_err[src]}")
            tail = f" ({', '.join(extra)})" if extra else ""
            print(f"  {src}: {found[src]}/{tried[src]} con prezzo{tail}")

    # Rilevamento ROTTURE basato sul tasso di ERRORI, NON su "0 prezzi":
    #   - net_err alto  -> la fonte risponde male (403/blocco IP, timeout) su molte richieste;
    #   - layout_err alto -> la struttura della pagina e' cambiata.
    # "0 prezzi con risposte pulite" NON e' rottura: col catalogo completo molte carte
    # non sono ricomprate da una fonte (Hareruya non compra le low-value, ecc.).
    # In caso di rottura usciamo con errore -> in GitHub Actions il job fallisce e notifica.
    ERR_FRACTION = 0.50      # >50% delle richieste di una fonte in errore rete/HTTP
    LAYOUT_FRACTION = 0.30   # >30% con struttura cambiata
    broken = []
    for s in tried:
        if not tried[s]:
            continue
        if net_err[s] >= max(5, ERR_FRACTION * tried[s]):
            broken.append(f"{s} ({net_err[s]}/{tried[s]} errori rete/403 — blocco?)")
        elif layout_err[s] >= max(3, LAYOUT_FRACTION * tried[s]):
            broken.append(f"{s} ({layout_err[s]}/{tried[s]} layout cambiato)")
    if broken:
        print(f"\nATTENZIONE: possibile rottura scraper: {', '.join(broken)}.")
        print("Probabile cambio layout o blocco IP/403. Controllare scrapers.py / fonti.")
        sys.exit(2)


if __name__ == "__main__":
    main()
