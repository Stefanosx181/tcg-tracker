-- =====================================================================
--  TCG Tracker - Schema database (MySQL / MariaDB)
--  Rispecchia la struttura del foglio "BuyList Pokemon" di Import_Kumamoto.xlsx
--  - Set  (S12A=VSTAR Universe, SV1V=Violet ex, ...)
--  - Carte sotto ogni set (colonna A = codice, colonna C = nome)
--  - Due buying price per carta: cardrush + hareruya
--
--  Import:  mysql -u utente -p < 01_schema.sql
-- =====================================================================

CREATE DATABASE IF NOT EXISTS tcg_tracker
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE tcg_tracker;

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS tcg_price;
DROP TABLE IF EXISTS tcg_card;
DROP TABLE IF EXISTS tcg_set;
SET FOREIGN_KEY_CHECKS = 1;

-- ---------------------------------------------------------------------
-- SET (i "pacchetti": S12A, SV1V, SV1S, SV1a, ...)
-- ---------------------------------------------------------------------
CREATE TABLE tcg_set (
  pack_code     VARCHAR(16)  NOT NULL,            -- es. 'S12A'
  set_name      VARCHAR(128) NOT NULL,            -- es. 'VSTAR Universe'
  display_order INT          NOT NULL DEFAULT 0,  -- ordine di comparsa nell'Excel
  PRIMARY KEY (pack_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- CARTE (i codici elencati sotto ogni set)
-- ---------------------------------------------------------------------
CREATE TABLE tcg_card (
  id            INT          NOT NULL AUTO_INCREMENT,
  pack_code     VARCHAR(16)  NOT NULL,            -- FK -> tcg_set
  card_code     VARCHAR(32)  NOT NULL,            -- colonna A, es. 's12a 262/172'
  model_number  VARCHAR(16)  NULL,                -- es. '262' (per la ricerca)
  full_name     VARCHAR(255) NULL,                -- colonna C, es. 'Arceus V ASTRO (s12a 262)VSTAR Universe'
  cardrush_url  TEXT         NULL,                -- colonna E (endpoint JSON cardrush)
  hareruya_url  TEXT         NULL,                -- URL/ricerca hareruya (hare2buy)
  row_index     INT          NULL,                -- riga originale nell'Excel (tracciabilita')
  PRIMARY KEY (id),
  UNIQUE KEY uq_card (pack_code, card_code),
  KEY idx_pack (pack_code),
  CONSTRAINT fk_card_set FOREIGN KEY (pack_code)
      REFERENCES tcg_set (pack_code) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- PREZZI (storico): un record per carta / sito / scraping
--   source = cardrush | hareruya
--   buying_price            -> prezzo di acquisto rilevato sul sito
--   price_with_commission   -> buying_price * 1.10 (come la colonna F dell'Excel)
-- ---------------------------------------------------------------------
CREATE TABLE tcg_price (
  id                    BIGINT       NOT NULL AUTO_INCREMENT,
  card_id               INT          NOT NULL,            -- FK -> tcg_card
  source                ENUM('cardrush','hareruya') NOT NULL,
  buying_price          DECIMAL(12,2) NULL,
  price_with_commission DECIMAL(12,2) NULL,
  currency              CHAR(3)      NOT NULL DEFAULT 'JPY',
  in_stock              TINYINT(1)   NOT NULL DEFAULT 1,   -- 0 = non trovato / non acquistato
  scraped_at            DATETIME     NOT NULL,
  PRIMARY KEY (id),
  KEY idx_card_source (card_id, source),
  KEY idx_scraped (scraped_at),
  CONSTRAINT fk_price_card FOREIGN KEY (card_id)
      REFERENCES tcg_card (id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================================
--  VISTE: ricostruiscono il "layout Excel" leggendo l'ultimo prezzo rilevato
-- =====================================================================

-- Ultimo prezzo per carta + sito
CREATE OR REPLACE VIEW v_latest_price AS
SELECT p.card_id, p.source, p.buying_price, p.price_with_commission,
       p.currency, p.in_stock, p.scraped_at
FROM   tcg_price p
JOIN ( SELECT card_id, source, MAX(scraped_at) AS mx
       FROM tcg_price GROUP BY card_id, source ) last
  ON  p.card_id = last.card_id AND p.source = last.source AND p.scraped_at = last.mx;

-- Vista "BuyList": una riga per carta con i due buying price affiancati
CREATE OR REPLACE VIEW v_buylist AS
SELECT
    s.display_order                         AS set_order,
    s.pack_code,
    s.set_name,
    c.id                                    AS card_id,
    c.card_code,
    c.model_number,
    c.full_name,
    cr.buying_price                         AS cardrush_price,
    cr.price_with_commission                AS cardrush_price_comm,
    hr.buying_price                         AS hareruya_price,
    hr.price_with_commission                AS hareruya_price_comm,
    GREATEST(COALESCE(cr.buying_price,0), COALESCE(hr.buying_price,0)) AS best_price,
    CASE
       WHEN COALESCE(cr.buying_price,0) = 0 AND COALESCE(hr.buying_price,0) = 0 THEN NULL
       WHEN COALESCE(cr.buying_price,0) >= COALESCE(hr.buying_price,0) THEN 'cardrush'
       ELSE 'hareruya'
    END                                     AS best_source,
    c.cardrush_url,
    c.hareruya_url
FROM tcg_card c
JOIN tcg_set  s  ON s.pack_code = c.pack_code
LEFT JOIN v_latest_price cr ON cr.card_id = c.id AND cr.source = 'cardrush'
LEFT JOIN v_latest_price hr ON hr.card_id = c.id AND hr.source = 'hareruya'
ORDER BY s.display_order, c.id;
