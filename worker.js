// Cloudflare Worker per TCG Tracker.
// - Gate di accesso con password (secret SITE_PASSWORD): senza login non si vede
//   nulla (ne' pagina ne' dati). Cookie firmato (HMAC) come prova di accesso.
// - Serve la dashboard statica (cartella dashboard/) tramite il binding ASSETS.
// - POST /api/trigger avvia il workflow GitHub (richiede login + secret GH_TOKEN).

const REPO = "Stefanosx181/tcg-tracker";
const WORKFLOW = "scrape.yml";
const COOKIE = "tcgauth";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // --- endpoint di autenticazione (sempre raggiungibili) ---
    if (path === "/login" && request.method === "POST") {
      const form = await request.formData();
      const pw = (form.get("password") || "").toString();
      if (env.SITE_PASSWORD && pw === env.SITE_PASSWORD) {
        const token = await authToken(env.SITE_PASSWORD);
        return new Response(null, {
          status: 302,
          headers: {
            "Location": "/",
            "Set-Cookie": `${COOKIE}=${token}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=31536000`,
          },
        });
      }
      return loginPage("Password errata.", 401);
    }
    if (path === "/logout") {
      return new Response(null, {
        status: 302,
        headers: {
          "Location": "/",
          "Set-Cookie": `${COOKIE}=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0`,
        },
      });
    }

    // --- controllo accesso ---
    const authed = await isAuthed(request, env);
    if (!authed) {
      // navigazione -> mostra login; richieste non-GET -> 401
      if (request.method === "GET") return loginPage();
      return json({ ok: false, error: "Non autorizzato" }, 401);
    }

    // --- trigger scraping (solo loggati) ---
    if (path === "/api/trigger") {
      if (request.method !== "POST") return json({ ok: false, error: "Usa POST" }, 405);
      if (!env.GH_TOKEN) return json({ ok: false, error: "Token GitHub non configurato (secret GH_TOKEN)" }, 503);
      const gh = await fetch(
        `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
        {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${env.GH_TOKEN}`,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "tcg-tracker-worker",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ ref: "main" }),
        }
      );
      if (gh.status === 204) return json({ ok: true });
      let detail = "";
      try { detail = (await gh.json()).message || ""; } catch (_) {}
      return json({ ok: false, error: `GitHub ${gh.status}: ${detail}` }, 502);
    }

    // --- file statici della dashboard ---
    return env.ASSETS.fetch(request);
  },
};

// ----------------------------------------------------------------------
async function isAuthed(request, env) {
  if (!env.SITE_PASSWORD) return true; // gate non attivo finche' non c'e' la password
  const token = await authToken(env.SITE_PASSWORD);
  const cookie = request.headers.get("Cookie") || "";
  return cookie.split(/;\s*/).some((c) => c === `${COOKIE}=${token}`);
}

async function authToken(pw) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(pw),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode("tcg-auth-v1"));
  return btoa(String.fromCharCode(...new Uint8Array(sig))).replace(/[^a-zA-Z0-9]/g, "");
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}

function loginPage(error = "", status = 200) {
  const err = error ? `<p class="err">${error}</p>` : "";
  const html = `<!DOCTYPE html><html lang="it"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>Accesso — TCG Tracker</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
       background:#0f1320;color:#e6e9f2;font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif}
  .box{background:#161b2c;border:1px solid #27304a;border-radius:14px;padding:28px;width:min(360px,92vw)}
  h1{font-size:18px;margin:0 0 4px} p.sub{color:#8b94ad;font-size:13px;margin:0 0 18px}
  label{display:block;font-size:12px;color:#8b94ad;margin-bottom:6px}
  input{width:100%;background:#0f1320;color:#e6e9f2;border:1px solid #27304a;border-radius:9px;
        padding:11px 12px;font-size:15px}
  button{width:100%;margin-top:14px;background:#1d3a5f;border:1px solid #2c5a8f;color:#cfe4ff;
         border-radius:9px;padding:11px;font-size:15px;cursor:pointer}
  button:hover{background:#234a78}
  .err{color:#ff8a5a;font-size:13px;margin:0 0 12px}
</style></head><body>
  <form class="box" method="POST" action="/login">
    <h1>TCG Tracker</h1><p class="sub">Area riservata — inserisci la password</p>
    ${err}
    <label for="p">Password</label>
    <input id="p" name="password" type="password" autofocus autocomplete="current-password">
    <button type="submit">Entra</button>
  </form>
</body></html>`;
  return new Response(html, { status, headers: { "Content-Type": "text/html; charset=utf-8" } });
}
