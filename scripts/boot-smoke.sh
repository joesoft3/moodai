#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ChatMood — BOOT smoke: prove a machine actually serves, not just that the
# unit tests pass. CI's pytest gate stayed green on 2026-08-20 while the Fly
# deploy failed, because nothing booted the app the way the container does.
#
# This script boots uvicorn exactly like Dockerfile.fly's CMD (dev fallback:
# AUTO_CREATE_TABLES on SQLite — no Postgres/Redis/Qdrant needed), waits for
# /readyz, then asserts the surfaces a production machine is useless without:
#
#   1. /healthz          → 200 {"status":"ok"}
#   2. /readyz           → 200 ready:true, required postgres check ok
#   3. CORS preflight    → allowed origin echoed; foreign origin denied
#   4. auth gate         → /api/v1/auth/me is 401 without a token
#   5. GET /             → redirects to the web app (FRONTEND_URL)
#
# Usage:   scripts/boot-smoke.sh                 (assumes deps on PATH)
#          PYTHON=/path/to/python scripts/boot-smoke.sh
# Exit:    0 = machine serves · 1 = boot or assertion failed (log on stderr)
# ─────────────────────────────────────────────────────────────────────────────
set -u

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
PORT="${BOOT_SMOKE_PORT:-8765}"
BASE="http://127.0.0.1:$PORT"
FRONTEND="${FRONTEND_URL:-https://moodai-app.vercel.app}"
FAIL=0
LOG="$(mktemp)"
SERVER_PID=""

say()  { printf '%s\n' "$*"; }
ok()   { say "  ✓ $*"; }
bad()  { say "  ✗ $*"; FAIL=1; }
cleanup() { [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null; wait 2>/dev/null; rm -f "$LOG"; }
trap cleanup EXIT

# ── boot (mirrors the container CMD's fallback path) ────────────────────────
cd backend
DATABASE_URL="sqlite+aiosqlite:////tmp/chatmood-boot-smoke.db" \
AUTO_CREATE_TABLES=true REDIS_URL= QDRANT_URL= JWT_SECRET=boot-smoke-secret \
FRONTEND_URL="$FRONTEND" CORS_ORIGINS="$FRONTEND" \
  "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >"$LOG" 2>&1 &
SERVER_PID=$!

for i in $(seq 1 45); do
  sleep 1
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 2 "$BASE/healthz" 2>/dev/null || true)"
  [ "$code" = "200" ] && break
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    say "server process died during boot; last log lines:"; tail -30 "$LOG"; exit 1
  fi
done
if [ "${code:-}" != "200" ]; then
  say "timed out waiting for /healthz; last log lines:"; tail -30 "$LOG"; exit 1
fi
ok "server up (boot $(kill -0 $SERVER_PID 2>/dev/null && echo ok))"

# ── 1. healthz ───────────────────────────────────────────────────────────────
body="$(curl -s -m 5 "$BASE/healthz" || true)"
case "$body" in *'"status":"ok"'*) ok "/healthz ok";; *) bad "/healthz body: $body";; esac

# ── 2. readyz (readiness is what Fly/Render gate deploys on) ────────────────
code="$(curl -s -o "$LOG.rz" -w '%{http_code}' -m 15 "$BASE/readyz" || true)"
body="$(cat "$LOG.rz" 2>/dev/null || true)"
if [ "$code" = "200" ] && \
   printf '%s' "$body" | grep -q '"ready":true' && \
   printf '%s' "$body" | grep -q '"postgres":{"status":"ok"'; then
  ok "/readyz 200 ready:true (postgres ok)"
else
  bad "/readyz → $code $body"
fi

# ── 3. CORS: allowed origin echoed, foreign origin refused ──────────────────
hdrs="$(curl -s -D - -o /dev/null -m 5 -X OPTIONS "$BASE/api/v1/auth/me" \
        -H "Origin: $FRONTEND" -H 'Access-Control-Request-Method: GET' || true)"
case "$hdrs" in *"access-control-allow-origin: $FRONTEND"*) ok "CORS allows $FRONTEND";; *) bad "CORS did not allow $FRONTEND";; esac
hdrs="$(curl -s -D - -o /dev/null -m 5 -X OPTIONS "$BASE/api/v1/auth/me" \
        -H 'Origin: https://definitely-not-chatmood.example' -H 'Access-Control-Request-Method: GET' || true)"
case "$hdrs" in *"access-control-allow-origin"*) bad "CORS allowed a foreign origin";; *) ok "CORS denies foreign origins";; esac

# ── 4. auth gate ─────────────────────────────────────────────────────────────
code="$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$BASE/api/v1/auth/me" || true)"
[ "$code" = "401" ] && ok "/auth/me is 401 unauthenticated" || bad "/auth/me → $code (want 401)"

# ── 5. root redirect ─────────────────────────────────────────────────────────
code="$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -m 5 "$BASE/" || true)"
case "$code" in *"$FRONTEND"*) ok "/ redirects to the web app";; *) bad "/ → $code (want redirect to $FRONTEND)";; esac

[ "$FAIL" = "0" ] && { say "BOOT SMOKE PASSED"; exit 0; }
say "BOOT SMOKE FAILED"; exit 1
