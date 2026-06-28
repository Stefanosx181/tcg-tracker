-- =====================================================================
--  TCG Tracker - Schema v2 (MULTI-GIOCO, game-agnostic) - SQLite
--  Schema CORRENTE. Sostituisce il v1 Pokémon-specifico (db/schema_v1_sqlite.sql).
--
--  Identita' canonica della carta INDIPENDENTE dal formato di numerazione:
--    (game, set, number, language, rarity, variant)
--  cosi' regge Pokémon '262/172', One Piece 'OP01-001', Yu-Gi-Oh, ecc.
--
--  Le viste v_latest_price / v_buylist riespongono gli STESSI nomi di colonna
--  del v1 (pack_code, card_code, model_number, full_name, cardrush_price, ...)
--  cosi' database.py/export_web e la dashboard restano invariati: il
--  contratto-output (buylist + indice) non cambia.
--
--  Bootstrap: init_db crea il v1 dal seed e poi applica db/migrate_001_multigame.py.
-- =====================================================================
PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_buylist;
DROP VIEW  IF EXISTS v_latest_price;
DROP TABLE IF EXISTS tcg_price;
DROP TABLE IF EXISTS tcg_card;
DROP TABLE IF EXISTS tcg_set;
DROP TABLE IF EXISTS tcg_source;
DROP TABLE IF EXISTS tcg_game;

-- --------------------------------------------------------------------
-- GIOCO (dimensione nuova): pokemon / onepiece / yugioh
-- --------------------------------------------------------------------
CREATE TABLE tcg_game (
  game_code     TEXT PRIMARY KEY,                 -- 'pokemon','onepiece','yugioh'
  display_name  TEXT NOT NULL
);

-- --------------------------------------------------------------------
-- SET (per gioco). set_code = ex pack_code, casing PRESERVATO (S12a, SV1V)
-- --------------------------------------------------------------------
CREATE TABLE tcg_set (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  game_code     TEXT    NOT NULL REFERENCES tcg_game(game_code) ON DELETE CASCADE,
  set_code      TEXT    NOT NULL,
  set_name      TEXT    NOT NULL,
  display_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE (game_code, set_code)
);

