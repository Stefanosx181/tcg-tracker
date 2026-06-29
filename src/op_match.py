"""
op_match.py - Riconciliazione per-STAMPA One Piece (precisione massima).

Lo stesso numero ha piu' stampe; CardRush e' fine (tante arti/illustratori),
Toretoku piu' grezzo. Per confrontare la STESSA stampa, dentro ogni TIER
(base/parallel/super) accoppiamo le inserzioni delle due fonti per SIMILARITA'
dei token d'arte (es. 海賊旗背景 ↔ 海賊旗背景), accoppiando per primi i pair piu'
simili. Le inserzioni senza pari (arte esclusiva di una fonte: illust:..., stampe
che l'altro negozio non prezza) restano single-fonte -> niente confronto fuorviante.

Funzioni PURE e testabili offline. L'integrazione (catalogo + save_price) e' a parte.
"""
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scrapers as sc  # noqa: E402

_SPLIT = re.compile(r"[\/／]")


def art_tokens(text):
    """Token d'arte di una stampa (esclusi il marker tier パラレル e il rumore)."""
    out = set()
    for p in _SPLIT.split(text or ""):
        p = p.strip()
        if not p or p == "パラレル" or sc.is_noise_listing(p):
            continue
        out.add(p)
    return frozenset(out)


def _cardrush_listings(items, number):
    """[{tier, art, price}] per le inserzioni CardRush pulite del numero."""
    out = []
    for it in items:
        if not isinstance(it, dict) or str(it.get("model_number", "")) != number:
            continue
        extra = it.get("extra_difference") or ""
        if sc.is_noise_listing(extra):
            continue
        try:
            price = int(float(it.get("amount")))
        except (TypeError, ValueError):
            continue
        out.append({"tier": sc.print_tier_cardrush(it.get("rarity"), extra),
                    "art": art_tokens(extra), "price": price})
    return out


def _toretoku_listings(items, number):
    out = []
    for it in items:
        if (it.get("number") or "") != number:
            continue
        p = it.get("price")
        if not p:
            continue
        name = it.get("name") or ""
        suffix = name[name.find("(") + 1:name.rfind(")")] if "(" in name else ""
        out.append({"tier": sc.print_tier_from_name(name),
                    "art": art_tokens(suffix), "price": p})
    return out


def _similarity(a, b):
    """Jaccard dei token: 1 se identici (anche entrambi vuoti), 0 se disgiunti."""
    if not a and not b:
        return 1.0
    u = a | b
    return len(a & b) / len(u) if u else 1.0


def reconcile(cr_listings, tt_listings):
    """Accoppia le inserzioni delle due fonti per (tier, similarita' arte).
    Ritorna una lista di stampe: {tier, art(frozenset), cardrush, toretoku}.
    Greedy GLOBALE sui pair a similarita' piu' alta; i resti -> single-fonte."""
    prints = []
    tiers = {l["tier"] for l in cr_listings} | {l["tier"] for l in tt_listings}
    for tier in tiers:
        cr = [l for l in cr_listings if l["tier"] == tier]
        tt = [l for l in tt_listings if l["tier"] == tier]
        # candidati pair ordinati per similarita' decrescente
        pairs = sorted(
            ((i, j, _similarity(cr[i]["art"], tt[j]["art"]))
             for i in range(len(cr)) for j in range(len(tt))),
            key=lambda x: -x[2])
        used_cr, used_tt = set(), set()
        for i, j, _ in pairs:
            if i in used_cr or j in used_tt:
                continue
            used_cr.add(i); used_tt.add(j)
            prints.append({"tier": tier, "art": cr[i]["art"] or tt[j]["art"],
                           "cardrush": cr[i]["price"], "toretoku": tt[j]["price"]})
        for i in range(len(cr)):
            if i not in used_cr:
                prints.append({"tier": tier, "art": cr[i]["art"],
                               "cardrush": cr[i]["price"], "toretoku": None})
        for j in range(len(tt)):
            if j not in used_tt:
                prints.append({"tier": tier, "art": tt[j]["art"],
                               "cardrush": None, "toretoku": tt[j]["price"]})
    return prints


def reconcile_number(number, cardrush_html, toretoku_html):
    """Comodita': dai grezzi HTML alle stampe riconciliate per un numero."""
    cr = _cardrush_listings(sc.parse_cardrush(cardrush_html), number)
    tt = _toretoku_listings(sc.parse_toretoku(toretoku_html), number)
    return reconcile(cr, tt)
