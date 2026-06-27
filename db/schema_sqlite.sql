-- =====================================================================
--  TCG Tracker - Schema database (SQLite, variante zero-config)
--  Stessa struttura di 01_schema.sql ma per chi non vuole installare MySQL.
--  Uso:  sqlite3 tcg_tracker.db < schema_sqlite.sql
-- =====================================================================
PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_buylist;
DROP VIEW  IF EXISTS v_latest_price;
DROP TABLE IF EXISTS tcg_price;
DROP TABLE IF EXISTS tcg_card;
DROP TABLE IF EXISTS tcg_set;

CREATE TABLE tcg_set (
  pack_code     TEXT    PRIMARY KEY,
  set_name      TEXT    NOT NULL,
  display_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE tcg_card (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  pack_code     TEXT    NOT NULL REFERENCES tcg_set(pack_code) ON DELETE CASCADE,
  card_code     TEXT    NOT NULL,
  model_number  TEXT,
  full_name     TEXT,
  rarity        TEXT,
  cardrush_url  TEXT,
  hareruya_url  TEXT,
  row_index     INTEGER,
  UNIQUE (pack_code, card_code)
);

CREATE TABLE tcg_price (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id               INTEGER NOT NULL REFERENCES tcg_card(id) ON DELETE CASCADE,
  source                TEXT    NOT NULL CHECK (source IN ('cardrush','hareruya')),
  buying_price          REAL,
  price_with_commission REAL,
  currency              TEXT    NOT NULL DEFAULT 'JPY',
  in_stock              INTEGER NOT NULL DEFAULT 1,
  scraped_at            TEXT    NOT NULL
);
CREATE INDEX idx_price_card_source ON tcg_price(card_id, source);

CREATE VIEW v_latest_price AS
SELECT p.*
FROM tcg_price p
JOIN ( SELECT card_id, source, MAX(scraped_at) mx
       FROM tcg_price GROUP BY card_id, source ) last
  ON p.card_id=last.card_id AND p.source=last.source AND p.scraped_at=last.mx;

CREATE VIEW v_buylist AS
SELECT s.display_order set_order, s.pack_code, s.set_name,
       c.id card_id, c.card_code, c.model_number, c.full_name, c.rarity,
       cr.buying_price cardrush_price, cr.price_with_commission cardrush_price_comm,
       hr.buying_price hareruya_price, hr.price_with_commission hareruya_price_comm,
       cr.in_stock cardrush_stock, hr.in_stock hareruya_stock,
       MAX(COALESCE(cr.buying_price,0), COALESCE(hr.buying_price,0)) best_price,
       CASE WHEN COALESCE(cr.buying_price,0)=0 AND COALESCE(hr.buying_price,0)=0 THEN NULL
            WHEN COALESCE(cr.buying_price,0)>=COALESCE(hr.buying_price,0) THEN 'cardrush'
            ELSE 'hareruya' END best_source,
       c.cardrush_url, c.hareruya_url
FROM tcg_card c
JOIN tcg_set s ON s.pack_code=c.pack_code
LEFT JOIN v_latest_price cr ON cr.card_id=c.id AND cr.source='cardrush'
LEFT JOIN v_latest_price hr ON hr.card_id=c.id AND hr.source='hareruya'
ORDER BY s.display_order, c.id;
