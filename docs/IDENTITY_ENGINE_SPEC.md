## CRITIQUE scores
  Identità canonica ancorata a TCGdex (Architect A): 6/10 breaks_excel=False — Impostazione solida e rispettosa dei vincoli sacri: arricchimento offline fuori dal ciclo prezzi, indice ufficiale su price_raw a pesi fissi invariato (lockato dai test), tcg_price solo-append, e per 
  Design B — Identità autosufficiente (game, set, numero pieno, stampa) + matching a porte AND con astensione: 6/10 breaks_excel=False — Direzione giusta, ma il design SOPRAVVALUTA la sicurezza già garantita in Fase A e descrive porte (P2 gate set su Hareruya, esclusione da best_price) che NON esistono ancora nel codice/vista. Punti fo
  Design C — Verifica per immagine (pHash + OCR numero) come gate d'identità indipendente dal testo: 5/10 breaks_excel=False — RESPINGERE come design PRINCIPALE; eventualmente ACCETTARE come vista a basso-costo solo-VETO sui casi alto-valore single-source, MA solo dopo calibrazione su ground-truth etichettato. Punti FORTI rea

## CHIAVE UNIVOCA
CHIAVE DI IDENTITA UNIVOCA DEFINITIVA = (game_code, set_code_norm, full_number, print_tier).

- game_code: 'pokemon' | 'onepiece' | 'yugioh' (dimensione tcg_game esistente).
- set_code_norm: set_code con casing PRESERVATO in colonna (display), ma confrontato in forma normalizzata = upper(strip()) col SUFFISSO-VARIANTE Hareruya rimosso ('SV2a-Ma' -> 'SV2A'). Il casing originale resta in tcg_set.set_code perche distingue era/blocco (S12a != s12a, SV1V); la normalizzazione e solo per il join.
- full_number: numero PIENO 'numeratore/denominatore' senza zeri iniziali, slash mantenuto (es. '141/165', '262/172'). MAI il solo numeratore. Il denominatore = TOTALE DEL SET BASE (etichetta del set, non limite): numeratore>denominatore e LEGITTIMO e atteso (secret rare, 3167/8303 nel DB). Carte senza denominatore ('-', '旧裏', 'DPBP#006') = NON identificabili -> astensione.
- print_tier: '' (=base implicita) | 'masterball' | 'monsterball' | 'reverse' | 'promo' | 'parallel' | 'super'. E la 4a componente, additiva: la carta base resta sull'id storico in tcg_card.

VINCOLO EXCEL: per Pokemon (game, set_code_norm, full_number) con print_tier='' COINCIDE 1:1 col 'Card Code' Excel '<set_code> <numero>' (verificato in ricerca: 0 collisioni interne su (set_id,number), 0 mismatch su legacy_card_code vs number per le 263 storiche). Quindi la chiave NON ridefinisce l'identita che il cliente gia usa; la aggiunge solo la dimensione print_tier per separare base da mirror.

Il denominatore NON identifica il set (078/070 esiste in 11 set), quindi NESSUNA porta da sola basta: l'unicita richiede SEMPRE set_code_norm + full_number + (dove esistono stampe parallele) print_tier.

