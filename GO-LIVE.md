# Go Live

The go-live path for ChatMood, and the verification gate a branch must clear
before it is merged.

## How production deploys

ChatMood auto-deploys from `main` via GitHub Actions (see `.github/workflows/`):

| Surface | Host       | Trigger                  | Config                       |
| ------- | ---------- | ------------------------ | ---------------------------- |
| Web     | Vercel     | push to `main`           | `frontend/vercel.json`, `deploy-vercel-web.yml` |
| Web     | Netlify    | push to `main`           | `netlify.toml`, `deploy-netlify.yml` |
| API     | Vercel     | push to `main`           | `deploy-vercel.yml`          |
| API     | Fly.io     | `fly deploy`             | `fly.toml`, `Dockerfile.fly`, `deploy-fly.yml` |
| Backend | Render     | Blueprint `autoDeploy`   | `render.yaml`                |

So the canonical "go live" step is: **merge to `main`**, which triggers the
connected production deploys. Use **https://moodai-app.vercel.app** until the
planned `chatmood.net` domain is registered; then follow
[docs/CHATMOOD-NET-CUTOVER.md](docs/CHATMOOD-NET-CUTOVER.md) before retiring the
Vercel URL.

## The pre-merge gate

Run all of it locally; CI (`test.yml`) enforces the first three.

```bash
# backend — every module must import, every test must pass
find backend/app -name "*.py" -exec python -m py_compile {} +
cd backend && pytest tests -q                 # 694 passed, 3 skipped

# backend — a real machine must boot (this is what the Fly health check gates on;
# unit tests alone were green on 2026-08-20 while the deploy failed)
cd .. && PYTHON=python3 scripts/boot-smoke.sh

# web — types must resolve and the production build must succeed
cd frontend && npx tsc --noEmit && npm run build

# no dead buttons, no 404 links, no phantom API paths
cd backend && DATABASE_URL='sqlite+aiosqlite:///:memory:' python -c \
  "import json; from app.main import app; \
   json.dump(sorted(app.openapi()['paths']), open('../.routes.json','w'))"
node scripts/check-wiring.mjs                 # 68 files · 23 pages · 153 API routes
node scripts/check-docs.mjs                   # 46 markdown files
```

Current status: **all green, 0 problems.**

### What the gate does *not* cover

Worth knowing, because a real 500 slipped through exactly here (see
[docs/QA-AUDIT.md](docs/QA-AUDIT.md)):

- `check-wiring.mjs` proves an API path **exists**, not that it **succeeds**.
- An unauthenticated sweep stops at `401` on any authenticated route, so a
  handler that always throws looks identical to one that works.
- Unit tests that never issue a request miss errors raised while *building* a
  request validator.

For risky surfaces, drive a real authenticated request and assert on the
response body — not just the status code.

## Required environment (all hosts)

- `XAI_API_KEY` — required (Grok models, Live Search, vision)
- `OPENAI_API_KEY` — voice features (realtime STT/TTS)
- `GEMINI_API_KEY` — widens the Arena panel
- `JWT_SECRET`, `REDIS_URL`, `DATABASE_URL`, `QDRANT_URL`
- Stripe: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`
- `CORS_ORIGINS`, `FRONTEND_URL`
- `APP_PASSWORD`, `ADMIN_BOOTSTRAP_PASSWORD` — **change before any public deploy**

See `.env.example` and [docs/DEPLOY-WALKTHROUGH.md](docs/DEPLOY-WALKTHROUGH.md)
for the full setup.

## After deploy

Run `scripts/live-smoke.sh` (or the `live-smoke.yml` workflow) against the live
URL to verify chat, search, memory and `/readyz`.

`/readyz` is the **readiness** probe and is what the Fly/Render health checks
gate on. `/healthz` is liveness only — it returns 200 whenever the process is
running, even if the database is unreachable, so never gate a deploy on it.

Only the dependencies listed in `READINESS_REQUIRED` (default: `postgres`) can
fail the probe:

| Body | HTTP | Meaning |
|---|---|---|
| `{"status":"ok","ready":true}` | 200 | Everything reachable. |
| `{"status":"degraded","ready":true}` | 200 | An **optional** dep (Redis/Qdrant) is down. Still serving — the rate limiter fails open and memory/RAG degrade to "no recall". **Fly runs this way normally**: it provisions no Redis. |
| `{"status":"unready"}` | 503 | A **required** dep is unreachable. Pull the instance. |

Each entry in `checks` carries `status`, latency `ms`, and `required`, so read
the body before assuming a deploy is broken. Set
`READINESS_REQUIRED=postgres,redis,qdrant` on stacks that really do provision
all three (docker-compose does).

## Shipping a change

1. Implement it on your working branch, commit, push.
2. Open / update the PR against `main`.
3. Merge to `main` → production auto-deploys.
4. Run the live smoke test.
