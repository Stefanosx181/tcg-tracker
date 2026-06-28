"""
build_catalog.py - Costruisce il CATALOGO carte di un set (One Piece / Yu-Gi-Oh)
dalla pagina-set buyback di Yuyu-tei e lo inserisce nel DB v2.

Perche': lo scraper (run.py) NON scopre le carte da solo, legge l'elenco dal DB.
Per i Pokemon l'elenco arriva dall'Excel; per OP/YGO non esiste. La pagina-set
di Yuyu-tei (/buy/{opc|ygo}/s/{set}) pero' elenca TUTTE le carte del set: la
usiamo come sorgente del catalogo (numero + nome), poi lo scraping ne prende i prezzi.

Identita' canonica per carta = (set, number, variant). variant='parallel' se il
nome contiene パラレル, altrimenti '' (standard). Stesso numero standard+parallel =
due righe; piu' stampe della stessa (number,variant) collassano in una (lo scraper
sceglie poi il prezzo, come per i Pokemon). Idempotente: INSERT OR IGNORE.

Uso:
  python src/build_catalog.py onepiece OP01 "ROMANCE DAWN"
  python src/build_catalog.py yugioh QCCU "Quarter Century" --html tests/fixtures/yuyutei_ygo_qccu.html
  (--html FILE = cataloga OFFLINE da una fixture; --db FILE = altro database)
"""
import os
import sys
import argparse
import urllib.parse as urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scrapers as sc          # noqa: E402
import adapters as ad          # noqa: E402
import database as db          # noqa: E402

# cartella immagini della dashboard (stessa dei Pokemon)
_DEFAULT_IMAGES = os.path.join(HERE, "..", "dashboard", "images")

# categoria CardRush per gioco (per costruire l'URL buyback per-carta)
CARDRUSH_CAT = {"onepiece": "onepiece", "yugioh": "yugioh", "pokemon": "pokemon"}
# nome leggibile gioco (per tcg_game.display_name se va creato)
GAME_NAME = {"onepiece": "One Piece Card Game", "yugioh": "Yu-Gi-Oh! OCG",
             "pokemon": "Pokémon"}


def _variant_of(name: str) -> str:
    """Variante canonica dal nome Yuyu-tei: 'parallel' se marcato パラレル, else ''."""
    return "parallel" if name and "パラレル" in name else ""


def _cardrush_url(game_code: str, number: str) -> str:
    cat = CARDRUSH_CAT.get(game_code, game_code)
    return f"https://cardrush.media/{cat}/buying_prices?model_number={number}"


def _yuyutei_url(game_code: str, set_code: str) -> str:
    seg = ad.YuyuteiAdapter.GAME_SEGMENT.get(game_code)
    return ad.YuyuteiAdapter.BASE.format(seg=seg, set_code=set_code.lower())