## ALGORITMO IDENTITA
  • IDENTITA A PORTE AND A FORZA DECRESCENTE, altrimenti ASTENSIONE ('carta giusta o niente'). Nessuna singola porta e sufficiente.
  • PORTA 1 (obbligatoria) NUMERO PIENO: il listing deve avere full_number == full_number della carta, confrontando numeratore E denominatore entrambi senza zeri iniziali. Chiude la collisione cross-set (078/070 in 11 set) e il match sul solo numeratore. Se la carta non ha un num/den ricavabile -> Query vuota = astensione immediata (gia fatto su Hareruya, da estendere come principio).
  • PORTA 2 (obbligatoria, dopo normalizzazione) SET: set della fonte normalizzato (upper, strip, rimozione suffisso dopo '-' tipo -Ma/-Mo) == set_code_norm della carta, case-insensitive. Su CardRush pack_code e pulito -> confronto diretto. Su Hareruya il tag [SV2a-Ma] va spogliato a 'SV2A' PRIMA del confronto; il suffisso -Ma/-Mo NON si scarta, passa alla PORTA 4 come segnale di stampa. CRITICO: oggi HareruyaAdapter.parse NON confronta il tag set affatto -> va aggiunto.
  • PORTA 3 (requisito, non fallback) NOME: confronto del nome del listing contro il NOSTRO nome canonico tcg_card.name (verita interna JP, 100% popolata), via uguaglianza-segmento + Jaccard sui bigrammi >= 0.85, NON substring. Separa コイル 001/015 da Pikachu V 001/015 e Quick Ball da Evolution Incense. Se nessun listing supera la soglia -> astensione (la nostra carta non e su quella fonte). Il substring attuale (_norm_name + 'in') va sostituito.
  • PORTA 4 (gate di sicurezza) STAMPA / VETO MIRROR: estrai il marcatore di stampa dal listing (nome ':マスターボールミラー'->masterball, ':モンスターボールミラー'->monsterball, 'リバース'->reverse; suffisso tag -Ma/-Mo; suffisso 'a' nel codProd Hareruya; extra_difference / righe multiple su CardRush). Tieni SOLO i listing il cui print_tier == print_tier target della carta. Se la carta target e 'base' e gli UNICI listing sopravvissuti sono mirror/variante -> ASTENSIONE (mai pubblicare 1800 al posto di 100). Veto per CLASSE: se in catalogo/risultato esiste una stampa mirror nota per quel (set,numero), la carta base astiene finche la dimensione variant non e popolata (Fase D).
  • PORTA 5 (soft, skip-non-reject) RARITA: solo se la rarita nostra e nota e NON e un simbolo (★/☆/◆) e il listing espone una rarita divergente in modo netto -> declassa a 'da_verificare', MAI reject hard. Rarita vuota/simbolo (26% del catalogo) -> gate inerte. La rarita non separa mai le mirror (entrambe R).
  • SELEZIONE + GUARD AMBIGUITA: dopo le porte resta un pool. Se sopravvive esattamente 1 candidato distinto per il tier -> confirmed. Se >1 candidato con print_tier distinto o prezzi che divergono > AMBIGUITY_RATIO (4x) -> astensione []. Se 0 -> absent. MAI mediana, MAI max() cieco su pool a tier misti: max SOLO entro la stessa stampa confermata.
  • ANCORA ESTERNA come VALIDAZIONE OFFLINE (non nel ciclo prezzi): TCGdex /v2/ja popola card_anchor (canonical_id, nome JP ufficiale, rarity, image, set_official_total). 404 su (set,numeratore) -> astensione automatica; denominatore != cardCount.official -> warning identita. Il porta-nome puo confrontarsi col nome canonico TCGdex come terzo segnale sulle ~5000 carte solo-CardRush. Mai matcher di prezzo, mai dipendenza runtime.
  • ESITO A 3 LIVELLI: confirmed (tutte le porte note AND + sanita) -> pubblicabile in best_price; da_verificare (un gate soft fallisce / single-source / carried / multi-stampa pre-Fase-D) -> badge, ESCLUSO da best_price, coda revisione; absent (nessun nome combacia / solo mirror su carta base / numero senza den / bucket その他 / >1 candidato distinto) -> nessun prezzo.

