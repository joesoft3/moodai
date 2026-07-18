/**
 * Mood AI — weekly live E2E (Playwright + native fetch).
 *
 *   WEB_URL  — e.g. https://mood-ai.netlify.app
 *   API_URL  — https://<railway>.up.railway.app  (root OR full .../api/v1 — both accepted)
 *
 * HARD checks fail the job (deploy broken):  health, home/legal pages, auth
 * round-trip, authed API, and admin/media route presence.
 * SOFT checks only print ::warning (provider keys may be absent):  first AI
 * stream bytes, arena page reachability.
 * Screenshots land in e2e-shots/ and upload as an artifact on failure.
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const WEB_URL = (process.env.WEB_URL || "").replace(/\/+$/, "");
const RAW_API = (process.env.API_URL || "").replace(/\/+$/, "");
if (!WEB_URL || !RAW_API) {
  console.log("::notice::WEB_URL/API_URL missing — set LIVE_WEB_URL / LIVE_API_URL. Skipping.");
  process.exit(0);
}
const origin = new URL(RAW_API).origin;
const API = RAW_API.endsWith("/api/v1") ? RAW_API : `${origin}/api/v1`;
const SHOTS = "e2e-shots";
mkdirSync(SHOTS, { recursive: true });

const failures = [];
const soft = [];
const ok = (m) => console.log(`✅ ${m}`);
const hard = (m) => { failures.push(m); console.error(`❌ HARD: ${m}`); };
const warn = (m) => { soft.push(m); console.warn(`::warning::SOFT: ${m}`); };

async function get(url, opts = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), opts.timeout ?? 20000);
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

/* ------------------------------------------------------------- API: health */
try {
  const h = await get(`${origin}/healthz`);
  const r = await get(`${origin}/readyz`);
  h.status === 200 && r.status === 200 ? ok("API health + readiness 200") : hard(`health ${h.status} / ready ${r.status}`);
} catch (e) {
  hard(`API unreachable: ${e.message}`);
}

/* ----------------------------------------------------------------- auth */
const email = `e2e-${Date.now()}@mood-e2e.test`;
const password = `E2e-${Math.random().toString(36).slice(2)}-pass!`;
let token = null;
try {
  const res = await get(`${API}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, display_name: "E2E Bot" }),
  });
  if (res.status === 201) {
    token = (await res.json()).access_token;
    ok(`registered ${email}`);
  } else {
    hard(`register → ${res.status}: ${(await res.text()).slice(0, 140)}`);
  }
} catch (e) {
  hard(`register failed: ${e.message}`);
}

const authHeaders = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
let convId = null;
if (token) {
  try {
    const res = await get(`${API}/conversations`, { method: "POST", headers: authHeaders, body: JSON.stringify({ title: "E2E smoke chat" }) });
    if (res.status === 201) {
      convId = (await res.json()).id;
      ok("authed conversation create");
    } else hard(`conversation create → ${res.status}`);
  } catch (e) {
    hard(`conversation create: ${e.message}`);
  }
}

/* --------------------------------- deploy version probes (routes exist) */
for (const [method, path, label] of [
  ["POST", "/media/videos", "video+sound route"],
  ["GET", "/admin/devices", "admin devices route"],
  ["POST", "/admin/push-test", "admin push-test route"],
]) {
  try {
    const res = method === "GET" ? await get(`${API}${path}`) : await get(`${API}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    [401, 403, 422].includes(res.status)
      ? ok(`${label} wired (auth-gated ${res.status})`)
      : res.status === 404 ? hard(`${label} missing on this deploy`) : ok(`${label} reachable (${res.status})`);
  } catch (e) {
    hard(`${label}: ${e.message}`);
  }
}

/* ------------------------------------------------- SOFT: first AI tokens */
if (token && convId) {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 45000);
    const res = await fetch(`${API}/chat/stream`, {
      method: "POST",
      headers: authHeaders,
      body: JSON.stringify({ conversation_id: convId, content: "Reply with exactly: MOOD_E2E_OK" }),
      signal: ctrl.signal,
    });
    const reader = res.body.getReader();
    const first = await Promise.race([reader.read(), new Promise((_, j) => setTimeout(() => j(new Error("no tokens in 40s")), 40000))]);
    clearTimeout(t);
    res.status === 200 && first.value ? ok("chat stream produced tokens") : warn(`chat stream status ${res.status}`);
  } catch (e) {
    warn(`chat stream: ${e.message} (AI keys not set on this deploy?)`);
  }
}

/* ------------------------------------------------------------ UI (chromium) */
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("pageerror", (e) => warn(`console error: ${String(e).slice(0, 120)}`));
async function shot(name) {
  try { await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true }); } catch { /* best effort */ }
}
try {
  await page.goto(WEB_URL, { waitUntil: "networkidle", timeout: 45000 });
  (await page.title()) ? ok(`home rendered: "${await page.title()}"`) : hard("home title empty");
  const bodyText = await page.textContent("body");
  bodyText?.includes("Mood AI") ? ok("hero copy present") : hard("home missing brand copy");
  for (const legal of ["terms", "privacy"]) {
    const res = await get(`${WEB_URL}/${legal}`);
    res.status === 200 ? ok(`/${legal} 200`) : hard(`/${legal} → ${res.status}`);
  }
  if (token) {
    await page.addInitScript((t) => localStorage.setItem("mood_token", t), token);
    for (const route of ["chat", "deepsearch", "images", "plugins"]) {
      try {
        await page.goto(`${WEB_URL}/${route}`, { waitUntil: "networkidle", timeout: 45000 });
        const txt = (await page.textContent("body")) ?? "";
        txt.length > 200 ? ok(`/${route} app shell renders`) : warn(`/${route} thin render`);
      } catch (e) {
        route === "chat" ? hard(`/chat failed: ${e.message}`) : warn(`/${route}: ${e.message}`);
      }
    }
    await shot("chat");
  }
} catch (e) {
  await shot("failure");
  hard(`web flow: ${e.message}`);
} finally {
  await browser.close();
}

/* ---------------------------------------------------------------- report */
console.log(`\n—— E2E summary ——  hard failures: ${failures.length}, soft warnings: ${soft.length}`);
failures.forEach((f) => console.error(`  ❌ ${f}`));
soft.forEach((s) => console.warn(`  ⚠️ ${s}`));
process.exit(failures.length ? 1 : 0);
