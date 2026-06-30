# -*- coding: utf-8 -*-
"""
BLINDATURA del ground-truth Excel (Import Kumamoto.xlsx): le carte Pokemon e i loro
prezzi/indice "fanno fede" e NON devono rompersi. Qui blocchiamo l'IDENTITA':
  - i 294 Card Code dell'Excel sono ben formati (set + numero pieno parsabile);
  - sul DB REALE (se presente) ognuno risolve a >=1 carta, in modo TOLLERANTE sul
    denominatore (l'Excel scrive S12a 262/170, CardRush 262/172: stessa carta).
L'indice ufficiale resta lockato da test_intelligence.py::test_official_index_matches_excel_formula.
"""
import os
import sys
import json
import sqlite3
import pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import scrapers as sc  # noqa: E402

CODES = json.loads((ROOT / "tests" / "fixtures" / "excel_pokemon_codes.json").read_text(encoding="utf-8"))
REAL_DB = ROOT / "tcg_tracker.db"


def test_excel_codes_fixture_wellformed():
    assert len(CODES) == 294
    for code in CODES:
        setc, _, num = code.partition(" ")
        assert setc and "/" in num, f"code malformato: {code!r}"
        assert sc.collector_tuple(num) is not None, f"numero non parsabile: {code!r}"


@pytest.mark.skipif(not REAL_DB.exists(), reason="DB reale non presente (CI)")
def test_excel_codes_resolve_in_real_db():
    """Ogni Card Code Excel deve risolvere a >=1 carta nel DB reale, tollerando il
    denominatore (match per set + NUMERATORE). Protegge l'identita' delle carte che
    fanno fede da refactor del matcher/catalogo."""
    # Set/codici noti NON nel catalogo (merch/refusi Excel): gap documentati, non regressioni.
    KNOWN_GAPS = {"mBG 022/021", "s12a 195/72"}
    con = sqlite3.connect(str(REAL_DB))
    unresolved = []
    for code in CODES:
        if code in KNOWN_GAPS:
            continue
        setc, _, num = code.partition(" ")
        numer = num.split("/")[0]
        # case-insensitive sul set (l'Excel mescola 'S12a'/'s12a' - casing incoerente)
        # e tollerante sul denominatore (Excel /170 vs DB /172).
        row = con.execute(
            """SELECT 1 FROM tcg_card c JOIN tcg_set s ON s.id = c.set_id
               WHERE upper(s.set_code) = upper(?) AND c.number LIKE ? LIMIT 1""",
            (setc, numer + "/%")).fetchone()
        if not row:
            unresolved.append(code)
    con.close()
    assert not unresolved, f"{len(unresolved)} Card Code Excel non risolti: {unresolved[:15]}"
