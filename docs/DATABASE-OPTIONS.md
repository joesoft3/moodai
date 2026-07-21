# 🗄️ Where Mood AI's database can live

Mood AI's backend is **FastAPI + SQLAlchemy on Postgres** (20+ relational
tables, JOINs, transactions) with SQLite for local dev. Any hosted Postgres
works — paste its URI as `DATABASE_URL` and the app normalizes it
(scheme + `sslmode` translation included).

## ✅ Recommended paths (pick one)

### Option A — Neon (fastest with Vercel) ⭐

Serverless Postgres built for serverless functions (auto-suspend, pooled
connections, generous free tier: 0.5 GB + branching). Official Vercel
marketplace integration = **env vars wire themselves**:

1. 🖱 Vercel project → **Storage** tab → **Create Database** → **Neon** (free)
2. Follow the two prompts (region closest to you)
3. Done — `DATABASE_URL` lands in the project automatically; **Redeploy**

Or manual: [neon.tech](https://neon.tech) → New Project → copy the **pooled**
connection string (host ends `-pooler…`) → paste as `DATABASE_URL`.
(The app translates `sslmode=require` automatically — paste exactly as shown.)

### Option B — Supabase

The original path: [supabase.com](https://supabase.com) → New project →
**Connect → URI** → paste as `DATABASE_URL`. Free 500 MB. Full walkthrough in
[docs/SUPABASE.md](SUPABASE.md). Choose this if you also want Supabase Storage
later (files that survive serverless `/tmp`).

### Option C — Railway / Render / any VPS

Bundled-in-Docker Postgres — covered in [BACKEND-HOSTING.md](BACKEND-HOSTING.md).

## ❓ "What about Appwrite?"

Appwrite is a great BaaS, but **it's not a hosted Postgres**. Its database is
MariaDB-backed and reachable **only through Appwrite's own document APIs** —
there is no SQL connection string to give SQLAlchemy (their own docs advise
against direct DB connections). Adopting it would mean replacing Mood AI's
entire data layer with Appwrite's document SDK — a rewrite, not a host change.
Appwrite *could* complement later (e.g. file storage), but it can't run this
app's database.

## After the switch

1. Set `DATABASE_URL` on the host (Vercel → Settings → Environment Variables)
2. Redeploy → `/healthz` → `{"ok":true}`
3. First request auto-creates the schema (AUTO_CREATE_TABLES) — for long-term
   rigor run `alembic upgrade head` from a dev machine after releases.
