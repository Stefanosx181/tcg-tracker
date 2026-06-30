# Piano correttezza prezzi — "Carta giusta o niente"

> Output di un'analisi multi-agente (ricerca modi di fallimento → 4 design indipendenti →
> critica avversariale → sintesi). App per un cliente: **un prezzo sbagliato è inaccettabile**.

## Principio cardine
Conferma SOLO se ogni segnale di identità NOTO concorda (AND, non OR) e il prezzo passa i gate
di sanità; altrimenti **astieniti** esplicitamente. Meglio "da verificare"/"nessun prezzo" che
un prezzo sbagliato silenzioso.

## Causa radice (verificata sui dati)
- Lo **schema non modella le varianti di stampa**: tutte le 10.191 carte Pokémon hanno
  `variant=''` → base vs Master/Monster Ball Mirror indistinguibili (Kabutops 141/165:
  monsterball ¥100 vs masterball ¥1.800). È il failure mode #5, NON risolvibile senza schema.
- Gate inerti dove servono: cross-source copre ~263 carte (HR parte da lì); rarità vuota/sporca
  sul 24,5% del catalogo; ~5.000 carte solo-CardRush (nessun secondo segnale).
- Collisione numero massiccia: `078/070` esiste in 11 set; 387 numeratori condivisi.
- `adapters.py:181` (CardRush) fa ancora match sul **solo numeratore** = failure mode #1.

## Identità a porte AND (sempre la carta giusta)
1. Numero PIENO (num+den, no zeri iniziali) — fatto su HR; **da fare su CR (riga 181)**.
2. Nome per **uguaglianza segmento + Jaccard ≥0.85** (non substring). Normalizzare entrambi i
   lati (i nostri nomi contengono `(` e `:`, es. `(CD付未開封)ピカチュウ`, `タイプ:ヌル`).
3. Rarità come porta SOLO se nota e non simbolo (skip, non reject, se vuota/★/☆/◆).
4. Marcatore di stampa: carta standard + unico listing mirror → **astieniti**.
5. Selezione: candidato che passa tutte le porte; >1 distinto → astieniti. MAI la mediana.
6. Bucket その他 / number '-' / senza denominatore → non identificabile → astensione.

## Gate di sanità (sempre prezzo confermato)
- A. Filtro rumore (`is_noise_listing`) esteso a Pokémon/YGO + vocabolario game-specifico
  (PSA/BGS/鑑定/プロモ/デッキ/ジャンボ/box) con whitelist anti-falso-negativo.
- B. Banda per `(game,rarity)` mediana+IQR su confirmed validati → `is_outlier=2` fuori banda,
  escluso dal best_price. NON declassare sui bucket rarità vuoti/contenitore.
- C. Accordo cross-source (Pokémon) SOLO come declassamento (>3× → da_verificare), mai promozione.
- D. Guard ambiguità 4x come backstop (cieco sotto soglia: la porta-nome deve separare).
- E. Canary anti-drift per fonte + check label 買取/販売 nel DOM (buyback vs vendita).
- F. Monitor tasso absent/da_verificare (`health.json`): crescita = matcher rotto, non "carte assenti".
- G. Carry-forward: resta nell'indice (vincolo Excel) ma mai best_price "sicuro".

## 3 livelli di confidenza
- ALTA (confirmed): tutte le porte + sanità → pubblica (best_price/movers/spread).
- MEDIA (da_verificare): plausibile ma un gate fallisce / single-source / carried → badge,
  escluso da best_price, → coda revisione.
- BASSA (absent): nessun nome combacia / solo mirror / non identificabile / ambiguo → nessun prezzo.

## Coda di revisione umana + cache
- `review_queue(card_id, source, reason, candidates_json, status, ...)` popolata da save_price.
- `confirmation_cache` ancorata a un **FINGERPRINT del listing** (numero+nome-listing+prezzo+
  marcatore+source) con `expires_at` e invalidazione quando il fingerprint cambia — NON a
  numero+nome (instabile). `review.html` dietro Access JWT; POST /api/review nel worker.
- Prioritizzare per valore, lotti piccoli, niente "approva tutto", cache invalidabile.

## Fasi
- **A** (quick wins, solo matcher/parse, no schema): noise-filter Pokémon/YGO; CR match numero
  pieno; nome Jaccard; veto mirror; best_price solo-confirmed; canary+label; fixture casi-killer.
- **B** (gate + 3 livelli in database.py/export; indice ufficiale byte-identico).
- **C** (coda umana + cache conferme).
- **D** (schema varianti base/mirror per Pokémon, come One Piece; migrazione id-preserving; YGO
  multi-rarità). Lavoro di schema → pianificare a parte con ok dell'utente.

## Rischi residui
- Base-vs-mirror non risolto fino alla Fase D.
- Sicurezza comprata con astensioni → quota ampia "da verificare"; comunicarlo al cliente e
  MISURARLO, o si allentano le soglie e tornano i falsi positivi.
- Soglie da calibrare su ground-truth etichettato >100 carte.
- Verifica per immagine (pHash/OCR numero) + DB ufficiale (identità più forte) rinviate.
- Cross-source può confermare errori correlati; drift parziale può sfuggire al canary.

_Sorgente completa (ricerca + 4 design + critiche): workflow always-correct-card-price._
