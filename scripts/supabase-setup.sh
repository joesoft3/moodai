#!/usr/bin/env bash
# 🔌 Supabase setup — pushes Mood AI's full schema (16 migrations) into your
# Supabase Postgres and verifies it. Run locally or in Railway's one-off shell.
#
# Usage:
#   ./scripts/supabase-setup.sh "postgresql://postgres.REF:PASSWORD@aws-0-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require"
#
# Get the string from Supabase → Project Settings → Database → Connection string
# → "Transaction" pooler. The script rewrites it to the asyncpg driver and
# injects sslmode if missing — just paste what Supabase gives you.
set -euo pipefail
cd "$(dirname "$0")/../backend"

DSN="${1:-${DATABASE_URL:-}}"
if [ -z "$DSN" ]; then
  echo "❌ Pass your Supabase connection string as the first argument."; exit 1
fi
case "$DSN" in
  postgres://*)     DSN="postgresql+asyncpg://${DSN#postgres://}" ;;
  postgresql://*)   DSN="postgresql+asyncpg://${DSN#postgresql://}" ;;
esac
case "$DSN" in
  postgresql+asyncpg://*"pooler.supabase.com"*":6543"*)
    echo "🪣 Pooler (transaction mode) detected — prepared-statement cache will be disabled by the app engine." ;;
esac
if [[ "$DSN" != *sslmode* ]]; then
  if [[ "$DSN" == *\?* ]]; then DSN="$DSN&sslmode=require"; else DSN="$DSN?sslmode=require"; fi
fi

echo "📦 Installing deps…" && pip install -q -r requirements-full.txt
echo "🚀 Pushing schema (alembic upgrade head)…"
DATABASE_URL="$DSN" alembic upgrade head
echo "🔎 Verifying tables…"
DATABASE_URL="$DSN" python3 - <<'PY'
import os, asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

expect = {"users","conversations","messages","films","designs","brand_kits","devices",
          "pending_actions","teams","usage_events","agent_runs","arena_matches"}

async def main():
    eng = create_async_engine(os.environ["DATABASE_URL"])
    async with eng.connect() as c:
        tables = set((await c.run_sync(lambda s: sa.inspect(s).get_table_names())))
    have = {t for t in expect if t in tables}
    print(f"✅ {len(tables)} tables present; core set {len(have)}/{len(expect)} OK" if expect <= tables
          else f"⚠️  missing some expected tables: {sorted(expect - tables)}")
    await eng.dispose()

asyncio.run(main())
PY
echo "🎉 Done — set this exact string as DATABASE_URL in Railway → Variables → Raw Editor."
echo "   $DSN"
