/**
 * HF reader study — relay for networks that block Google.
 *
 * A Cloudflare Worker (free tier) that forwards a submission from the study page to the Apps Script
 * from Cloudflare's network, and returns the Apps Script's JSON answer. No secrets: the Apps Script URL
 * is the same one that is already public in docs/config.js. The page uses it only when the direct
 * request to script.google.com fails.
 *
 * Deploy (about 5 minutes, no CLI):
 *   1. dash.cloudflare.com → Workers & Pages → Create → Worker → name it e.g. "hf-reader-relay" → Deploy.
 *   2. Edit code → replace everything with this file → set APPS_SCRIPT_URL below → Deploy.
 *   3. Copy the worker URL (https://hf-reader-relay.<account>.workers.dev) into docs/config.js as `relay`.
 *   Optional: Settings → Domains & Routes lets you serve it from your own domain if workers.dev is blocked.
 */

const APPS_SCRIPT_URL = "https://script.google.com/macros/s/REPLACE_ME/exec";
const ALLOWED_ORIGIN = "https://njdong.github.io";       // the study page; "*" during local testing

const cors = {
  "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    const url = new URL(request.url);
    try {
      let upstream;
      if (request.method === "POST") {
        const body = await request.text();
        if (body.length > 200000) return json({ ok: false, error: "too_large" }, 413);
        upstream = await fetch(APPS_SCRIPT_URL, { method: "POST", headers: { "Content-Type": "text/plain;charset=utf-8" }, body, redirect: "follow" });
      } else if (request.method === "GET" && url.searchParams.get("r")) {
        // resume lookup: ?r=CODE -> {ok, done:[...]}
        upstream = await fetch(APPS_SCRIPT_URL + "?r=" + encodeURIComponent(url.searchParams.get("r")), { redirect: "follow" });
      } else {
        return json({ ok: true, relay: "hf-reader-study" });
      }
      const text = await upstream.text();
      return new Response(text, { status: 200, headers: { ...cors, "Content-Type": "application/json" } });
    } catch (e) {
      return json({ ok: false, error: "relay_upstream" }, 502);
    }
  },
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { ...cors, "Content-Type": "application/json" } });
}
