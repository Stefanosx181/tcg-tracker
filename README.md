# TCG Tracker — Buying Prices (CardRush vs Hareruya)

Strumento per il tracking del mercato TCG giapponese. Legge i **set** e i **codici
carta** dal foglio `BuyList Pokemon` di `Import_Kumamoto.xlsx`, recupera il
**buying price** da **CardRush** e **Hareruya**, salva tutto in un **database**
con la stessa struttura dell'Excel e lo mostra in una **schermata dedicata**.

> ⚠️ L'Excel originale **non viene mai modificato**: il programma ne legge solo i dati.

---

## Struttura del progetto

```
tcg_tracker/
├── db/
│   ├── 01_schema.sql            # schema database (MySQL/MariaDB)
│   ├── 02_seed_sets_cards.sql   # set + carte estratti dall'Excel
│   └── schema_sqlite.sql        # stesso schema in versione SQLite
├── src/
│   ├── init_db.py               # crea il DB SQLite da schema + seed
│   ├── run.py                   # ESEGUIBILE: fa lo scraping dei prezzi
│   ├── scrapers.py              # logica CardRush (JSON) + Hareruya (HTML)
│   └── database.py              # accesso DB (SQLite default, MySQL opzionale)
├── dashboard/
│   ├── app.py                   # schermata dedicata (web) servita dal DB
│   ├── templates/index.html
│   └── dashboard.html           # s
tessa schermata, versione statica/standalone
├── build/build_exe.bat          # compila lo scraper in .exe (Windows)
├── requirements.txt
└── config.example.ini
```

---

## Modello dati (rispecchia l'Excel)

- **tcg_set** — i set: `pack_code` (S12A, SV1V…), `set_name` (VSTAR Universe…)
- **tcg_card** — le carte sotto ogni set: `card_code` (colonna A), `full_name`
  (colonna C), `cardrush_url` (colonna E), `model_number`, `hareruya_url`
- **tcg_price** — storico prezzi: `source` = `cardrush` | `hareruya`,
  `buying_price`, `price_with_commission` (= prezzo × 1.10, come la colonna F)
- **v_buylist** — vista che affianca i due buying price per ogni carta e calcola
  la **migliore offerta**.

---

## Avvio rapido (SQLite, senza installare database)

```bash
pip install -r requirements.txt

# 1) crea il database con set e carte estratti dall'Excel
python src/init_db.py

# 2) avvia lo scraping dei buying price
python src/run.py                 # tutte le carte
python src/run.py --set S12A      # solo un set
python src/run.py --limit 5       # test sui primi 5
python src/run.py --only cardrush # un solo sito

# 3) apri la schermata dedicata
python dashboard/app.py           # -> http://127.0.0.1:5000
```

## Uso con MySQL

```bash
mysql -u root -p < db/01_schema.sql
mysql -u root -p tcg_tracker < db/02_seed_sets_cards.sql
```
Poi copia `config.example.ini` in `config.ini` con le tue credenziali.

## Generare l'eseguibile .exe

Su **Windows** (gli `.exe` sono platform-specific):
```
build\build_exe.bat
```
Gli eseguibili finiscono in `dist/`.

---

## Note sugli scraper

- **CardRush**: l'URL della colonna E un tempo restituiva JSON; oggi
  `cardrush.media` è una app **Next.js** che rende HTML con i dati incorporati
  nello script `__NEXT_DATA__`. Lo scraper estrae da lì la lista `buyingPrices`,
  filtra per `model_number`/`pack_code` e legge il buying price (`amount`) più
  alto. (Mantiene un fallback per il vecchio formato JSON.)
- **Hareruya** (`hare2buy.com`): si cerca su `/product-list` col parametro
  **`keyword`** usando il **numero di collezione completo** (es. `114/083`, non
  solo `114`, che restituirebbe carte di set diversi). I risultati si filtrano
  per numero `〈###/###〉` e tag set `[M4]` nel nome prodotto. Selettori CSS in
  `HARERUYA_SELECTORS` dentro `scrapers.py`: da adeguare se il sito cambia layout.
- Aggiungi sempre una pausa (`--sleep`) tra le richieste e rispetta i termini
  d'uso dei siti.