## MATCHING CARDRUSH
  • Query gia per (model, pack) in forma SPA completa (anti-403): INVARIATA. Il problema e SOLO nel parse/match, non nella query.
  • FIX FAILURE MODE #1 (adapters.py:181 e scrapers.py pick_cardrush:242): sostituire 'model == want_model or model.split("/")[0] == want_model' con confronto sul NUMERO PIENO. build_query oggi passa want_model = SOLO numeratore (model_number o number.split('/')[0]): va cambiato per passare e confrontare il full_number 'num/den'. Allinea CardRush al comportamento gia corretto di Hareruya.
  • AGGIUNGERE PORTA NOME: confrontare il name del listing CardRush contro tcg_card.name via Jaccard>=0.85 + uguaglianza-segmento (oggi CardRush NON qualifica per nome). Necessario perche le varianti mirror sono RIGHE MULTIPLE con stesso model_number/pack_code distinte solo dal nome (verificato live: Kabutops 141/165 SV2a = 3 righe ¥1700/¥400/¥10).
  • PORTA STAMPA Pokemon: introdurre print_tier_pokemon(name, extra_difference) che riconosce masterball/monsterball/reverse dal nome (':マスターボールミラー' / ':モンスターボールミラー' / 'リバース') e da extra_difference. In parse(): tenere SOLO i listing con tier == tier target (oggi sempre 'base'). Se per (model,pack) restano righe di tier diverso e la carta e base ma resta solo una mirror -> astensione, mai max(). Oggi il ramo non-OP fa max() su tutte le 'standard' includendo le mirror non riconosciute.
  • Mantenere il ramo OP esistente (print_tier_cardrush + is_noise_listing) INVARIATO: il fix Pokemon e parallelo, non lo tocca.
  • SELEZIONE: per Pokemon, max() SOLO entro il tier 'base' confermato e dopo la porta nome; aggiungere guard ambiguita 4x (oggi presente solo su Hareruya).

## MATCHING HARERUYA
  • Numero pieno (num+den) gia corretto in HareruyaAdapter.parse via _COLLECTOR_RE: INVARIATO (e la difesa giusta, confermata live su 078/070 = 4 carte diverse).
  • AGGIUNGERE GATE SET (oggi ASSENTE): in parse() estrarre il tag [SET] dal nome listing (sc._PACK_RE), spogliare il suffisso variante dopo '-' ('SV2a-Ma'->'SV2A'), confrontarlo case-insensitive con query.match['pack'] normalizzato. Se il tag e presente e non combacia -> scarta il listing. Se il tag manca -> non confermare il gate set: declassa a da_verificare se gli altri segnali reggono. Questo chiude il buco critico: full_number NON e unico e oggi Hareruya non guarda il set.
  • MIGLIORARE PORTA NOME: sostituire il substring attuale (key in _norm_name(n)) con Jaccard>=0.85 + uguaglianza-segmento contro tcg_card.name. Il substring lascia passare match parziali; la collisione 078/070 (4 set) e separabile solo se il nome filtra a 1 prima della guard 4x.
  • PORTA STAMPA / VETO MIRROR: riconoscere masterball/monsterball dal nome (':マスターボールミラー'/':モンスターボールミラー'), dal suffisso tag -Ma/-Mo e dal suffisso 'a' nel codProd. Estrarre anche il codProd ([codProd] in coda al listing) per il fingerprint cache e come segnale variante. Se la carta e base e resta solo una mirror -> astensione (Kabutops 141/165: ¥100 base vs ¥1800 master, verificato live).
  • Propagare nel parse anche il tag set e il codProd come campi dell'item (oggi parse_hareruya ritorna solo name+price): serve per il gate set e il fingerprint. Validare i selettori reali sul DOM (gap noto: .selling_price/.goods_name non confermati dal vivo).
  • Guard ambiguita 4x: INVARIATA (gia presente).

## ANCORA ESTERNA
ANCORA ESTERNA = TCGdex /v2/ja, usata come VALIDAZIONE OFFLINE del catalogo, MAI come matcher di prezzo ne dipendenza runtime (cosi il numero ufficiale Excel non dipende mai da terzi e il sistema funziona anche se TCGdex e giu).

FATTIBILITA VERIFICATA: pubblica, HTTPS, no-auth, CORS *. Set id = nostri set_code case-insensitive (S12a, SV2a, S8b verificati). GET /v2/ja/cards?set={SET}&localId={numeratore} (endpoint query, evita lo zero-padding) -> id canonico 'SET-NNN', name JP, rarity (parziale, molti null), image base URL deterministica. GET /v2/ja/sets/{SET} -> cardCount.official (= denominatore set base) e .total (include secret).

