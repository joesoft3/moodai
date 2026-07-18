# 🚂 Railway — exact click-sheet for `joesoft3/moodai`

Everything below assumes [docs/BACKEND-HOSTING.md](BACKEND-HOSTING.md) Path A. This is the
copy-paste version — keep it open next to the Railway canvas.

## Services to create (Project canvas → + New)

| # | Service | How |
|---|---|---|
| 1 | **moodai** (the API) | Deploy from GitHub repo → `joesoft3/moodai` (reads `railway.toml` automatically) |
| 2 | **Postgres** | Database → Add PostgreSQL |
| 3 | **Redis** | Database → Add Redis |
| 4 | **Qdrant** | Empty Service → Source Image `qdrant/qdrant:latest` → Settings → attach Volume → Mount path `/qdrant/storage` |

## Variables on the `moodai` service (Variables tab → + New Variable / Reference)

Paste these **as variable references** (Railway auto-completes when you type `${{`):

```
DATABASE_URL = ${{Postgres.DATABASE_URL}}
REDIS_URL    = ${{Redis.REDIS_URL}}
QDRANT_URL   = http://${{Qdrant.RAILWAY_PRIVATE_DOMAIN}}:6333
```

Then raw values (get them from your local `.env` / providers):

```
JWT_SECRET   = <same value as your local .env — KEEP IT IDENTICAL or local logins invalidate>
XAI_API_KEY  = <console.x.ai>
OPENAI_API_KEY = <optional — voice + 2nd arena contestant>
GEMINI_API_KEY = <optional — 3rd arena contestant>
ADMIN_BOOTSTRAP_EMAIL    = admin@mood.local
ADMIN_BOOTSTRAP_PASSWORD = <your owner password>
CORS_ORIGINS = http://localhost:3000            ← add Netlify URL after step 5
FRONTEND_URL = http://localhost:3000            ← same here
```

> ⛔ Do **not** set `APP_PASSWORD` — it would re-enable the sign-up access-code gate we removed.

## Networking

1. `moodai` service → **Settings → Public Networking → Generate Domain**
   → `https://<something>.up.railway.app`
2. **Custom domain (optional now):** same panel → Custom Domain → `api.yourdomain.com`
   → Railway shows a **CNAME target** → add it at your DNS provider → wait for the ✅
3. Next.js on Netlify: env var `NEXT_PUBLIC_API_URL = https://<that-domain>/api/v1`
4. Back on Railway: extend `CORS_ORIGINS` = `http://localhost:3000,https://<your-site>.netlify.app`

## Optional add-on variables (any time later — Railway redeploys on change)

| Why | Variables |
|---|---|
| 🧩 Plugin Store real connects (Gmail/Calendar) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `BACKEND_PUBLIC_URL=https://<api-domain>` — guide: [PLUGIN-OAUTH](PLUGIN-OAUTH.md) |
| 🧩 GitHub plugin | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` |
| 🔔 Push notifications | `FCM_PROJECT_ID`, `FCM_SERVICE_ACCOUNT_JSON` — guide: [PUSH-NOTIFICATIONS](PUSH-NOTIFICATIONS.md) |
| 🌍 Custom domain | `CORS_ORIGINS`, `FRONTEND_URL`, `BACKEND_PUBLIC_URL` → see [CUSTOM-DOMAIN-SETUP](CUSTOM-DOMAIN-SETUP.md) |
| 💳 Stripe (later) | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID` |

## Verify (from any machine)

```bash
scripts/live-smoke.sh https://<something>.up.railway.app
```

Green board = register → chat → think → ⚔️ arena → quotas → meters all live.

## Campus map (where things live after deploy)

| What | Where |
|---|---|
| Owner panel | `https://<app-domain>/admin` (login with `ADMIN_BOOTSTRAP_*`) |
| Plugin store | `https://<app-domain>/plugins` |
| Analytics | owner panel → Analytics card |
| Domain white-labeling | Settings → Domains (on the live app) |
