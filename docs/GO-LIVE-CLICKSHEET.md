# 🚀 Mood AI — Go-Live Click-Sheet (Railway → Netlify → Phone)

The whole app goes live in **~15 minutes of clicking**. Do the parts **in order** —
each step has a 🖱 = a click in your browser, and a ✅ = how you know it worked.

> 🔐 Never paste passwords or tokens into GitHub issues/comments — set them only in
> Railway/Netlify dashboards as shown. Never set `APP_PASSWORD` anywhere (that
> would turn the removed site gate back on).

---

## Part A — Backend on Railway 🚄 (≈8 min)

**A1.** 🖱 Go to <https://railway.app> → **Login with GitHub** (use the **Joesoft3** GitHub account).

**A2.** 🖱 **New Project** → **Deploy from GitHub repo** → pick **`joesoft3/moodai`**.
Railway detects the root `railway.toml` + `backend/Dockerfile` and starts a build.
It will fail/crash-loop for now — expected — env vars come next.

**A3.** 🖱 Add the three data services (each takes ~30 s to provision):
- canvas **＋ New → Database → PostgreSQL**
- canvas **＋ New → Database → Redis**
- canvas **＋ New → Template →** search **`Qdrant`** → **Deploy**

✅ You should see **4 services**: `moodai`, `Postgres`, `Redis`, `Qdrant` — all green.

**A4.** 🖱 Click the **`moodai`** service → **Variables** tab → add exactly these
(*Variable Editor / "Add variable" for each*):

