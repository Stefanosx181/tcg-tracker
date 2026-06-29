# Redesign UI/UX — "Sumi 墨" (dashboard)

Redesign premium della dashboard `dashboard/index.html`, prodotto con un workflow
multi-agente (4 direzioni di design indipendenti → giuria a 3 lenti → blueprint), poi
una review avversariale a 4 dimensioni (correttezza JS, CSS/contrasto, responsive,
estetica) con triage. Questo documento è la sintesi di cosa è stato fatto e perché.

## Vincolo invalicabile rispettato
Le **CARD con immagine non sono state toccate**: regola `.grid` (minmax 186px),
`.tile`, `.imgbox` (aspect-ratio 3/4), `.tile img`, tutto il corpo card
(`.body/.nm/.meta/.code/.rar/.prices/.prow/.bar/.amb`), la funzione `tileEl`, e i
token-colore della card (`--card --line --txt --muted --cr --hr --yt --tt --best
--stale`) restano IDENTICI. È stata ridisegnata solo "la cornice".

## Direzione scelta: Sumi 墨 (inchiostro & vuoto)
Estetica radicata nel dominio (carte JP): dark stratificato, **un solo accento**
rosso-sigillo (`--f-seal #e0573f`, il bollo 印) che non collide con i colori-fonte
delle card. Tipografia: **Inter** per tutta la UI/numeri + **Zen Old Mincho** solo
per i display (wordmark, titoli set, titolo modal). Token cornice con prefisso
`--f-*` (superfici, hairline, ink, sigillo, raggi, ombre, motion) AGGIUNTI accanto
ai token-card invariati.

## Cosa è cambiato (solo cornice)
- **Header**: wordmark con sigillo 印 + occhiello "買取 · Mercato JP"; blur + ombra
  allo scroll (`header.scrolled`); pallino di freschezza **stato-dipendente** (verde
  solo se i dati sono ≤8 giorni, altrimenti ambra senza pulse).
- **Totali**: stat-chip per fonte con label micro + valore tabular e bordo nel colore
  della fonte (linguaggio cromatico coerente con card e legenda).
- **Schede gioco**: segmented control (pillole in un binario), firma-sigillo sotto la
  scheda attiva.
- **Toolbar**: search con icona lente, select con chevron custom, focus-ring sigillo;
  **¥/€ come segmented** (evidenzia la valuta ATTIVA); "Aggiorna ora" = CTA piena
  rosso-sigillo con spinner; messaggi come **toast** (l'esito OK resta finché non si
  ricarica). Filtri a sinistra, azioni/preferenze a destra.
- **Set-head**: blocco-card elegante, caret SVG che ruota, bordo-sigillo quando aperto.
- **Modal**: fade backdrop + sheet con scale/translate; **bottom-sheet su mobile**
  (grabber + safe-area iOS). Grafici (Chart.js): tick/griglia presi dal tema.
- **Stati**: skeleton di caricamento (solo intestazioni, coerente col render lazy
  "tutto chiuso"); empty-state con ensō + "Azzera filtri"; scrollbar custom;
  focus-visible globale; `prefers-reduced-motion`.

## Accessibilità / mobile
Contrasto AA verificato (ink/panel ~15:1, ink-3 su bg ~4.9:1, CTA ~7.4:1); touch
target ≥44px su mobile (inclusa la `.idxbtn` 44×44); tabs/totali scrollabili in
orizzontale; CTA full-width; modal bottom-sheet.

## Fix applicati dalla review
- **must**: `load()` e fetch di `buylist.json` con `.catch` → niente skeleton
  bloccato; stato d'errore esplicito.
- **should**: pallino freschezza non più "verde fisso"; rimossa la legenda-asterisco
  fissa dall'header (la spiegazione resta nel `title` delle tile); `.idxbtn` 44×44 su
  mobile; toast OK persistente; skeleton coerente (solo intestazioni); `#refreshMsg`
  vuoto nascosto.
- **polish**: chip-totale solo per fonti con valore; tasso EUR caricato prima del
  primo paint (no flash); scrollbar/err-toast tokenizzati; token morto `--f-hair-soft`
  rimosso e `--f-bg-soft` agganciato al gradiente; ensō/bottone-reset più visibili;
  `.set-tot` riordinato su mobile (niente 📈 orfano).

## Verifica
`node --check` OK; harness DOM (DOM finto + `buylist.json` reale): render lazy
(default 343 header / 0 tile, filtro set esatto, ricerca cap 400) e valuta
(¥10.000 ⇄ €62); card/ID confermati intatti; `pytest` 99 verdi; Flask serve la UI.
