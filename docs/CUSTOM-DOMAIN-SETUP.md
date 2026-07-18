# 🌍 Custom domain — `app.yourdomain.com` (web) + `api.yourdomain.com` (API)

Move the app off the `.netlify.app` / `.up.railway.app` URLs onto your own domain.
Both hosts issue **free auto-TLS**. You'll touch your DNS provider once.
Prereq: your app already runs ([GO-LIVE-CLICKSHEET](GO-LIVE-CLICKSHEET.md) done).

> Convention: replace `yourdomain.com` with your real domain; `SITE.NETLIFY.APP` and
> `RAILWAY.TARGET` are the values the dashboards show you.

---

## 1️⃣ Web — Netlify

1. 🖱 Netlify site → **Domain management → Add a domain** → type `app.yourdomain.com` → **Verify → Add domain**.
2. 🖱 At your DNS provider (Cloudflare, GoDaddy, Namecheap…) add:

   | Type | Host/Name | Value |
   |---|---|---|
   | `CNAME` | `app` | `SITE.NETLIFY.APP` |

3. ⏳ Wait for the green 🔒 (Netlify auto-issues Let's Encrypt; usually 1–15 min, up to 24 h).

**Apex instead?** Want `yourdomain.com` with no subdomain → use an `A` record to `75.2.60.5`
(+ `AAAA` `99.83.190.102`) or transfer DNS to **Netlify DNS** (easiest; it manages everything).

## 2️⃣ API — Railway

1. 🖱 Railway → *moodai* service → **Settings → Networking → Public Networking → + Custom domain** → type `api.yourdomain.com`. Railway shows the **CNAME target**.
2. 🖱 DNS record:

   | Type | Host/Name | Value |
   |---|---|---|
   | `CNAME` | `api` | *〈target Railway gave you〉* |

3. ⏳ Certificate auto-provisions; `https://api.yourdomain.com/healthz` should answer.

## 3️⃣ Point every piece at the new names

| Where | Variable | New value |
|---|---|---|
| Netlify (Site → Env vars) | `NEXT_PUBLIC_API_URL` | `https://api.yourdomain.com/api/v1` *(triggers a redeploy)* |
| Railway (Variables) | `CORS_ORIGINS` | `https://app.yourdomain.com` |
| Railway | `FRONTEND_URL` | `https://app.yourdomain.com` |
| Railway | `BACKEND_PUBLIC_URL` | `https://api.yourdomain.com` |
| Google OAuth client ➜ redirect URIs | both `/plugins/*/callback` URLs | now on `api.yourdomain.com` |
| GitHub OAuth App ➜ callback URL | same idea | now on `api.yourdomain.com` |
| GitHub repo secret (optional, mobile) | `MOOD_MOBILE_API_URL` | `https://api.yourdomain.com/api/v1` |

✅ Re-run the acceptance pass:

```bash
WEB_URL=https://app.yourdomain.com scripts/live-smoke.sh https://api.yourdomain.com
```

Every line green = domain cutover complete. 🎉

## 4️⃣ Beyond — white-label arenas on customer domains

Custom domains are also how the 🌐 **white-label arena** product works: each customer
domain serves a branded arena (per-domain judge, panel, daily cap — settings UI).
That architecture (VPS + Caddy on-demand TLS, because Railway/Render can't do wildcard
TLS) is detailed in [CUSTOM-DOMAIN-SALES-PAGE](CUSTOM-DOMAIN-SALES-PAGE.md).

*The removed-by-design note: domains you add via the app's 🌐 Domains screen are validated
through `GET /domains/allowed` + the `x-mood-host` header — the platform serves them only
after DNS points in.*