| Name | Value (paste) |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` |
| `QDRANT_URL` | `http://${{Qdrant.RAILWAY_PRIVATE_DOMAIN}}:6333` |
| `JWT_SECRET` | *〈use the JWT_SECRET from your local `.env` — shown in chat〉* |
| `XAI_API_KEY` | *〈your key from <https://console.x.ai>〉* |
| `ADMIN_BOOTSTRAP_EMAIL` | `admin@mood.local` |
| `ADMIN_BOOTSTRAP_PASSWORD` | *〈use the one from your local `.env` — shown in chat〉* |
| `CORS_ORIGINS` | `*` *(we'll tighten after Part B)* |
| `FRONTEND_URL` | `https://pending` *(we'll replace after Part B)* |

⛔ Do **not** add `APP_PASSWORD`.

**A5.** 🖱 Still in the `moodai` service → **Settings → Networking → Public Networking →
Generate Domain**. Railway gives you a URL like
`https://moodai-production-ab12.up.railway.app`. **Copy it.**

**A6.** 🖱 **Deployments** tab → click the newest deploy → watch logs. Wait for:
`alembic upgrade head … 0010_domain_arena` then `Uvicorn running on 0.0.0.0:…`.

✅ Open **`https://YOUR-RAILWAY-URL/healthz`** → `{"ok":true}` — backend is **LIVE**.
(Also `…/docs` shows the API explorer.)

🛠 If the deploy is red: *Variables tab has a typo* is cause #1 — especially `QDRANT_URL`
(the `http://` prefix and `:6333` both matter). Re-check, Railway auto-redeploys on edit.

---

## Part B — Frontend on Netlify 🌐 (≈5 min, the easy official way)

**B1.** 🖱 <https://app.netlify.com> → **Sign up with GitHub** (Joesoft3) → **Add new project →
Import an existing project** → **GitHub** → pick **`joesoft3/moodai`**.

**B2.** 🖱 Build settings **auto-fill from `netlify.toml`** (base `frontend`, build
`npm run build`, publish `.next`, Next.js runtime) — **don't change anything**, just confirm.

**B3.** 🖱 Before deploying: **Environment variables → Add a variable**:

| Key | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://YOUR-RAILWAY-URL/api/v1` *(Part A5 URL + `/api/v1`)* |

**B4.** 🖱 **Deploy** (~2 min) → Netlify gives you
`https://<random-name>.netlify.app`.
🖱 Optional: **Site configuration → Change site name** → e.g. `mood-ai-app` →
`https://mood-ai-app.netlify.app`.

✅ Open the site → you see the **Mood AI login screen** — frontend is **LIVE**.

**B5.** 🖱 Lock the backend to the site (so other origins can't call it):
back in **Railway → moodai → Variables** — set:

| Name | New value |
|---|---|
| `CORS_ORIGINS` | `https://mood-ai-app.netlify.app`*(your real site name)* |
| `FRONTEND_URL` | `https://mood-ai-app.netlify.app` |

Railway redeploys automatically (~1 min).

> **Optional (CI-managed deploys instead):** prefer GitHub Actions to control deploys?
> Repo → *Settings → Secrets and variables → Actions* → add `NETLIFY_AUTH_TOKEN`
> (Netlify: *User settings → Applications → New access token*) and `NETLIFY_SITE_ID`
> (Netlify: *Site settings → General → Site details → API ID*), plus a secret
> `NEXT_PUBLIC_API_URL`. After that the `deploy-netlify` workflow turns green on every
> push to `main`. **Pick ONE deploy driver** — Netlify-Git (B1) or the workflow — not both.

---

## Part C — Phone app 📱 (≈1 min + a build)

**C1.** 🖱 GitHub repo → **Actions → mobile-apk → Run workflow** → paste
`https://YOUR-RAILWAY-URL/api/v1` into **Default API base** → **Run**.
~10 min later the run is green.

**C2.** 🖱 Open that run → **Artifacts** → **`mood-ai-android-apks`** → unzip → install
**`app-arm64-v8a-release.apk`** (*almost every modern Android*; the release page has a
“Which APK?” table). These build runs produce 4 slim, R8-shrunk APKs — compare against
v0.1.8's monolithic 54 MB one.

> The APKs attached to the **v0.1.9 Release** itself default to the dev/localhost API
> (tag builds have no URL input) — use them for emulator testing only. Your real phone
> build comes from the C1 run above.

---

## Part D — 60-second acceptance test ✅

1. 🖱 Open your Netlify URL → **Create account** (no invite code — signup is open).
2. 💬 Send a chat → answer streams back (that means DB + xAI + Redis all work).
3. ⚔️ Tap **Arena** → send “Should remote-first teams win?” → watch 3 drafts → ballots → verdict.
4. 🧠 Enable **Think** on a mini model → reasoning trace collapsible above the reply.
5. 🛡 Log in as **admin@mood.local** (bootstrap password) → **Owner** tab → analytics tiles.
6. 🧩 Open **Plugins** → store cards render; try to connect — errors politely until OAuth keys exist (fix: [PLUGIN-OAUTH](PLUGIN-OAUTH.md), ~10 min).

**One command to verify EVERYTHING** (creates a real user, chats, arena, think, quotas, CORS, web):

```bash
WEB_URL=https://mood-ai-app.netlify.app scripts/live-smoke.sh https://YOUR-RAILWAY-URL
```

Every line green = done. 🎉 Send me any failing line/URL and I'll diagnose from the logs.

**Then, whenever you want:** 🔑 [real Gmail/Calendar/GitHub connecting](PLUGIN-OAUTH.md) ·
🌍 [your own domain](CUSTOM-DOMAIN-SETUP.md) · 🏪 [Play Store submission run](PLAY-STORE-SUBMISSION.md)
(signed AAB ships on every `v*` tag — set the `MOOD_UPLOAD_*` secrets, then follow the runbook).

---

## Part E — Optional hands-free upgrades (paste-ready)

| Upgrade | Where | What |
|---|---|---|
| 🎙 **Video sound & voice** | Railway → Variables | `OPENAI_API_KEY=<key>` + `BACKEND_PUBLIC_URL=https://<your-railway-domain>` — then Video Studio's 🔊 **Voice + ambience** just works. Guide: [VIDEO-SOUND](VIDEO-SOUND.md) |
| 🧪 **Weekly live E2E** | GitHub → Settings → Secrets → Actions | add `LIVE_WEB_URL=https://<netlify-site>` and `LIVE_API_URL=https://<railway-domain>` — every Monday CI signs up a bot on YOUR live app, runs chat/pages/routes, and screenshots failures. |
| 🔑 **Play upload key** | GitHub → Secrets (4 values) | key is ALREADY generated in the repo workspace → [UPLOAD-KEY.md](UPLOAD-KEY.md) — 5 minutes, then every `v*` tag ships a Play-ready signed AAB. |
| 🔔 **Push notifications** | Firebase + Railway + 1 GitHub secret | 5 console clicks: [PUSH-NOTIFICATIONS](PUSH-NOTIFICATIONS.md) — then Owner panel → **Push & devices → Send test push** proves it end-to-end. |

*References: [RAILWAY-CHEATSHEET](RAILWAY-CHEATSHEET.md) (full env-var catalog) ·
[NETLIFY-DEPLOY](NETLIFY-DEPLOY.md) (CI secrets path) · [LIVE-SMOKE](LIVE-SMOKE.md) (scripted checks)*