NB DALLE CRITICHE (da gestire, non sopravvalutare): l'endpoint query-by-localId puo restituire [] anche per set/localId reali (osservato sm8b-150, S8b-78); ~30% del catalogo non e ancorabile (その他 ~1889, MC ~317, PROMO ~174, BW-P ~153, set con '+' che danno 404, bug 'sm4 ' con spazio); l'esempio '262/170' del prompt e errato (DB+TCGdex usano /172). Quindi l'ancora e un SEGNALE in piu, non un oracolo: la sua assenza non deve mandare in errore carte legittime.

USO CONCRETO:
1) Job OFFLINE batch (HttpClient del progetto con User-Agent, NON WebFetch; backoff/rate-limit; ~10k chiamate cache-ate) che popola una NUOVA tabella card_anchor(card_id, source='tcgdex', canonical_id, name_official, rarity_official, image_url, set_official_total, fetched_at) + colonna nullable tcg_card.external_id. Idempotente, incrementale.
2) VALIDAZIONE denominatore: se number.den != card_anchor.set_official_total -> flag 'denominatore_sospetto' (non reject, warning in health.json). Risponde formalmente a 'cosa significa il secondo numero'.
3) ASTENSIONE su 404: (set, numeratore) inesistente su TCGdex -> classifica 'absent' (numero che aggancia carta diversa).
4) PORTA NOME ancorata: confrontare il listing col nome canonico TCGdex dove disponibile -> terzo segnale indipendente prezioso sulle ~5000 solo-CardRush.
5) image_url canonica salvata per abilitare in futuro pHash (rischio residuo), MAI gate centrale.

FALLBACK quando l'ancora manca (404, bucket non-canonici, query []): nessun canonical_id -> carta NON validata esternamente -> si retrocede al match interno (set+numero pieno+nome) con confidenza MEDIA massima (mai ALTA su single-source senza secondo segnale).

SCARTATE: pokemontcg.io (solo set EN, 403 a WebFetch, no codici JP); pokemon-card.com (DB ufficiale JP ma solo form HTML, niente API JSON) -> conferma manuale di ultima istanza.

## VARIANTI
MODELLO A DUE LIVELLI (standard industriale TCGplayer Product/SKU), gia retto dallo schema corrente: LIVELLO 1 Product = identita logica (set+number, ancorabile al canonical_id TCGdex); LIVELLO 2 Variant = colonna tcg_card.variant (gia usata per One Piece 'parallel'/'super'). E SOLO il seed Pokemon a non popolarla (10191/10191 variant='').

DUE FASI SEPARATE DAL RISCHIO:

FASE A (SUBITO, solo matcher, NESSUNA modifica schema): VETO MIRROR. print_tier_pokemon in scrapers.py + filtro tier negli adapter (vedi pipeline CR/HR). Finche variant='' su tutte, quando per (set,number) esistono >1 stampe distinte e la carta target e 'base', astieniti se non resta esattamente la base. Rende sicuro il presente senza migrazione. Costo: nessun prezzo sulle carte multi-stampa (le piu di valore) -> misurato in health.json e comunicato.

FASE D (DOPO, con OK esplicito utente, migrazione id-preserving su COPIA del DB con conteggi prima/dopo): popolare tcg_card.variant per i Pokemon replicando la logica One Piece (print_tier dal nome/extra_difference). La carta BASE RESTA sull'id storico (cosi tcg_price storico, _index() e Charts NON si muovono); le stampe mirror sono RIGHE NUOVE con variant='masterball'/'monsterball' e id nuovi. La UNIQUE(set_id,number,language,rarity,variant) lo consente gia. Lo storico tcg_price e append-only, mai riscritto.

CORREZIONE SCHEMA CONSIGLIATA (Fase D): togliere rarity dalla UNIQUE key. La chiave naturale verificata e (set_id, number, variant); rarity e 74% popolata e sporca -> due righe stessa carta con rarity '' e 'R' violerebbero l'identita. E gia una trappola nota nel CLAUDE.md.

