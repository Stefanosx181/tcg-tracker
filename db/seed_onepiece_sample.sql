-- Seed di PROVA per One Piece (schema v2). Piccolo set OP01 con carta standard
-- e relativa variante 'parallel', per validare l'integrazione multi-gioco.
-- Pensato per il sandbox (tcg_tracker.backup.db), NON per il DB reale.
-- Idempotente per il gioco/sorgente; le carte usano INSERT OR IGNORE sull'identita'.

INSERT OR IGNORE INTO tcg_game (game_code, display_name)
  VALUES ('onepiece', 'One Piece Card Game');

INSERT OR IGNORE INTO tcg_source (source_code, display_name)
  VALUES ('yuyutei', 'Yuyu-tei');

INSERT OR IGNORE INTO tcg_set (game_code, set_code, set_name, display_order)
  VALUES ('onepiece', 'OP01', 'ROMANCE DAWN', 100);

-- Carta standard: Roronoa Zoro (Leader) — buyback CardRush filtrato per model_number;
-- la URL Yuyu-tei la costruisce l'adapter dal set (yuyu-tei.jp/buy/opc/s/op01).
INSERT OR IGNORE INTO tcg_card
  (set_id, number, language, rarity, variant, name, name_en,
   cardrush_url, legacy_card_code, legacy_model_number)
SELECT s.id, 'OP01-001', 'JP', 'L', '', 'ロロノア・ゾロ', 'Roronoa Zoro',
       'https://cardrush.media/onepiece/buying_prices?model_number=OP01-001',
       'OP01-001', 'OP01-001'
FROM tcg_set s WHERE s.game_code='onepiece' AND s.set_code='OP01';

-- Variante 'parallel' della stessa carta (identita' canonica distinta).
INSERT OR IGNORE INTO tcg_card
  (set_id, number, language, rarity, variant, name, name_en,
   cardrush_url, legacy_card_code, legacy_model_number)
SELECT s.id, 'OP01-001', 'JP', 'L', 'parallel', 'ロロノア・ゾロ(パラレル)', 'Roronoa Zoro (Parallel)',
       'https://cardrush.media/onepiece/buying_prices?model_number=OP01-001',
       'OP01-001', 'OP01-001'
FROM tcg_set s WHERE s.game_code='onepiece' AND s.set_code='OP01';
