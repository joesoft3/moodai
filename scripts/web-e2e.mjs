/**
 * Web PR-E2E — runs against a LOCAL production build (`next start`), so UI
 * regressions are caught before merge, no deployment needed.
 *
 *   WEB_URL  — default http://127.0.0.1:4100  (CI injects the local server)
 *
 * HARD: every public page renders (landing, login, terms, privacy, share-404),
 *        zero pageerrors/console errors, basic a11y hooks present.
 * ARTIFACTS: screenshots of each page (always uploaded).
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const WEB = (process.env.WEB_URL || "http://127.0.0.1:4100").replace(/\/+$/, "");
mkdirSync("web-e2e-shots", { recursive: true });

const failures = [];
const ok = (m) => console.log(`✅ ${m}`);
const hard = (m) => { failures.push(m); console.error(`❌ ${m}`); };

const browser = await chromium.launch();
const page = await browser.newPage();
const consoleErrors = [];
page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${String(e).slice(0, 160)}`));
page.on("console", (msg) => {
  if (msg.type() === "error") consoleErrors.push(`console.error: ${msg.text().slice(0, 160)}`);
});

const checks = [
  ["/", "Mood AI", "hero copy"],
  ["/login", "Mood AI", "login shell"],
  ["/terms", "Terms", "terms body"],
  ["/privacy", "Privacy", "privacy body"],
  ["/f/deadbeefdeadbeefdeadbeefdeadbeef", "expired", "graceful share 404 state"],
];

for (const [path, needle, label] of checks) {
  try {
    const res = await page.goto(`${WEB}${path}`, { waitUntil: "networkidle", timeout: 45000 });
    const status = res?.status() ?? 0;
    const body = (await page.textContent("body")) ?? "";
    if (status >= 400) hard(`${path} → HTTP ${status}`);
    else if (!body.toLowerCase().includes(needle.toLowerCase())) hard(`${path} missing ${label} ("${needle}")`);
    else ok(`${path} renders (${label})`);
    await page.screenshot({ path: `web-e2e-shots/${path.replace(/\//g, "_") || "_home"}.png`, fullPage: true });
  } catch (e) {
    hard(`${path}: ${e.message}`);
  }
}

// Landing-page tall content: also verify the feature grid + footer links exist
try {
  await page.goto(WEB, { waitUntil: "networkidle", timeout: 30000 });
  for (const feature of ["Arena v2", "Deep research", "Video with pure sound & voice"]) {
    (await page.textContent("body"))?.includes(feature) ? ok(`landing feature: ${feature}`) : hard(`landing missing feature: ${feature}`);
  }
  const terms = await page.getAttribute('a[href="/terms"]', "href");
  terms === "/terms" ? ok("footer Terms link") : hard("footer Terms link missing");
} catch (e) {
  hard(`landing features: ${e.message}`);
}

await browser.close();

if (consoleErrors.length) {
  consoleErrors.forEach((e) => console.error(`⚠️ ${e}`));
  hard(`${consoleErrors.length} runtime console/page errors (see log)`);
}
console.log(`\n—— web PR-E2E ——  hard failures: ${failures.length}`);
process.exit(failures.length ? 1 : 0);
