# 🔌 Supabase as Mood AI's managed database

Your entire platform (users, chats, films, designs, brand kits, plugins, teams…)
runs on one Postgres. Supabase gives you a managed one — free tier is plenty
to start (500 MB), with daily backups on paid. The schema (16 migrations,
everything ships) pushes in ~30 seconds.

> This is **database-only**: Mood AI keeps its own auth (JWT) and file storage.
> Swapping auth/storage onto Supabase is a bigger re-architecture — listed as a
> separate upgrade track.

## Part A — Create the project (3 min, supabase.com)
1. **supabase.com** → Sign in (GitHub button) → **New project**.
2. Organization: create/accept the default. Name: `mood-ai`.
3. **Database password:** click *Generate* → **copy it somewhere safe immediately**.
4. Region: **EU (Frankfurt)** or **EU (London)** — closest to Accra.
5. Create project → wait ~2 min for provisioning.

## Part B — Grab the connection string (1 min)
1. Project → ⚙️ **Project Settings → Database** → *Connection string*.
2. Pick the **Transaction** pooler tab (port **6543**, `pooler.supabase.com`).
   *Transaction mode is what we want: it multiplexes connections and the app
   auto-disables prepared statements for it (see `db/session.engine_connect_args`).*
3. Copy the URI — it looks like:
   `postgresql://postgres.xxxxxx:[YOUR-PASSWORD]@aws-0-eu-west-1.pooler.supabase.com:6543/postgres`
4. Replace `[YOUR-PASSWORD]` with the password from Part A.

## Part C — Push the schema (2 min, your terminal)
```bash
cd mood-ai
./scripts/supabase-setup.sh "postgresql://postgres.xxxxxx:PASSWORD@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
```
The script: rewrites the DSN to the asyncpg driver → injects `sslmode=require` →
runs `alembic upgrade head` → verifies the core tables → prints the **exact
`postgresql+asyncpg://…` string to use**.

## Part D — Point Railway at Supabase (1 min)
1. Railway → your API service → **Variables** → edit `DATABASE_URL` → paste the
   printed `postgresql+asyncpg://…` string (keep it SECRET — it holds the DB password).
2. Redeploy. On boot, Alembic is idempotent — nothing to run again.
3. Verify: open `https://<your-api>/health` then sign up a test user; rows appear in
   Supabase → **Table Editor** instantly.

## Notes & gotchas
- **Don't** paste the string with `[YOUR-PASSWORD]` brackets left in — the #1 cause of
  "connection refused" tickets.
- Password got `@`/`#`/`%`? URL-encode it (Supabase's *Copy* button on the pooler
  tab does this for you on paid regions; otherwise ask me and I'll encode it).
- If you ever want **direct** connections (port 5432) instead of the pooler: the app
  detects it and keeps prepared-statement caching on for max speed.
- Free tier pauses after ~7 days of inactivity — first request after a pause just
  takes a couple of seconds to wake it.
