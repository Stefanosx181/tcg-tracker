// Cloudflare Worker per TCG Tracker.
// L'accesso e' protetto a monte da Cloudflare Access (Worker URL = "Restricted").
// Questo Worker:
//  - (opzionale) valida il JWT di Access cosi' richieste che AGGIRANO Access
//    vengono respinte. Attivo solo se la variabile ENFORCE_JWT = "1"
//    (cosi' non c'e' rischio di lock-out: si abilita/disabilita a piacere).
//  - serve la dashboard statica (cartella dashboard/) via il binding ASSETS.
// NB: l'aggiornamento prezzi e' SOLO automatico (cron GitHub Actions). Niente
// trigger on-demand: nessun endpoint /api/trigger -> niente superficie da proteggere.

const TEAM_DOMAIN = "tcgtracker.cloudflareaccess.com";
const AUD = "5c0f3bdeb6f916d8deaca883176055b57df6849b5ac3c2ac84654452e188db30";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Difesa in profondita': se abilitata, richiede un JWT di Access valido.
    if (env.ENFORCE_JWT === "1") {
      const ok = await verifyAccessJWT(request);
      if (!ok) return json({ ok: false, error: "Accesso non valido" }, 403);
    }

    // La pagina e i JSON dei dati cambiano ad ogni scrape ma hanno URL fisso:
    // senza questo, browser/CDN servono versioni VECCHIE (modifiche "non visibili").
    // Le immagini restano cacheabili (hanno nomi nuovi quando cambiano).
    const res = await env.ASSETS.fetch(request);
    const p = url.pathname;
    const noCache = p === "/" || p.endsWith(".html") ||
                    (p.startsWith("/data/") && p.endsWith(".json"));
    if (noCache) {
      const r = new Response(res.body, res);
      r.headers.set("Cache-Control", "no-cache, must-revalidate");
      return r;
    }
    return res;
  },
};

// ----------------------------------------------------------------------
// Validazione del JWT di Cloudflare Access (RS256, verifica firma + claims)
let JWKS_CACHE = null, JWKS_TS = 0;

async function getJWKS() {
  const now = Date.now();
  if (JWKS_CACHE && now - JWKS_TS < 3600000) return JWKS_CACHE;
  const r = await fetch(`https://${TEAM_DOMAIN}/cdn-cgi/access/certs`);
  const j = await r.json();
  JWKS_CACHE = j.keys || [];
  JWKS_TS = now;
  return JWKS_CACHE;
}

function getToken(request) {
  const h = request.headers.get("Cf-Access-Jwt-Assertion");
  if (h) return h;
  const cookie = request.headers.get("Cookie") || "";
  const m = cookie.match(/(?:^|;\s*)CF_Authorization=([^;]+)/);
  return m ? m[1] : null;
}

function b64urlBytes(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const bin = atob(s);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}
function b64urlJSON(s) {
  return JSON.parse(new TextDecoder().decode(b64urlBytes(s)));
}

async function verifyAccessJWT(request) {
  try {
    const token = getToken(request);
    if (!token) return false;                 // nessun token = richiesta che aggira Access
    const [h, p, s] = token.split(".");
    if (!h || !p || !s) return false;
    const header = b64urlJSON(h);
    const payload = b64urlJSON(p);

    const now = Math.floor(Date.now() / 1000);
    if (payload.iss !== `https://${TEAM_DOMAIN}`) return false;
    const aud = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
    if (!aud.includes(AUD)) return false;
    if (payload.exp && now >= payload.exp) return false;
    if (payload.nbf && now < payload.nbf) return false;

    const jwk = (await getJWKS()).find((k) => k.kid === header.kid);
    if (!jwk) return false;
    const key = await crypto.subtle.importKey(
      "jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]
    );
    return await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5", key, b64urlBytes(s), new TextEncoder().encode(`${h}.${p}`)
    );
  } catch (_) {
    return false;
  }
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}
