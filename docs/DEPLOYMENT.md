# Deployment guide — public URL in ~30 minutes

Target production shape: **Vercel** (frontend) + **container host** (FastAPI) +
**managed Postgres/Redis/Qdrant**. Everything below is free-tier friendly.

---

## 1. Backend API (pick one host)

Both options build straight from `backend/Dockerfile`.

### Option A — Railway
1. Push this repo to GitHub.
2. Railway → **New Project → Deploy from GitHub repo** → select repo, set root directory to `backend`.
3. Railway detects the Dockerfile automatically. It assigns a public domain like `mood-ai.up.railway.app`.
4. Add a **volume** mounted at `/app/storage` (uploads).

### Option B — Render
1. **New → Web Service → from GitHub repo**, root directory `backend`, runtime **Docker**.
2. Render gives you `https://mood-ai.onrender.com`.

## 2. Managed data services

| Service | Free option | Env var to set on the API |
|---|---|---|
| **Postgres** | Neon / Supabase | `DATABASE_URL=postgresql+asyncpg://user:pass@host/db` |
| **Redis** | Upstash | `REDIS_URL=rediss://default:pass@host:6379` (fail-open: rate limits just disable) |
| **Qdrant** | Qdrant Cloud (1 GB free) | `QDRANT_URL=https://<cluster>.cloud.qdrant.io` |
| **Uploads** | host volume (or S3 later) | `UPLOAD_DIR=/app/storage` |

## 3. API environment variables

Set on the API host (dashboard → environment):

```
XAI_API_KEY=... (required)
OPENAI_API_KEY=... (voice)
JWT_SECRET=<long random string>
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=rediss://...
QDRANT_URL=https://...
CORS_ORIGINS=https://<your-vercel-app>.vercel.app
FRONTEND_URL=https://<your-vercel-app>.vercel.app
STRIPE_* (optional, for subscriptions)
AUTO_CREATE_TABLES=false          # production: use migrations (below)
OTEL_EXPORTER_OTLP_ENDPOINT=      # optional tracing collector, e.g. http://jaeger:4318
```

**Migrations in production:** run `alembic upgrade head` on deploy (the Docker CMD does this
automatically; with `AUTO_CREATE_TABLES=false` migrations are the single source of truth).
Adopting migrations on an existing database: `alembic stamp 0001_initial && alembic upgrade head`.

**Kubernetes probes:** `livenessProbe → /healthz`, `readinessProbe → /readyz`.
**Monitoring:** scrape `/metrics` with Prometheus; dashboard panels: LLM latency by model,
active SSE streams, request rate/error rate per route.

Tables and Qdrant collections self-create on first boot.

## 4. Frontend on Vercel

1. Vercel → **Add New → Project** → import the repo.
2. **Root Directory: `frontend`** (this is the monorepo step people forget).
3. Env var:
   ```
   NEXT_PUBLIC_API_URL=https://<your-api-domain>/api/v1
   ```
4. Deploy → you get `https://<your-app>.vercel.app`.

Vercel auto-detects Next.js; `frontend/vercel.json` is included for explicitness.

## 5. Post-deploy checklist

- [ ] `/healthz` returns ok on the API domain
- [ ] Register + login works on the Vercel URL
- [ ] Chat streams; live search citations appear
- [ ] Upload a PDF → later ask about it in a *different* chat (Doc-RAG)
- [ ] Say something memorable → Settings shows the memory
- [ ] Stripe webhook URL added: `https://<api-domain>/api/v1/billing/webhook`
- [ ] CORS_ORIGINS lists exactly your frontend origin(s)

## 6. Scaling notes (when you grow)

- API is stateless → run 2+ instances behind the host's load balancer.
- Move `BackgroundTasks` work (memory extraction, doc indexing) to ARQ/Celery on Redis.
- Uploads → S3/Cloudinary, fronted by CDN.
- Kubernetes path: see `docs/ARCHITECTURE.md` §16.
