# 🪰 Deploy the Mood AI backend on Fly.io

> ### 🚦 LIVE STATUS (2026-07-21) — **RUNNING IN PRODUCTION** ✅
> | Piece | State (all agent-verified live) |
> |---|---|
> | App | ✅ `moodai-api` @ **https://moodai-api.fly.dev** — region **jnb** (Johannesburg 🇬🇭), always-on 1×shared-cpu/1GB |
> | Billing gate | ✅ user's card added → app created headlessly via the sealed deploy token |
> | Database | ✅ dedicated Neon role+DB `moodai` (pooled URI) — **zero sharing with the Vercel API**; 19/19 migrations applied before first boot |
> | `/healthz` | ✅ `200 {"status":"ok"}` · OpenAPI v1.8.0 |
> | Owner bootstrap | ✅ `admin@moodaiapp.com` login → `is_admin: true` |
> | Chat | ✅ live SSE: conversation persisted on the Fly-DB + model reply streamed ("FLY LIVE OK") |
> | Web app wiring | ✅ `NEXT_PUBLIC_API_URL=https://moodai-api.fly.dev` (verified inside the served JS bundles) |
> | CI auto-deploy | ✅ `FLY_CONNECTED=true` — `deploy-fly` workflow deploys every backend push |
> | Volume note | ⚠️ jnb zone was saturated for volume-attached machines at deploy time → shipped **volumeless** (ephemeral uploads until R2); orphaned volume deleted. R2 is the designed durable store |
> | Vercel API | ↩️ kept running as warm secondary (no cost, still healthy) |

The FastAPI backend runs on Fly.io as a **Docker machine** — full ffmpeg,
voice WebSockets, no request-time limit, no cold-start surprises. The repo
ships `fly.toml` (repo root) + `Dockerfile.fly` (root build context); this page is the clicks.

> Fly.io is the **host**, not the database — you still pick a Postgres
> ([docs/DATABASE-OPTIONS.md](DATABASE-OPTIONS.md); Neon free tier is
> recommended) and optionally R2 for durable files ([R2-STORAGE.md](R2-STORAGE.md)).

**Cost honesty:** one always-on `shared-cpu-1x/1GB` machine ≈ **$5–6/month**
(256 MB would halve it but ffmpeg renders want the gig). Bandwidth generous.

---

## Step 0 — flyctl + account (≈2 min)

1. 🖱 Create account: <https://fly.io/app/sign-up> (GitHub sign-in OK)
2. Add a card in **Billing** (required even if you stay tiny — they charge
   actual usage)
3. 💻 Install flyctl — terminal:
   ```bash
   curl -L https://fly.io/install.sh | sh
   fly auth login        # opens browser, click Allow
   ```

## Step 1 — Create the app + volume (≈1 min)

💻 From the repo root:
```bash
fly apps create moodai-api          # name from fly.toml; if taken, pick another + edit fly.toml
fly volumes create moodai_data --region jnb --size 3
```
(Volume = 3 GB persistent disk mounted at `/data` for uploads/media until R2.)

## Step 2 — Secrets (≈2 min)

💻 One command per secret (or paste in dashboard → app → **Secrets**):

| Secret | Value |
|---|---|
| `DATABASE_URL` | your Neon/Supabase URI (app normalizes `sslmode` itself) |
| `JWT_SECRET` | 〈shown in chat〉 |
| `XAI_API_KEY` | 〈console.x.ai — after credits〉 |
| `GEMINI_API_KEY` | 〈AI Studio key〉 |
| `LLM_FALLBACK_PROVIDER` | `gemini` while xAI is unfunded |
| `LLM_FALLBACK_MODEL` | `gemini-2.5-flash` |
| `ADMIN_BOOTSTRAP_EMAIL` / `ADMIN_BOOTSTRAP_PASSWORD` / `ADMIN_EMAILS` | owner account |
| `CORS_ORIGINS` | `https://moodai-app.vercel.app` |
| `FRONTEND_URL` | `https://moodai-app.vercel.app` |
| `BACKEND_PUBLIC_URL` | `https://moodai-api.fly.dev` |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` | optional — durable files ([R2-STORAGE.md](R2-STORAGE.md)) |

```bash
fly secrets set DATABASE_URL="postgresql://…" JWT_SECRET="…" GEMINI_API_KEY="…" \
  LLM_FALLBACK_PROVIDER="gemini" LLM_FALLBACK_MODEL="gemini-2.5-flash" \
  ADMIN_BOOTSTRAP_EMAIL="admin@mood.local" ADMIN_BOOTSTRAP_PASSWORD="…" \
  ADMIN_EMAILS="admin@mood.local" CORS_ORIGINS="https://moodai-app.vercel.app" \
  FRONTEND_URL="https://moodai-app.vercel.app" BACKEND_PUBLIC_URL="https://moodai-api.fly.dev"
```
⛔ Never set `APP_PASSWORD`.

## Step 3 — Deploy & verify

```bash
fly deploy            # builds backend/Dockerfile, runs alembic, boots uvicorn
```
✅ `curl https://moodai-api.fly.dev/healthz` → `{"status":"ok",…}` — **LIVE**.
Web app talks to it already if you keep using the same API URL — else update
`NEXT_PUBLIC_API_URL=https://moodai-api.fly.dev/api/v1` on the web project
(Vercel → moodai-web → env) and redeploy.

## Step 4 — Auto-deploys (optional)

1. 💻 `fly tokens create deploy` → copy token
2. 🖱 GitHub repo → Settings → Secrets and variables → Actions:
   Secret `FLY_API_TOKEN` · Variable `FLY_CONNECTED` = `true`
3. Every push to main now redeploys (`deploy-fly` workflow, ships in repo).

## Fly vs Vercel for this app

| | Fly.io | Vercel (current) |
|---|---|---|
| Runtime | Docker machine, persistent | serverless function |
| Long renders (>60s) | ✅ | Hobby ⛔ / Pro 300s |
| Voice live WebSocket | ✅ | ❌ |
| Uploads/media | `/data` volume (survives) or R2 | `/tmp` ephemeral → R2 recommended |
| Cost | ~$5–6/mo always-on | $0 hobby |
| Cold starts | none | seconds after idle |

Both stay deployable — flip the web app's `NEXT_PUBLIC_API_URL` anytime.
