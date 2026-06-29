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
import re
import sys
import argparse
import urllib.parse as urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scrapers as sc          # noqa: E402
import adapters as ad          # noqa: E402
import database as db          # noqa: E402
import op_match as om          # noqa: E402

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


# ----------------------------------------------------------------------
# POKEMON: catalogo COMPLETO dalla lista buyback CardRush (paginata)
# ----------------------------------------------------------------------
# A differenza di OP/YGO (catalogo da Yuyu-tei), per i Pokemon la fonte del
# catalogo E dei prezzi e' la STESSA lista buyback di CardRush: una sola
# scansione paginata da' tutte le singole con prezzo+immagine. Cosi' non serve
# l'elenco curato dall'Excel: il catalogo = tutte le carte che CardRush ricompra.
# URL-lista nella forma COMPLETA della SPA (vedi sc.pokemon_cardrush_url): anti-403.
def _pokemon_list_url(page):
    return sc.pokemon_cardrush_url(page=page)
# placeholder set per le voci CardRush senza pack_code (promo varie, old-back sfusi)
_POKEMON_OTHER_SET = "その他"


def _pokemon_catalog_from_items(items):
    """PURA (no rete/DB): lista di item buyingPrices CardRush -> dict
    {(set_code, number): scelta}. Tiene SOLO le singole (product_category シングル).

    Per ogni (set, number) sceglie la STAMPA STANDARD (extra_difference vuoto) col
    prezzo piu' alto; se non esiste alcuna standard ripiega sulla variante col prezzo
    piu' alto (cosi' la carta esiste comunque, come fa pick_cardrush). pack_code vuoto
    -> set placeholder その他. Il valore scelto porta number/name/rarity/price/image."""
    best = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("product_category") != "シングル":
            continue
        number = str(it.get("model_number") or "").strip()
        if not number:
            continue
        set_code = (it.get("pack_code") or "").strip() or _POKEMON_OTHER_SET
        try:
            price = int(float(it["amount"])) if it.get("amount") is not None else None
        except (TypeError, ValueError):
            price = None
        rarity = (it.get("rarity") or "").strip()
        if rarity == "-":
            rarity = ""
        op = it.get("ocha_product")
        image = op.get("image_source") if isinstance(op, dict) else None
        is_std = not (it.get("extra_difference") or "").strip()
        cand = {"set_code": set_code, "set_name": (it.get("pack_name") or "").strip(),
                "number": number, "name": (it.get("name") or "").strip(),
                "rarity": rarity, "price": price, "image": image, "is_std": is_std}
        cur = best.get((set_code, number))
        # preferisci la standard; a parita' di classe il prezzo piu' alto
        score = (cand["is_std"], cand["price"] or 0)
        if cur is None or score > (cur["is_std"], cur["price"] or 0):
            best[(set_code, number)] = cand
    return best


def _ensure_pokemon_set(conn, set_code, set_name):
    """set_id del set Pokemon (crealo se manca, APPENDENDO il display_order dopo
    gli esistenti). NON sovrascrive il set_name dei set gia' presenti (i nomi EN
    curati restano). Ritorna l'id."""
    conn.execute("INSERT OR IGNORE INTO tcg_game (game_code, display_name) VALUES ('pokemon', ?)",
                 (GAME_NAME["pokemon"],))
    row = conn.execute("SELECT id FROM tcg_set WHERE game_code='pokemon' AND set_code=?",
                       (set_code,)).fetchone()
    if row:
        return row[0]
    order = conn.execute(
        "SELECT COALESCE(MAX(display_order), 0) + 1 FROM tcg_set WHERE game_code='pokemon'"
    ).fetchone()[0]
    conn.execute("""INSERT INTO tcg_set (game_code, set_code, set_name, display_order)
                    VALUES ('pokemon', ?, ?, ?)""", (set_code, set_name or set_code, order))
    return conn.execute("SELECT id FROM tcg_set WHERE game_code='pokemon' AND set_code=?",
                        (set_code,)).fetchone()[0]


def _apply_image(conn, cid, card_image, *, images_dir, number, client):
    """Aggancia l'immagine alla carta cid secondo la policy LAZY:
      - images_dir dato -> scarica in locale, image_url = path 'images/...';
      - altrimenti       -> salva l'URL remoto CDN, SENZA pero' sovrascrivere un
                            eventuale path locale 'images/%' gia' presente.
    Ritorna 1 se ha (ri)scritto image_url, 0 altrimenti."""
    if not card_image:
        return 0
    if images_dir:
        stored = _download_image(card_image, images_dir, number, "", client)
        if stored:
            conn.execute("UPDATE tcg_card SET image_url=? WHERE id=?", (stored, cid))
            return 1
        return 0
    cur = conn.execute("""UPDATE tcg_card SET image_url=?
            WHERE id=? AND (image_url IS NULL OR image_url NOT LIKE 'images/%')""",
            (card_image, cid))
    return cur.rowcount