LIMITE DICHIARATO: TCGdex NON modella Master/Monster Ball Mirror (variants='normal'), quindi l'ancora conferma la carta logica ma NON la stampa: base-vs-mirror resta risolvibile SOLO con la dimensione variant interna (Fase D) o il VETO MIRROR temporaneo (Fase A).

## LOCK EXCEL
L'indice ufficiale e lo storico Excel si proteggono PER COSTRUZIONE, su quattro livelli:

1) INDICE UFFICIALE INTOCCATO: _index() in database.py:537 calcola pesi FISSI alla data base su price_raw GREZZO (rinormalizzati sulle carte presenti). NESSUNA modifica del matcher tocca questa funzione ne la serie 'series' ufficiale (ultimo prezzo/giorno, include i carried). Lockato da tests/test_intelligence.py::test_official_index_matches_excel_formula, che resta verde dopo ogni modifica. Le viste anti-outlier (sets_norm/global_norm) restano SEPARATE e aggiuntive.

2) STORICO APPEND-ONLY: save_price (database.py:173) INSERISCE righe nuove, non riscrive mai il passato. Le porte AND nuove cambiano SOLO cosa diventa 'confirmed' vs 'da_verificare'/'absent' nelle passate FUTURE; i prezzi gia in tcg_price fino alla data Excel non si toccano. I prezzi FUTURI che cambiano sono normali e voluti.

3) IDENTITA STABILE: per Pokemon (set_id, number) coincide col Card Code Excel; il fix matcher e la Fase A NON spostano carte tra set/number ne cambiano gli id. La Fase D e id-preserving (base sull'id storico, mirror su id nuovi), quindi l'aggregazione per card_id dentro il set resta invariata e l'indice non si muove.

4) PUBBLICAZIONE vs INDICE DISACCOPPIATI: il VETO/3-livelli agisce sul best_price/buylist (Fase B), NON sui pesi dell'indice. Carry-forward resta nell'indice (vincolo Excel) ma mai nel best_price 'sicuro'. ATTENZIONE (dalle critiche): la v_buylist oggi calcola best_price=MAX(price_raw) ignorando price_status/in_stock -> va modificata in Fase B per leggere price_status, altrimenti 'da_verificare'/'carried' raggiungono il cliente. Questa modifica e SULLA VISTA di pubblicazione, NON sull'indice ufficiale.

PROCEDURA OPERATIVA (vincolo CLAUDE.md): backup 'cp tcg_tracker.db tcg_tracker.backup.db', migrazioni/script PRIMA sulla copia, conteggi righe tcg_price prima/dopo mostrati, pytest verde (incl. il test indice) prima di toccare il DB reale. Mai init_db.py --force sul DB reale.