def _download_image(url, images_dir, number, variant, client):
    """Scarica l'immagine carta in images_dir e ritorna il path RELATIVO
    (es. 'images/OP01-120.jpg') da salvare in tcg_card.image_url. Idempotente:
    se il file esiste gia' non riscarica. Ritorna None se il download fallisce."""
    import os as _os
    ext = _os.path.splitext(urlparse.urlparse(url).path)[1] or ".jpg"
    fname = f"{number}{'_p' if variant == 'parallel' else ''}{ext}"
    dest = _os.path.join(images_dir, fname)
    rel = "images/" + fname
    if _os.path.exists(dest):
        return rel
    try:
        data = client.get(url).content
    except Exception as e:                       # rete/HTTP: non bloccare il catalogo
        print(f"    img KO {number}: {e}")
        return None
    _os.makedirs(images_dir, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return rel


def _ensure_set(conn, game_code, set_code, set_name, display_order):
    conn.execute("INSERT OR IGNORE INTO tcg_game (game_code, display_name) VALUES (?,?)",
                 (game_code, GAME_NAME.get(game_code, game_code)))
    conn.execute("INSERT OR IGNORE INTO tcg_source (source_code, display_name) VALUES (?,?)",
                 ("yuyutei", "Yuyu-tei"))
    conn.execute("INSERT OR IGNORE INTO tcg_source (source_code, display_name) VALUES (?,?)",
                 ("cardrush", "CardRush"))
    conn.execute("""INSERT OR IGNORE INTO tcg_set (game_code, set_code, set_name, display_order)
                    VALUES (?,?,?,?)""", (game_code, set_code, set_name, display_order))
    row = conn.execute("SELECT id FROM tcg_set WHERE game_code=? AND set_code=?",
                       (game_code, set_code)).fetchone()
    return row[0]


def harvest(conn, game_code, set_code, set_name, *,
            html=None, client=None, display_order=100, images_dir=None):
    """Cataloga un set nel DB. Ritorna (inseriti, gia_presenti, righe_pagina).
    Se images_dir e' dato, scarica le immagini carta li' e salva image_url locale."""
    db.ensure_image_column(conn)
    if html is None or images_dir is not None:
        client = client or sc._default_client()
    if html is None:
        html = client.get(_yuyutei_url(game_code, set_code)).text
    items = sc.parse_yuyutei(html)      # puo' sollevare LayoutError
    set_id = _ensure_set(conn, game_code, set_code, set_name, display_order)

    seen = set()
    inserted = skipped = images = 0
    for it in items:
        number = (it.get("number") or "").strip()
        name = (it.get("name") or "").strip()
        if not number:
            continue
        variant = _variant_of(name)
        key = (number, variant)
        if key in seen:                  # piu' stampe stessa (number,variant): una sola carta
            continue
        seen.add(key)
        # Identita' carta = (set, number, variant). NON usiamo INSERT OR IGNORE:
        # il vincolo UNIQUE di tcg_card include anche rarity, quindi dopo un
        # arricchimento rarità un re-harvest creerebbe DUPLICATI. Controllo esplicito.
        row = conn.execute("""SELECT id FROM tcg_card
                              WHERE set_id=? AND number=? AND variant=?""",
                           (set_id, number, variant)).fetchone()
        if row:
            skipped += 1
        else:
            conn.execute("""INSERT INTO tcg_card
                  (set_id, number, language, rarity, variant, name, name_en, cardrush_url)
                VALUES (?,?,?,?,?,?,?,?)""",
                (set_id, number, "JP", "", variant, name, None,
                 _cardrush_url(game_code, number)))
            inserted += 1
        # immagine: scarica (se richiesto) e salva il path locale; UPDATE cosi'
        # aggiorna anche le carte gia' presenti. SENZA --images salviamo l'URL
        # remoto SOLO come fallback: NON sovrascriviamo un'immagine locale gia'
        # scaricata (altrimenti un run --rarity cancellerebbe i path 'images/...').
        img = it.get("image")
        if img:
            if images_dir:
                stored = _download_image(img, images_dir, number, variant, client)
                if stored:
                    conn.execute("""UPDATE tcg_card SET image_url=?
                                    WHERE set_id=? AND number=? AND variant=?""",
                                 (stored, set_id, number, variant))
                    images += 1
            else:
                cur2 = conn.execute("""UPDATE tcg_card SET image_url=?
                        WHERE set_id=? AND number=? AND variant=?
                        AND (image_url IS NULL OR image_url NOT LIKE 'images/%')""",
                        (img, set_id, number, variant))
                images += cur2.rowcount
    conn.commit()
    return inserted, skipped, len(items), images


# Sigle corte per le rarita' verbose (soprattutto Yu-Gi-Oh in giapponese), cosi'
# il badge nella UI resta leggibile. Le rarita' One Piece sono gia' corte (L, SR/P...).
_RARITY_SHORT = {
    "クォーターセンチュリーシークレット": "QCSE",
    "プリズマティックシークレット": "PSE",
    "ホログラフィック": "HR",
    "アルティメット": "UL",
    "シークレット": "SE",
    "ウルトラ": "UR",
    "スーパー": "SR",
    "ノーマルレア": "NR",
    "レア": "R",
    "ノーマル": "N",
}


def _short_rarity(rar):
    """Rarita' grezza -> sigla corta (mappa nota); invariata se gia' corta/sconosciuta."""
    if not rar:
        return rar
    return _RARITY_SHORT.get(rar.strip(), rar.strip())


def _pick_rarity(items, number, variant):
    """Dagli item CardRush sceglie la rarita' della carta (number+variant).
    Preferisce l'item con/ senza marcatore パラレル coerente con la variante."""
    is_par_target = (variant == "parallel")
    matched = []
    for it in items:
        if not isinstance(it, dict):
            continue
        model = str(it.get("model_number", ""))
        if not (model == number or model.split("/")[0] == number):
            continue
        is_par = "パラレル" in (it.get("extra_difference") or "")
        (matched if is_par == is_par_target else []).append(it)
    pool = matched or [it for it in items if isinstance(it, dict)
                       and str(it.get("model_number", "")) == number]
    for it in pool:
        if it.get("rarity"):
            return it.get("rarity")
    return None


def enrich_rarity(conn, game_code, set_code, *, client=None):
    """Riempie tcg_card.rarity per le carte del set leggendola da CardRush
    (la fonte espone `rarity`). Ritorna (aggiornate, totali)."""
    client = client or sc._default_client()
    rows = conn.execute("""SELECT c.id, c.number, c.variant, c.cardrush_url
                           FROM tcg_card c JOIN tcg_set s ON s.id = c.set_id
                           WHERE s.game_code=? AND s.set_code=?""",
                        (game_code, set_code)).fetchall()
    updated = 0
    for cid, number, variant, url in rows:
        if not url:
            continue
        try:
            items = sc.parse_cardrush(client.get(url).text)
        except Exception as e:
            print(f"    rarity KO {number}: {e}")
            continue
        rar = _short_rarity(_pick_rarity(items, number, variant or ""))
        if rar:
            conn.execute("UPDATE tcg_card SET rarity=? WHERE id=?", (rar, cid))
            updated += 1
    conn.commit()
    return updated, len(rows)


def main(argv):
    ap = argparse.ArgumentParser(description="Cataloga un set OP/YGO da Yuyu-tei nel DB v2.")
    ap.add_argument("game", choices=["onepiece", "yugioh", "pokemon"])
    ap.add_argument("set_code")
    ap.add_argument("set_name")
    ap.add_argument("--html", help="cataloga OFFLINE da questo file HTML (fixture)")
    ap.add_argument("--db", help="percorso DB (default: il DB reale)")
    ap.add_argument("--order", type=int, default=100, help="display_order del set")
    ap.add_argument("--images", metavar="DIR", nargs="?", const=_DEFAULT_IMAGES,
                    help="scarica le immagini carta in DIR (default dashboard/images)")
    ap.add_argument("--rarity", action="store_true",
                    help="riempi la rarita' delle carte del set da CardRush")
    args = ap.parse_args(argv)

    conn = db.get_conn() if not args.db else __import__("sqlite3").connect(args.db)
    try:
        html = open(args.html, encoding="utf-8").read() if args.html else None
        ins, skip, rows, imgs = harvest(conn, args.game, args.set_code, args.set_name,
                                        html=html, display_order=args.order,
                                        images_dir=args.images)
        extra = f", {imgs} immagini" if args.images else ""
        print(f"{args.game}/{args.set_code}: pagina {rows} righe -> "
              f"{ins} carte nuove, {skip} gia' presenti{extra}.")
        if args.rarity:
            up, tot = enrich_rarity(conn, args.game, args.set_code)
            print(f"  rarita': {up}/{tot} carte aggiornate da CardRush.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