def harvest_pokemon_cardrush(conn, *, client=None, fetch_page=None, max_pages=None,
                             images_dir=None, save_prices=True, run_date=None,
                             progress=None):
    """Cataloga TUTTE le singole Pokemon dalla lista buyback CardRush e ne salva
    il prezzo nella STESSA passata. Idempotente e NON distruttivo:

      - identita' carta = (set, number, variant='') -> UPSERT con controllo
        esplicito (no INSERT OR IGNORE): le carte gia' presenti (es. le 263
        storiche) mantengono id e STORICO, si aggiornano solo nome/rarita'/immagine;
      - prezzo CardRush della carta (stampa standard) salvato via db.save_price
        (confirmed); cosi' una sola scansione = catalogo + prezzi CR di tutti i set;
      - immagini LAZY (vedi _apply_image): URL remoto di default, locale se images_dir.

    fetch_page(page)->html e' iniettabile per i test (offline). max_pages limita le
    pagine (test/debug). Ritorna un dict di conteggi."""
    db.ensure_image_column(conn)
    db.ensure_intelligence_columns(conn)
    # la fonte 'cardrush' deve esistere (FK di tcg_price): rende l'harvest autonomo
    conn.execute("INSERT OR IGNORE INTO tcg_source (source_code, display_name) VALUES ('cardrush','CardRush')")
    client = client or sc._default_client()
    if fetch_page is None:
        def fetch_page(page):
            return client.get(_pokemon_list_url(page)).text

    raw1 = fetch_page(1)
    items = list(sc.parse_cardrush(raw1))           # puo' sollevare LayoutError
    last = sc.cardrush_last_page(raw1) or 1
    if max_pages:
        last = min(last, max_pages)
    for p in range(2, last + 1):
        items.extend(sc.parse_cardrush(fetch_page(p)))
        if progress:
            progress(p, last)

    catalog = _pokemon_catalog_from_items(items)
    inserted = updated = images = priced = 0
    for (set_code, number), c in catalog.items():
        set_id = _ensure_pokemon_set(conn, set_code, c["set_name"])
        row = conn.execute("""SELECT id FROM tcg_card
                              WHERE set_id=? AND number=? AND variant=''""",
                           (set_id, number)).fetchone()
        if row:
            cid = row[0]
            conn.execute("UPDATE tcg_card SET name=?, rarity=? WHERE id=?",
                         (c["name"] or None, c["rarity"], cid))
            updated += 1
        else:
            conn.execute("""INSERT INTO tcg_card
                  (set_id, number, language, rarity, variant, name, name_en,
                   cardrush_url, legacy_model_number)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (set_id, number, "JP", c["rarity"], "", c["name"] or None, None,
                 _cardrush_url("pokemon", number.split("/")[0]), number.split("/")[0]))
            cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            inserted += 1
        # nome-file locale qualificato col set (schema legacy {pack}_{model}): i
        # prefissi-numero NON sono unici tra set diversi -> evita collisioni quando
        # si scarica in locale (per l'URL remoto, default, e' irrilevante).
        images += _apply_image(conn, cid, c["image"], images_dir=images_dir,
                               number=f"{set_code}_{number.split('/')[0]}", client=client)
        if save_prices:
            db.save_price(conn, cid, "cardrush", c["price"],
                          in_stock=c["price"] is not None, run_date=run_date)
            priced += 1
    conn.commit()
    return {"pages": last, "listings": len(items), "catalog": len(catalog),
            "inserted": inserted, "updated": updated, "images": images, "priced": priced}


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


def _pick_item(items, number, variant):
    """Item CardRush della carta per TIER di stampa (base/parallel/super), escluse
    le inserzioni rumore (serial/sigillati/esteri/illust); tra le candidate del tier
    sceglie la stampa principale (prezzo piu' alto)."""
    want_tier = variant or "base"
    cands = []
    for it in items:
        if not isinstance(it, dict):
            continue
        model = str(it.get("model_number", ""))
        if not (model == number or model.split("/")[0] == number):
            continue
        if sc.is_noise_listing(it.get("extra_difference")):
            continue
        if sc.print_tier_cardrush(it.get("rarity"), it.get("extra_difference")) != want_tier:
            continue
        cands.append(it)
    return max(cands, key=lambda it: int(it.get("amount") or 0)) if cands else None


def ensure_op_tier_cards(conn, *, client=None):
    """Per ogni numero One Piece crea le carte mancanti dei TIER 'parallel'/'super'
    presenti su CardRush o Toretoku (la 'base' = variant '' esiste gia'). Cosi' ogni
    stampa ha una carta propria e le fonti la confrontano per tier. Ritorna #aggiunte."""
    client = client or sc._default_client()
    db.ensure_image_column(conn)
    rows = conn.execute("""SELECT c.id, c.set_id, c.number, c.variant, c.name, c.cardrush_url
                           FROM tcg_card c JOIN tcg_set s ON s.id = c.set_id
                           WHERE s.game_code = 'onepiece'""").fetchall()
    by_num = {}
    for cid, set_id, number, variant, name, url in rows:
        by_num.setdefault(number, {})[variant] = (set_id, name, url)
    # Toretoku una volta sola
    tt_tiers = {}
    try:
        for it in sc.parse_toretoku(client.get(ad.ToretokuAdapter.URL).text):
            tt_tiers.setdefault(it["number"], set()).add(sc.print_tier_from_name(it["name"]))
    except Exception as e:
        print(f"  toretoku tiers KO: {e}")
    added = 0
    for number, variants in by_num.items():
        url = next((u for (_, _, u) in variants.values() if u), None)
        tiers = set(tt_tiers.get(number, set()))
        if url:
            try:
                for it in sc.parse_cardrush(client.get(url).text):
                    if str(it.get("model_number")) != number:
                        continue
                    if sc.is_noise_listing(it.get("extra_difference")):
                        continue
                    tiers.add(sc.print_tier_cardrush(it.get("rarity"), it.get("extra_difference")))
            except Exception as e:
                print(f"  cardrush tiers KO {number}: {e}")
        template = variants.get("parallel") or variants.get("") or next(iter(variants.values()))
        set_id, name, t_url = template
        for tier in ("parallel", "super"):
            if tier in tiers and tier not in variants:
                conn.execute("""INSERT INTO tcg_card
                      (set_id, number, language, variant, name, cardrush_url)
                    VALUES (?,?,?,?,?,?)""", (set_id, number, "JP", tier, name, t_url))
                added += 1
    conn.commit()
    return added


def _pick_rarity(items, number, variant):
    it = _pick_item(items, number, variant)
    return it.get("rarity") if it else None


def _cardrush_image(item):
    """URL immagine HI-RES (~564x800) dell'item CardRush (ocha_product.image_source)."""
    op = item.get("ocha_product") if item else None
    return op.get("image_source") if isinstance(op, dict) else None


def enrich_from_cardrush(conn, game_code, set_code, *, client=None, images_dir=None):
    """Da CardRush (una fetch per carta) riempie la RARITÀ e, se images_dir,
    scarica l'IMMAGINE hi-res (~564x800, come i Pokemon) sostituendo quella
    piccola di Yuyu-tei (100x140). Ritorna (rarità, immagini, totali)."""
    db.ensure_image_column(conn)
    client = client or sc._default_client()
    rows = conn.execute("""SELECT c.id, c.number, c.variant, c.cardrush_url
                           FROM tcg_card c JOIN tcg_set s ON s.id = c.set_id
                           WHERE s.game_code=? AND s.set_code=?""",
                        (game_code, set_code)).fetchall()
    rar_n = img_n = 0
    for cid, number, variant, url in rows:
        if not url:
            continue
        try:
            items = sc.parse_cardrush(client.get(url).text)
        except Exception as e:
            print(f"    cardrush KO {number}: {e}")
            continue
        it = _pick_item(items, number, variant or "")
        if not it:
            continue
        rar = _short_rarity(it.get("rarity"))
        if rar:
            conn.execute("UPDATE tcg_card SET rarity=? WHERE id=?", (rar, cid))
            rar_n += 1
        if images_dir:
            src = _cardrush_image(it)
            if src:
                local = _download_image(src, images_dir, number, variant, client)
                if local:
                    conn.execute("UPDATE tcg_card SET image_url=? WHERE id=?", (local, cid))
                    img_n += 1
    conn.commit()
    return rar_n, img_n, len(rows)


def rebuild_onepiece_prints(conn, set_code, set_name, *, client=None,
                            display_order=100, min_single=3000):
    """PRECISIONE MASSIMA One Piece: per ogni numero del set riconcilia le stampe
    CardRush<->Toretoku (op_match.reconcile) e ricostruisce una carta PER STAMPA con
    i prezzi gia' agganciati alla STESSA arte. Tiene le coppie a due fonti + le stampe
    single-fonte di valore (>= min_single). RIMPIAZZA le carte OP del set (i prezzi OP
    sono dati di test recenti). Ritorna (#carte, #coppie a due fonti)."""
    client = client or sc._default_client()
    db.ensure_image_column(conn)
    set_id = _ensure_set(conn, "onepiece", set_code, set_name, display_order)
    conn.execute("INSERT OR IGNORE INTO tcg_source (source_code, display_name) VALUES (?,?)",
                 ("toretoku", "Toretoku"))
    # numeri e nome-base (carattere senza suffisso d'arte) dal catalogo esistente
    rows = conn.execute("SELECT DISTINCT number, name FROM tcg_card WHERE set_id=?",
                        (set_id,)).fetchall()
    base_name = {}
    for number, name in rows:
        clean = re.sub(r"[\(（].*?[\)）]", "", name or "").strip()
        base_name.setdefault(number, clean or number)
    numbers = [n for n in base_name if n and n != "-"]

    tt_items = sc.parse_toretoku(client.get(ad.ToretokuAdapter.URL).text)

    # via le vecchie carte OP del set (e i loro prezzi recenti): rimpiazzo per-stampa
    conn.execute("DELETE FROM tcg_price WHERE card_id IN (SELECT id FROM tcg_card WHERE set_id=?)",
                 (set_id,))
    conn.execute("DELETE FROM tcg_card WHERE set_id=?", (set_id,))
    conn.commit()

    images_dir = _DEFAULT_IMAGES
    tier_rarity = {"base": "", "parallel": "P", "super": "SP"}
    cards = pairs = 0
    for number in numbers:
        cr_items = sc.parse_cardrush(client.get(_cardrush_url("onepiece", number)).text)
        cr = om._cardrush_listings(cr_items, number)
        tt = om._toretoku_listings(tt_items, number)
        # una immagine per numero (dal listing CardRush), condivisa dalle sue stampe
        img_url = None
        for it in cr_items:
            if str(it.get("model_number")) == number:
                op = it.get("ocha_product") or {}
                src = op.get("image_source") if isinstance(op, dict) else None
                if src:
                    img_url = _download_image(src, images_dir, number, "", client)
                    break
        for p in om.reconcile(cr, tt):
            both = p["cardrush"] and p["toretoku"]
            if not both and max(p["cardrush"] or 0, p["toretoku"] or 0) < min_single:
                continue
            art = "/".join(sorted(p["art"]))
            variant = p["tier"] + ("#" + art if art else "")
            name = base_name[number] + (f" ({art})" if art else "")
            conn.execute("""INSERT INTO tcg_card
                  (set_id, number, language, rarity, variant, name, cardrush_url, image_url)
                VALUES (?,?,?,?,?,?,?,?)""",
                (set_id, number, "JP", tier_rarity.get(p["tier"], ""),
                 variant[:120], name[:200], _cardrush_url("onepiece", number), img_url))
            cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            if p["cardrush"]:
                db.save_price(conn, cid, "cardrush", p["cardrush"])
            if p["toretoku"]:
                db.save_price(conn, cid, "toretoku", p["toretoku"])
            cards += 1
            pairs += 1 if both else 0
    conn.commit()
    return cards, pairs


def main(argv):
    ap = argparse.ArgumentParser(description="Cataloga un set OP/YGO da Yuyu-tei nel DB v2.")
    ap.add_argument("game", choices=["onepiece", "yugioh", "pokemon"])
    ap.add_argument("set_code")
    ap.add_argument("set_name")
    ap.add_argument("--html", help="cataloga OFFLINE da questo file HTML (fixture)")
    ap.add_argument("--db", help="percorso DB (default: il DB reale)")
    ap.add_argument("--order", type=int, default=100, help="display_order del set")
    ap.add_argument("--images", metavar="DIR", nargs="?", const=_DEFAULT_IMAGES,
                    help="scarica le immagini HI-RES da CardRush in DIR (default dashboard/images)")
    ap.add_argument("--rarity", action="store_true",
                    help="riempi la rarita' delle carte del set da CardRush")
    args = ap.parse_args(argv)

    conn = db.get_conn() if not args.db else __import__("sqlite3").connect(args.db)
    try:
        html = open(args.html, encoding="utf-8").read() if args.html else None
        ins, skip, rows, _ = harvest(conn, args.game, args.set_code, args.set_name,
                                     html=html, display_order=args.order)
        print(f"{args.game}/{args.set_code}: pagina {rows} righe -> "
              f"{ins} carte nuove, {skip} gia' presenti.")
        # rarita' e/o immagini hi-res da CardRush (una sola fetch per carta)
        if args.images or args.rarity:
            rar_n, img_n, tot = enrich_from_cardrush(
                conn, args.game, args.set_code, images_dir=args.images or None)
            msg = f"  CardRush: rarità {rar_n}/{tot}"
            if args.images:
                msg += f", immagini {img_n}/{tot}"
            print(msg + ".")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
