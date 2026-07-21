#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Mood AI — FIRST Fly.io deploy, guided end-to-end (~5 min).
# Everything is pre-filled EXCEPT the secrets you haven't pasted in chat yet.
# Run from the repo root:  bash scripts/fly-first-deploy.sh
#
# Prereq: flyctl installed (curl -L https://fly.io/install.sh | sh) + fly auth login
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REGION="jnb"                  # Johannesburg — closest to 🇬🇭
APP="moodai-api"              # must match fly.toml (edit if name was taken)

echo "▸ Checking flyctl login…"
fly auth whoami >/dev/null 2>&1 || fly auth login

echo "▸ Creating app: $APP (region $REGION)…"
fly apps create "$APP" 2>/dev/null || echo "  (app exists — continuing)"

echo "▸ Creating 3 GB volume (uploads/media until R2)…"
fly volumes create moodai_data --region "$REGION" --size 3 -a "$APP" --yes 2>/dev/null \
  || echo "  (volume exists — continuing)"

# ── Secrets ─────────────────────────────────────────────────────────────────
# FILL THESE (delete the brackets). Anything already known lives in the docs
# (docs/DEPLOY-FLY.md table) — never commit real secrets to the repo.
DATABASE_URL="〈PASTE your Neon/Supabase URI〉"
JWT_SECRET="〈PASTE your JWT secret〉"
GEMINI_KEY="〈PASTE your Gemini key〉"
XAI_KEY="〈PASTE your xAI key — can set later〉"
ADMIN_BOOTSTRAP_PW="〈PASTE your owner password〉"

if [[ "$DATABASE_URL" == *PASTE* || "$JWT_SECRET" == *PASTE* ]]; then
  echo "✋ Fill DATABASE_URL and JWT_SECRET in this script first, then re-run."
  exit 1
fi

echo "▸ Setting secrets…"
fly secrets set -a "$APP" \
  DATABASE_URL="$DATABASE_URL" \
  JWT_SECRET="$JWT_SECRET" \
  GEMINI_API_KEY="$GEMINI_KEY" \
  LLM_FALLBACK_PROVIDER="gemini" \
  LLM_FALLBACK_MODEL="gemini-2.5-flash" \
  XAI_API_KEY="${XAI_KEY/〈PASTE your xAI key — can set later〉/}" \
  ADMIN_BOOTSTRAP_EMAIL="admin@mood.local" \
  ADMIN_BOOTSTRAP_PASSWORD="$ADMIN_BOOTSTRAP_PW" \
  ADMIN_EMAILS="admin@mood.local" \
  CORS_ORIGINS="https://moodai-app.vercel.app" \
  FRONTEND_URL="https://moodai-app.vercel.app" \
  BACKEND_PUBLIC_URL="https://$APP.fly.dev"

echo "▸ Deploying…"
fly deploy -a "$APP"

echo "▸ Verifying…"
sleep 5
curl -sf "https://$APP.fly.dev/healthz" && echo -e "\n\n🎉 API LIVE on Fly.io: https://$APP.fly.dev"
echo "Next: point the web app (moodai-web on Vercel) NEXT_PUBLIC_API_URL to"
echo "      https://$APP.fly.dev/api/v1  — or ask your Arena agent to do it."
