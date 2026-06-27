// Cloudflare Worker per TCG Tracker.
// - Serve la dashboard statica (cartella dashboard/) tramite il binding ASSETS.
// - Espone POST /api/trigger che avvia il workflow GitHub "scrape.yml"
//   (aggiornamento prezzi on-demand), usando il token GH_TOKEN salvato come
//   secret su Cloudflare. Il token NON sta mai nella pagina.

const REPO = "Stefanosx181/tcg-tracker";
const WORKFLOW = "scrape.yml";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/trigger") {
      if (request.method !== "POST") {
        return json({ ok: false, error: "Usa POST" }, 405);
      }
      if (!env.GH_TOKEN) {
        return json({ ok: false, error: "Token GitHub non configurato (secret GH_TOKEN)" }, 503);
      }
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

    // tutto il resto: file statici della dashboard
    return env.ASSETS.fetch(request);
  },
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
