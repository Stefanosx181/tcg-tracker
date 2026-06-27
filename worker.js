// Cloudflare Worker per TCG Tracker.
// L'accesso e' protetto a monte da Cloudflare Access (Worker URL = "Restricted"):
// chi non e' autenticato non raggiunge nemmeno questo codice. Qui quindi:
//  - serviamo la dashboard statica (cartella dashboard/) tramite il binding ASSETS;
//  - esponiamo POST /api/trigger per avviare il workflow GitHub (richiede il
//    secret GH_TOKEN). L'utente e' gia' autenticato via Access.

const REPO = "Stefanosx181/tcg-tracker";
const WORKFLOW = "scrape.yml";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/trigger") {
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

    return env.ASSETS.fetch(request);
  },
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}