-- --------------------------------------------------------------------
-- CARTA. Identita' canonica = (set_id, number, language, rarity, variant).
--   number  : numero canonico nel set, testo libero ('262/172','OP01-001',...)
--   variant : '' = standard; altrimenti chiave variante (error, holo, manga...)
-- I campi legacy_* conservano i valori v1 (tracciabilita' + immagini).
-- --------------------------------------------------------------------
CREATE TABLE tcg_card (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  set_id              INTEGER NOT NULL REFERENCES tcg_set(id) ON DELETE CASCADE,
  number              TEXT    NOT NULL,
  language            TEXT    NOT NULL DEFAULT 'JP',
  rarity              TEXT,
  variant             TEXT    NOT NULL DEFAULT '',
  name                TEXT,
  name_en             TEXT,
  cardrush_url        TEXT,
  hareruya_url        TEXT,
  legacy_card_code    TEXT,                        -- vecchio card_code 'S12a 262/172'
  legacy_model_number TEXT,                        -- vecchio model_number '262' (immagine)
  row_index           INTEGER,
  UNIQUE (set_id, number, language, rarity, variant)
);
CREATE INDEX idx_card_set ON tcg_card(set_id);

-- --------------------------------------------------------------------
-- SORGENTE buyback
-- --------------------------------------------------------------------
CREATE TABLE tcg_source (
  source_code   TEXT PRIMARY KEY,                  -- 'cardrush','hareruya'
  display_name  TEXT NOT NULL
);

-- --------------------------------------------------------------------
-- PREZZI (storico). Legato a (card_id, source_code).
--   price_raw    : buying price GREZZO rilevato (o riportato dal carry-forward)
--   price_norm   : prezzo con commissione *1.10, SEPARATO dal grezzo
--   condition    : condizione (default NM); in_stock 0 = non confermato/non trovato
--   price_status : 'confirmed' = trovato in questa passata,
--                  'carried'   = riportato dall'ultimo prezzo noto (entro il limite),
--                  'absent'    = non trovato e nessun prezzo recente da riportare.
--   is_outlier   : 1 = lo scarto vs la mediana storica della carta supera la soglia
--                  (flag SOLO informativo: l'indice ufficiale NON lo usa; la vista
--                  normalizzata in export_web esclude gli outlier).
-- --------------------------------------------------------------------
CREATE TABLE tcg_price (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id       INTEGER NOT NULL REFERENCES tcg_card(id) ON DELETE CASCADE,
  source_code   TEXT    NOT NULL REFERENCES tcg_source(source_code) ON DELETE CASCADE,
  price_raw     REAL,
  price_norm    REAL,
  currency      TEXT    NOT NULL DEFAULT 'JPY',
  condition     TEXT    NOT NULL DEFAULT 'NM',
  in_stock      INTEGER NOT NULL DEFAULT 1,
  price_status  TEXT    NOT NULL DEFAULT 'confirmed',
  is_outlier    INTEGER NOT NULL DEFAULT 0,
  scraped_at    TEXT    NOT NULL
);
CREATE INDEX idx_price_card_source ON tcg_price(card_id, source_code);

-- =====================================================================
--  VISTE: stessi NOMI di colonna del v1 (contratto-output invariato)
-- =====================================================================

-- Ultimo prezzo per carta+sorgente = riga con scraped_at PIU' RECENTE
-- (stessa semantica del v1, cosi' la buylist resta identica: conta la DATA,
-- non l'ordine d'inserimento dei prezzi manuali/importati). A parita' di
-- scraped_at si sceglie l'id massimo: una sola riga, niente duplicati.
CREATE VIEW v_latest_price AS
SELECT p.*
FROM tcg_price p
JOIN ( SELECT card_id, source_code, MAX(id) AS mxid
       FROM tcg_price
       WHERE (card_id, source_code, scraped_at) IN (
           SELECT card_id, source_code, MAX(scraped_at)
           FROM tcg_price GROUP BY card_id, source_code)
       GROUP BY card_id, source_code ) last
  ON p.id = last.mxid;

-- Vista BuyList: una riga per carta con i due buying price affiancati.
-- Alias verso i nomi v1 (pack_code, card_code, model_number, full_name, ...).
CREATE VIEW v_buylist AS
SELECT s.display_order            AS set_order,
       s.set_code                 AS pack_code,
       s.set_name                 AS set_name,
       c.id                       AS card_id,
       c.legacy_card_code         AS card_code,
       c.legacy_model_number      AS model_number,
       c.name                     AS full_name,
       c.name_en                  AS name_en,
       c.rarity                   AS rarity,
       cr.price_raw               AS cardrush_price,
       cr.price_norm              AS cardrush_price_comm,
       hr.price_raw               AS hareruya_price,
       hr.price_norm              AS hareruya_price_comm,
       cr.in_stock                AS cardrush_stock,
       hr.in_stock                AS hareruya_stock,
       MAX(COALESCE(cr.price_raw,0), COALESCE(hr.price_raw,0)) AS best_price,
       CASE WHEN COALESCE(cr.price_raw,0)=0 AND COALESCE(hr.price_raw,0)=0 THEN NULL
            WHEN COALESCE(cr.price_raw,0)>=COALESCE(hr.price_raw,0) THEN 'cardrush'
            ELSE 'hareruya' END   AS best_source,
       c.cardrush_url             AS cardrush_url,
       c.hareruya_url             AS hareruya_url
FROM tcg_card c
JOIN tcg_set s ON s.id = c.set_id
LEFT JOIN v_latest_price cr ON cr.card_id=c.id AND cr.source_code='cardrush'
LEFT JOIN v_latest_price hr ON hr.card_id=c.id AND hr.source_code='hareruya'
ORDER BY s.display_order, c.id;
