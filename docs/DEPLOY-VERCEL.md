# ▲ Deploy the Mood AI backend on Vercel

The FastAPI backend runs on Vercel as a **Python serverless function**
(no Docker, no server to babysit). One function serves the whole API —
chat, media, designer, plugins, admin — because `vercel.json` rewrites
every request into `api/index.py`.

**Cost:** Vercel Hobby = **$0** (generous for launch) · Vercel Pro = $20/mo
(longer request budget — see limits table below).

> 🧠 Honest pick: Vercel is great for chat/auth/search/flyers. The heavy
> 🎬 video renders can outgrow the 60-second Hobby budget — if you hit that
> wall, the same repo deploys to Railway (Docker) with zero code changes
> ([GO-LIVE-CLICKSHEET.md](GO-LIVE-CLICKSHEET.md) Part A, Option 2).

---

## Step 0 — Database (≈2 min, one time)

Serverless functions can't keep a local database file (the disk resets),
so the backend needs a **hosted Postgres** — Supabase free tier is perfect:

1. 🖱 Follow [docs/SUPABASE.md](SUPABASE.md) **Step 1 only** (create project).
2. 🖱 Copy the **connection string** (Supabase → Connect → "URI"), format:
   ```
   postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```
   You'll paste it as `DATABASE_URL` below. (The app converts it to the async
   driver automatically — paste it exactly as Supabase gives it.)

## Step 1 — Import into Vercel (≈3 min)

1. 🖱 Go to <https://vercel.com> → **Sign up / Login with GitHub** (Joesoft3 account).
2. 🖱 **Add New → Project** → **Import** `joesoft3/moodai`.
3. 🖱 **Root Directory** → **Edit** → select **`backend`** → Continue.
4. 🛑 **Don't deploy yet** — env vars first (next section). If it auto-deploys,
   it will fail until vars are set; that's harmless, just redeploy after.

## Step 2 — Environment variables (≈3 min)

🖱 In the project: **Settings → Environment Variables** → add each
(Production + Preview):

| Name | Value | Why |
|---|---|---|
| `DATABASE_URL` | the Supabase URI from Step 0 | **required** — all your data |
| `JWT_SECRET` | 〈your JWT_SECRET — shown in chat〉 | login tokens |
| `XAI_API_KEY` | 〈from <https://console.x.ai>〉 | the AI brain |
| `CORS_ORIGINS` | `*` for now — tighten after Part B | lets the web app call the API |
| `FRONTEND_URL` | `https://pending` for now | share/invite links |
| `BACKEND_PUBLIC_URL` | your Vercel URL, e.g. `https://moodai-api.vercel.app` | plugin OAuth callbacks |
| `ADMIN_BOOTSTRAP_EMAIL` | 〈your owner email〉 | owner account |
| `ADMIN_BOOTSTRAP_PASSWORD` | 〈your owner password — shown in chat〉 | owner login |
| `ADMIN_EMAILS` | 〈same email〉 | always-admin list |
| `OPENAI_API_KEY` | 〈from <https://platform.openai.com>〉 | voice + memory embeddings (Vercel build is slim — no local ONNX) |
| `GEMINI_API_KEY` | 〈from <https://aistudio.google.com/apikey>〉 | free stand-in brain |
| `LLM_FALLBACK_PROVIDER` | `gemini` | route ALL xAI calls to the stand-in while primary is unfunded/down |
| `LLM_FALLBACK_MODEL` | `gemini-2.5-flash` | the stand-in model (multimodal — covers vision too) |
| `QDRANT_URL` | `https://<cluster>.cloud.qdrant.io:6333` + set nothing else | optional: long-term memory (free cloud tier) |

⛔ Do **not** set `APP_PASSWORD` (that would re-enable the removed signup gate).
⏭ Skip `REDIS_URL` — rate-limiting degrades gracefully without it.

## Step 3 — Deploy & verify

1. 🖱 **Deploy** (or **Deployments → ⋯ → Redeploy** after adding vars).
2. ✅ Open **`https://YOUR-VERCEL-URL/healthz`** → `{"ok":true}` — **LIVE**.
3. ✅ `…/docs` shows the interactive API explorer.
4. 🖱 First request may take a few seconds (cold start) — normal.

Then finish wiring (same as the main click-sheet):

- **Web app**: Netlify `NEXT_PUBLIC_API_URL = https://YOUR-VERCEL-URL/api/v1`
  → then come back and set `CORS_ORIGINS` + `FRONTEND_URL` to the Netlify URL.
- **Phone app**: rebuild pointing at the Vercel URL (or just log in — the app
  reads the same API URL you built with).

## Step 4 — Hands-free auto-deploys (optional, ≈3 min)

Every `git push` to main auto-deploys via GitHub Actions
(`.github/workflows/deploy-vercel.yml` — ships in this repo):

1. 🖱 Vercel → **Settings → Tokens** → create a token.
2. 🖱 Project → **Settings → General** → copy **Project ID**;
   account **Settings → General** → copy **User/Team ID**.
3. 🖱 GitHub repo → **Settings → Secrets and variables → Actions**:
   - Secrets: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`
   - Variable: `VERCEL_CONNECTED` = `true`

✅ Next push shows a green **deploy-vercel** job with the live URL in its summary.

> Both Vercel's own Git integration AND this workflow work — using both
> deploys twice. Prefer one (the workflow is auditable from GitHub).

---

## What's different from the Railway/Docker host

| Thing | Vercel (this doc) | Docker host |
|---|---|---|
| Runtime | serverless function, auto-scales | one always-on container |
| Database | **must be hosted** (Supabase) | bundled Postgres ok |
| Redis / Qdrant | optional (memory via Qdrant Cloud) | bundled next to app |
| Uploads & rendered media | `/tmp`, **ephemeral** — files can vanish between instances | persistent disk |
| Voice **live** WebSocket | ❌ not supported (HTTP STT/TTS ✅ work) | ✅ works |
| Request budget | 60 s (Hobby) / 300 s (Pro) | unlimited |
| Memory embeddings | OpenAI API (fastembed not bundled — function size limit) | local ONNX |

### 🎬 Media notes on Vercel

- ffmpeg comes from the **bundled static build** (`imageio-ffmpeg`) — flyers,
  soundtracks, beat-sync and the editor all work without apt.
- The **DejaVu Bold font is bundled in the repo**, so text rendering is
  identical everywhere.
- **Fast jobs are fine**: flyers/cards (seconds), short beat-cuts. A 2-minute
  4K re-encode will hit the Hobby 60 s wall → fail with a timeout message.
  Fix: Pro plan, or move the backend service to Railway for studio-heavy weeks.
- Files land in `/tmp` and are served from that same instance — grab/download
  them promptly. Durable file storage (Supabase Storage) is on the roadmap.

### Troubleshooting

| Symptom | Cause #1 | Fix |
|---|---|---|
| 500 on every request incl. /healthz | `DATABASE_URL` missing/typo | re-check Step 2, redeploy |
| `/healthz` ok, login fails | `JWT_SECRET` changed after users created | reset it once, users re-login |
| CORS errors in browser console | `CORS_ORIGINS` still `*` typo'd / missing app URL | set exact Netlify URL, redeploy |
| Build fails "bundle too large" | old commit — `fastembed` slipped into requirements.txt | this repo's layout already splits it (`requirements-full.txt` is Docker-only) |
| Video edit times out | Hobby 60 s budget | retry a smaller clip, or Pro/Railway |
