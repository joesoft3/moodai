# ⚙️ Backend hosting — get the FastAPI side answering real requests

The Netlify app needs `NEXT_PUBLIC_API_URL` pointing at a **deployed backend**.
Pick one path — all assume your `.env` is provisioned (`scripts/provision-env.sh`).

---

## Path A — Vercel (serverless, free tier, ~6 min)

The full click-by-click guide ships as **[docs/DEPLOY-VERCEL.md](DEPLOY-VERCEL.md)**.

TL;DR: import `joesoft3/moodai` → Root Directory **`backend`** → add env vars
(hosted Postgres/Supabase `DATABASE_URL` is the only hard requirement beyond
`JWT_SECRET` + `XAI_API_KEY`) → Deploy → `/healthz` returns `{"ok":true}`.
Every push to `main` can auto-deploy via the shipped `deploy-vercel` GitHub Action.

Serverless differences to know (details + fixes in the guide): uploads/media
live in `/tmp` (ephemeral), 60 s request budget on Hobby, voice **live**
WebSocket unavailable (HTTP voice works), memory embeddings go through the
OpenAI-compatible API (slim image — no local ONNX).

## Path B — Railway (container, ~10 min)

1. [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo** → `joesoft3/moodai`.
2. The repo ships **`railway.toml`** at the root — it points the builder at `backend/Dockerfile`,
   sets the `/healthz` healthcheck, and adds restart policy. **No root-directory fiddling needed.**
   (If Railway ever ignores it: Settings → Build → Dockerfile path = `backend/Dockerfile`.)
3. Add the data services from the Railway catalog: **PostgreSQL**, **Redis**, and a
   template service for **Qdrant** (image `qdrant/qdrant`, port 6333, attach a volume at `/qdrant/storage`).
4. Set env vars on the API service:
   ```
   DATABASE_URL=postgresql+asyncpg://<railway-pg-url>
   REDIS_URL=<railway-redis-url>
   QDRANT_URL=http://<qdrant-service>:6333
   XAI_API_KEY=...   (plus OPENAI/GEMINI for the full arena)
   JWT_SECRET=<from .env>   ADMIN_BOOTSTRAP_PASSWORD=<owner>
   STRIPE_* if billing
   CORS_ORIGINS=https://<your-site>.netlify.app
   FRONTEND_URL=https://<your-site>.netlify.app
   BASE_DOMAIN=<your railway domain>
   ```
5. **Settings → Public Networking → Generate Domain** → `https://<svc>.up.railway.app`.
6. Point Netlify's `NEXT_PUBLIC_API_URL` at `https://<svc>.up.railway.app/api/v1`.
7. Verify: `scripts/live-smoke.sh https://<svc>.up.railway.app`

Uploads are ephemeral on Railway free tiers — attach a volume at `/data/storage`
and set `UPLOAD_DIR=/data/storage`.

## Path C — Render (blueprint, ~15 min)

`render.yaml` ships in the repo — Render → **New → Blueprint** → paste the repo URL.
It spins up: the API (Docker), managed Postgres, managed Redis, and Qdrant.
Fill the secret env vars when prompted, add the Netlify origin to `CORS_ORIGINS`,
then run the smoke script against `https://<svc>.onrender.com`.

## Path D — Any VPS (full control)

The complete Docker-compose path (API + Postgres + Redis + Qdrant + Caddy with
automatic TLS for your domain and customers' white-label domains) is in
**[DEPLOY-WALKTHROUGH.md](DEPLOY-WALKTHROUGH.md)**. TL;DR:

```bash
git clone https://github.com/joesoft3/moodai && cd moodai
scripts/provision-env.sh            # fill in keys
docker compose up -d --build
scripts/smoke.sh https://api.your-domain.com
```

Point DNS `api.your-domain.com` at the VPS before step 3 so Caddy can issue TLS.

---

## After the backend is live

| Where | Setting |
|---|---|
| Netlify env vars | `NEXT_PUBLIC_API_URL = https://<backend>/api/v1` |
| Backend `.env` | `CORS_ORIGINS` includes the Netlify URL (+ your custom app domain) |
| Stripe dashboard | webhook → `https://<backend>/api/v1/billing/webhook`, copy signing secret to `STRIPE_WEBHOOK_SECRET` |
| Owner bootstrap | hit `/login` with `ADMIN_BOOTSTRAP_EMAIL`/`_PASSWORD` once → becomes platform admin |

Then the real proof: `scripts/live-smoke.sh https://<backend>` — register gate,
chat, think mode, arena, quota, meters, (optional) Stripe checkout, all green.
