# 🚀 Deploy the Mood AI web app to Netlify

The repo ships a ready `netlify.toml` — the frontend deploys as-is. The FastAPI
backend runs separately (any Docker host; see `docs/DEPLOY-WALKTHROUGH.md` for the
full 0→live path including Postgres/Redis/Qdrant, Caddy TLS, Stripe webhooks).

---

## Option A — Git-connected (recommended, auto-deploys on push)

1. Push the repo to GitHub/GitLab.
2. Netlify → **Add new site → Import an existing project** → pick the repo.
3. Netlify detects `netlify.toml` and pre-fills:
   - **Base directory:** `frontend`
   - **Build command:** `npm run build`
   - **Publish:** `frontend/.next` (handled by the Next.js runtime plugin)
4. **Site settings → Environment variables → Add:**

   | Key | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | `https://api.your-domain.com/api/v1` ← your deployed backend |

5. Deploy. Your preview URL: `https://<random-name>.netlify.app`.

## Option B — CLI (one-off or from this workspace)

```bash
cd frontend
npm install
npx netlify-cli login                       # once — opens browser auth
npx netlify-cli init                        # link/create the site (or --manual)
NEXT_PUBLIC_API_URL=https://api.your-domain.com/api/v1 \
  npx netlify-cli deploy --build --prod
```

Every deploy also prints a **draft preview URL** (`--prod` promotes it).

---

## ⚠️ Two server-side settings after your first deploy

1. **CORS** — allow the Netlify origin on the backend (`.env`):
   ```env
   CORS_ORIGINS=http://localhost:3000,https://<your-site>.netlify.app,https://app.your-domain.com
   ```
2. **Streaming** — chat/Arena use SSE fetch streams. Netlify's Next.js runtime
   streams these natively; just don't put a buffering proxy in between. The app
   already sends `Accept: text/event-stream` and the API sets `X-Accel-Buffering: no`.

## Custom domain on Netlify

- **Site settings → Domain management → Add a domain** → point DNS at Netlify.
- White-label business domains bought/connected **inside Mood AI** still terminate
  at your Caddy edge (`docs/DEPLOY-WALKTHROUGH.md` §Custom domains) — Netlify hosts
  *your* platform app, Caddy serves *your customers'* domains.

## Verify the deploy

```bash
# backend first
scripts/live-smoke.sh https://api.your-domain.com
# then open the Netlify URL and: log in → send a chat → toggle ⚔️ Arena → run a debate
```

Troubleshooting: build log if `tsc`/lint fails · Netlify **Functions** log if SSR
500s · browser Network tab for `NEXT_PUBLIC_API_URL` typos (it is *build-time*
inlined — changing it requires a rebuild).
