-- Seed di PROVA per Yu-Gi-Oh (schema v2). Piccolo campione dal set QCCU,
-- per validare l'integrazione multi-gioco (CardRush + Yuyu-tei).
-- Pensato per il sandbox (tcg_tracker.backup.db), NON per il DB reale.
--
-- Nota numerazione YGO: l'identita' e' il SET CODE 'QCCU-JP002' (PACK-JPnnn);
-- il set_code 'QCCU' costruisce l'URL Yuyu-tei /buy/ygo/s/qccu. Lo stesso set code
-- ha piu' rarita'/versioni: CardRush le distingue per rarita', Yuyu-tei per suffisso
-- del nome (es. "(イラスト違い版)"). Senza disambiguazione fine, la scelta 'standard'
-- prende il prezzo piu' alto per fonte (puo' essere una stampa diversa tra CR e Yuyu-tei).

INSERT OR IGNORE INTO tcg_game (game_code, display_name)
  VALUES ('yugioh', 'Yu-Gi-Oh! OCG');

INSERT OR IGNORE INTO tcg_source (source_code, display_name)
  VALUES ('yuyutei', 'Yuyu-tei');

INSERT OR IGNORE INTO tcg_set (game_code, set_code, set_name, display_order)
  VALUES ('yugioh', 'QCCU', 'QUARTER CENTURY CHRONICLE side:UNITY', 200);

-- Carta: Dark Magician Girl (Black Magician Girl), set code QCCU-JP002.
INSERT OR IGNORE INTO tcg_card
  (set_id, number, language, rarity, variant, name, name_en,
   cardrush_url, legacy_card_code, legacy_model_number)
SELECT s.id, 'QCCU-JP002', 'JP', 'QCSE', '', 'ブラック・マジシャン・ガール', 'Dark Magician Girl',
       'https://cardrush.media/yugioh/buying_prices?model_number=QCCU-JP002',
       'QCCU-JP002', 'QCCU-JP002'
FROM tcg_set s WHERE s.game_code='yugioh' AND s.set_code='QCCU';