## MODIFICHE IMPLEMENTAZIONE
  [src/scrapers.py] Aggiungere print_tier_pokemon(name, extra='') che ritorna 'masterball' (':マスターボールミラー' nel nome), 'monsterball' (':モンスターボールミラー'), 'reverse' ('リバース'), 'promo', altrimenti '' (base). Aggiungere helper di normalizzazione: _norm_set_tag(tag) (upper/strip + split('-')[0]) e _name_jaccard(a,b)>=0.85 su bigrammi + uguaglianza-segmento. Estendere parse_hareruya per emettere anche 'set_tag' (da _PACK_RE) e 'prod_code' (codProd in coda) oltre a name/price. Fix pick_cardrush:242 al numero pieno (coerenza, anche se l'adapter e il percorso principale).
       perche: Fornisce i mattoni testabili offline per le porte set/nome/stampa senza logica negli adapter. Oggi parse_hareruya scarta tag set e codProd, che servono per il gate set, il veto mirror e il fingerprint cache.
       rischio: Selettori Hareruya non confermati sul DOM vero (gap noto): validare su fixture HTTP reale prima di affidarsi. Il tag set nel nome puo mancare in alcuni listing -> gestire come 'set non confermato', non come reject.
  [src/adapters.py] CardRushAdapter: build_query passa full_number ('num/den') non il solo numeratore; parse confronta model_number==full_number (chiude failure mode #1), aggiunge porta nome (Jaccard vs card name) e print_tier_pokemon, filtra al tier target, applica guard 4x. HareruyaAdapter.parse: aggiungere GATE SET (spoglia [SV2a-Ma]->'SV2A', confronta con pack), sostituire il substring nome con _name_jaccard, aggiungere veto mirror via print_tier_pokemon su name/set_tag/prod_code. select(): max SOLO entro tier base confermato.
       perche: E qui che vivono i failure mode #1 (CardRush solo numeratore) e #5 (base-vs-mirror) e il buco del gate set Hareruya. Sono i fix che eliminano i prezzi catastroficamente sbagliati.
       rischio: Jaccard 0.85 e AMBIGUITY_RATIO 4x da calibrare su ground-truth etichettato (>100 carte) per non rigettare carte legittime con nomi troncati/kana-kanji. Il veto mirror riduce la copertura sulle carte di valore finche non c'e la Fase D.
  [src/database.py] FASE B: save_price scrive price_status gia oggi; aggiungere stato 'da_verificare' per i casi soft (single-source, multi-stampa pre-Fase-D, set non confermato). export_web: best_price/best_source ricalcolati SOLO su prezzi confirmed+non-outlier (non piu max su tutto). NON toccare _index() ne la serie ufficiale. Opzionale: popolare review_queue + health.json (tasso absent/da_verificare per fonte).
       perche: Senza far rispettare price_status alla pubblicazione, i prezzi 'da_verificare'/'carried' arrivano comunque al cliente (buco rilevato nelle critiche). L'indice resta blindato.
       rischio: Cambiare la selezione best_price puo ridurre la copertura visibile: misurare e comunicare. Non confondere 'carta assente' con 'matcher rotto' (health.json).
  [db/schema_sqlite.sql (vista v_buylist)] FASE B: la vista v_buylist calcola best_price=MAX(price_raw) e best_source ignorando price_status e in_stock. Modificarla per escludere i non-confirmed dal best_price (o spostare il calcolo best in export_web, gia presente, e far si che la vista esponga solo i raw per fonte). Migrazione vista, nessuna perdita di dati.
       perche: Il punto di pubblicazione bypassa la sicurezza scritta nel DB: carried/da_verificare risultano come buyback ufficiale.
       rischio: E un cambio di vista: verificare che export_web (che gia ricalcola best su prices{}) e la dashboard restino coerenti; test buylist diff-zero sulle carte confirmed.
  [src/anchor.py (NUOVO) + db/schema (tabella card_anchor + colonna external_id)] Job OFFLINE che chiama TCGdex /v2/ja via HttpClient, popola card_anchor(card_id, canonical_id, name_official, rarity_official, image_url, set_official_total) e tcg_card.external_id (nullable). Idempotente, incrementale, backoff. NON nel ciclo prezzi.
       perche: Terzo segnale indipendente dal testo del negozio (porta nome ancorata, 404=astensione, validazione denominatore) sulle ~5000 solo-CardRush. Migliora la confidenza senza dipendenza runtime.
       rischio: Copertura ~70% (の他/MC/PROMO/+ non ancorabili; query-by-localId talvolta []). Trattare l'assenza come 'non validato', non come errore. ~10k chiamate: rate-limit/backoff obbligatori.
  [src/build_catalog.py (Fase D, con OK utente)] Popolare variant per i Pokemon (replica logica One Piece print_tier): la base resta sull'id storico, le mirror sono righe NUOVE con variant='masterball'/'monsterball'. Togliere rarity dalla UNIQUE di tcg_card. Migrazione id-preserving su copia DB con conteggi prima/dopo.
       perche: E l'UNICO modo definitivo per separare Kabutops 141/165 base da mirror e togliere il veto-astensione, recuperando copertura sulle carte di valore.
       rischio: Lavoro di schema/migrazione: backup obbligatorio, conteggi tcg_price prima/dopo, pytest indice verde. Non perdere storico. Richiede OK esplicito utente (lavoro strutturale).

## TEST FIXTURE
  • KILLER #1 CardRush Kabutops 141/165 SV2a = 3 righe stesso model_number/pack (master ¥1700, monster ¥400, standard ¥10): asserisce che la carta base ritorna ¥10, mai max() ¥1700. Salvare il __NEXT_DATA__ raw reale.
  • KILLER #2 Hareruya 141/165 = 'カブトプス:モンスターボールミラー〈141/165〉[SV2a-Mo][43617]' ¥100 + 'カブトプス:マスターボールミラー〈141/165〉[SV2a-Ma][43617a]' ¥1800: la carta base astiene (veto mirror), non pubblica ¥1800.
  • KILLER #3 Hareruya keyword 078/070 = 4 carte diverse su 4 set (ハピナスV[S6K]¥250, アーマーガアV[S5R]¥350, ポケモンブリーダー[S2a]¥700, ガラルファイヤーV:SA[S5a]¥26000): senza gate set+nome la guard 4x astiene; con gate set+nome resta solo la carta giusta. Prova che full_number non basta.
  • KILLER #4 collisione nome+numero: コイル 001/015 vs Pikachu V 001/015: il porta-nome Jaccard separa; se la nostra carta non e sulla fonte -> absent, mai prezzo dell'altra.
  • KILLER #5 CardRush failure mode #1: lista con 141/165 e 141/100 (set diverso) restituiti per model=141: il match numero PIENO scarta 141/100; il vecchio split('/')[0]=='141' li prendeva entrambi.
  • KILLER #6 sotto-set: sA 013/023 クイックボール vs sA 013/024 クイックボール (stesso nome, numeri adiacenti): il gate numero pieno distingue; nome identico non deve far agganciare l'altro.
  • KILLER #7 bucket その他 / numero senza denominatore ('-', '旧裏'): Query vuota = astensione, nessun prezzo.
  • BLINDATURA EXCEL: per i 294 Card Code dell'Excel (set_code + numero), test che (a) ognuno risolve a esattamente 1 carta in DB; (b) test_official_index_matches_excel_formula resta verde dopo ogni fix (indice byte-identico al foglio Charts); (c) snapshot buylist sulle 263 storiche: best_price invariato sulle confirmed, nessun cambio di id carta.
  • ANCORA TCGdex (offline, fixture JSON salvate): S12a-262 risolve 'アルセウスVSTAR' official=172; SV2a-141 'カブトプス' official=165; S8b-78 e sm8b-150 ritornano [] dalla query-by-localId -> fallback senza errore; その他/MC/'sm4 ' -> non ancorabile, nessuna eccezione.

## FASI
  [FASE A — Quick wins matcher (solo adapters.py/scrapers.py, NESSUNO schema)]
     - Backup DB: cp tcg_tracker.db tcg_tracker.backup.db
     - scrapers.py: print_tier_pokemon, _norm_set_tag, _name_jaccard; parse_hareruya emette set_tag+prod_code; fix pick_cardrush al numero pieno
     - adapters.py CardRush: numero pieno + porta nome + filtro tier + guard 4x; chiude failure mode #1 e #5 lato CR
     - adapters.py Hareruya: gate set (spoglia -Ma/-Mo) + nome Jaccard + veto mirror
     - Aggiungere le 7 fixture killer + le blindature Excel in tests/; pytest verde (incluso test indice)
     - Misurare health.json (tasso confirmed/da_verificare/absent) su una passata di prova; nessuna scrittura sul DB reale finche i test non sono verdi
  [FASE B — 3 livelli + pubblicazione sicura (database.py + vista v_buylist)]
     - save_price: stato 'da_verificare' per casi soft; best_price/best_source SOLO su confirmed+non-outlier in export_web
     - Modificare v_buylist per non spacciare carried/da_verificare come best_price; verificare diff-zero su confirmed
     - Lasciare _index()/serie ufficiale INTATTI; test_official_index_matches_excel_formula verde
     - health.json per fonte (absent/da_verificare) per distinguere 'matcher rotto' da 'carte assenti'
     - Commit di fase + aggiornare CLAUDE.md (trappole risolte, fasi)
  [FASE C — Ancora esterna TCGdex (offline, src/anchor.py + card_anchor)]
     - Aggiungere tabella card_anchor + colonna nullable tcg_card.external_id (migrazione additiva su copia, conteggi prima/dopo)
     - src/anchor.py: job batch TCGdex via HttpClient (backoff, cache), idempotente/incrementale; fixture JSON offline
     - Validazione denominatore (== cardCount.official) -> warning health.json; 404 -> astensione; porta-nome ancorata al nome canonico nei casi solo-CardRush
     - Salvare image_url canonica per pHash futuro (non gate)
     - Commit di fase
  [FASE D — Schema varianti Pokemon (con OK ESPLICITO utente; lavoro strutturale)]
     - Mostrare piano in max 10 righe e aspettare ok (vincolo CLAUDE.md)
     - Backup; migrazione id-preserving su COPIA: base resta su id storico, mirror = righe nuove variant='masterball'/'monsterball'; togliere rarity dalla UNIQUE
     - Conteggi tcg_price prima/dopo (storico invariato); test indice byte-identico verde
     - Rimuovere il veto-astensione dove la variante e ora modellata (recupero copertura sulle carte di valore)
     - Estendere lo stesso modello a YGO multi-rarita; commit + CLAUDE.md

## RISCHI RESIDUI
  ! Base-vs-mirror NON risolto fino alla Fase D (schema): in Fase A/B il veto mirror compra sicurezza con ASTENSIONI proprio sulle carte di maggior valore (le secret rare) -> quota 'da_verificare' ampia, da MISURARE (health.json) e comunicare al cliente, altrimenti si e tentati di allentare le soglie e tornano i falsi positivi.
  ! Soglie Jaccard 0.85 e AMBIGUITY_RATIO 4x sono euristiche NON ancora calibrate su ground-truth etichettato (>100 carte): mal tarate generano falsi negativi (carte giuste astenute) o falsi positivi.
  ! Selettori HTML Hareruya (.selling_price/.goods_name) e i nuovi campi set_tag/prod_code NON confermati sul DOM grezzo (WebFetch rende il modello, non l'HTML): validare su fixture HTTP reale prima di affidarvisi; rischio di gate set inerte se il tag non viene estratto.
  ! Cross-source puo confermare errori CORRELATI: se entrambe le fonti agganciano la stessa carta sbagliata per la stessa collisione di numero, i prezzi concordano e si promuove l'errore. Mitigato solo dall'ancora TCGdex (Fase C) e dal gate set; senza ancora resta un rischio residuo.
  ! Ancora TCGdex: ~30% del catalogo non ancorabile (の他 ~1889, MC, PROMO, BW-P, set con '+' che danno 404, bug 'sm4 ' con spazio) e query-by-localId talvolta [] su set/localId reali -> copertura del terzo segnale parziale, non azzera i falsi positivi sulle solo-CardRush non ancorate.
  ! Carry-forward resta nell'indice ufficiale (vincolo Excel): se una fonte cambia carta dietro lo stesso numero, il trend puo mostrare un prezzo non piu offerto. Confinato fuori dal best_price ma presente nel trend: segnalarlo.
  ! print_tier_pokemon dipende da stringhe di listing incoerenti tra negozi (マスターボールミラー nel nome vs -Ma nel tag vs 'a' nel codProd): coverage parziale, una stampa nuova non riconosciuta sfugge al veto -> in dubbio astenere, mai max(). Da estendere quando emergono nuovi pattern.
  ! DB cresce in fretta (append-only ~10k righe/notte): non e un rischio di correttezza ma di ops (Fase 5: salvare solo prezzi cambiati / DB fuori git).
