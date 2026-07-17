#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Mood AI — end-to-end smoke test (pure bash + curl + python3 for JSON parsing)
#
# Usage:
#   scripts/smoke.sh                       # against http://localhost:8000
#   scripts/smoke.sh https://api.example.com
#   BASE_URL=https://staging.example.com scripts/smoke.sh
#
# Exercises the critical paths: health/readiness probes, account creation,
# authenticated /me, a real streaming chat round-trip, domain providers and
# usage metering. Exits non-zero if any check fails.
# ─────────────────────────────────────────────────────────────────────────────
set -u

BASE="${1:-${BASE_URL:-http://localhost:8000}}"
BASE="${BASE%/}"
API="$BASE/api/v1"
EMAIL="smoke-$(date +%s)@mood-smoke.local"
PASS="smoke-pass-$(date +%s)-Aa1"
BODY="$(mktemp)"
FAILED=0

pass() { printf '\033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '\033[31mFAIL\033[0m  %s — %s\n' "$1" "$2"; FAILED=$((FAILED + 1)); }

json_get() { python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get(sys.argv[2], "") or "")
except Exception: print("")' "$BODY" "$1"; }

echo "Mood AI smoke test → $BASE"
echo "────────────────────────────────────────────"

# ── 1. liveness ──────────────────────────────────────────────────────────────
code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 10 "$BASE/healthz")
if [ "$code" = "200" ]; then pass "GET /healthz → 200"; else fail "GET /healthz" "HTTP $code"; fi

# ── 2. readiness (DB/Redis/Qdrant) ───────────────────────────────────────────
code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 15 "$BASE/readyz")
if [ "$code" = "200" ]; then pass "GET /readyz → 200 (deps reachable)"; else fail "GET /readyz" "HTTP $code — $(head -c 200 "$BODY")"; fi

# ── 3. register a fresh account ──────────────────────────────────────────────
code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 15 -X POST "$API/auth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"email\": \"$EMAIL\", \"password\": \"$PASS\"$( [ -n "${SMOKE_APP_PASSWORD:-}" ] && printf ', \"app_password\": \"%s\"' "$SMOKE_APP_PASSWORD" )}")
TOKEN=$(json_get access_token)
if [ "$code" = "200" ] && [ -n "$TOKEN" ]; then
  pass "POST /auth/register → account + token"
elif [ "$code" = "403" ]; then
  fail "POST /auth/register" "sign-up gated (invite-only or app access code enabled) — rerun with SMOKE_APP_PASSWORD=<code> or disable the owner gate"
else
  fail "POST /auth/register" "HTTP $code — $(head -c 200 "$BODY")"
fi

# ── 4. authenticated /me ─────────────────────────────────────────────────────
if [ -n "$TOKEN" ]; then
  code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 10 "$API/auth/me" -H "Authorization: Bearer $TOKEN")
  ME=$(json_get email)
  if [ "$code" = "200" ] && [ "$ME" = "$EMAIL" ]; then pass "GET /auth/me → $ME"; else fail "GET /auth/me" "HTTP $code"; fi
fi

# ── 5. streaming chat round-trip ─────────────────────────────────────────────
if [ -n "$TOKEN" ]; then
  STREAM=$(curl -sN --max-time 90 -X POST "$API/chat/stream" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"message":"Reply with the single word: pong"}' | head -c 4096)
  case "$STREAM" in
    *data:*)
      pass "POST /chat/stream → SSE bytes flowing"
      case "$STREAM" in
        *[Dd]elta*|*pong*|*Pong*) pass "chat stream contains model output" ;;
        *error*|*not\ configured*) echo "WARN  chat stream returned an error frame (check LLM API keys)" ;;
        *) echo "WARN  chat stream had no recognizable delta (provider key set?)" ;;
      esac
      ;;
    *) fail "POST /chat/stream" "no SSE data — got: $(printf '%s' "$STREAM" | head -c 160)" ;;
  esac
fi

# ── 6. domain providers (registrar config surface) ───────────────────────────
if [ -n "$TOKEN" ]; then
  code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 10 "$API/domains/providers" -H "Authorization: Bearer $TOKEN")
  if [ "$code" = "200" ]; then pass "GET /domains/providers → 200"; else fail "GET /domains/providers" "HTTP $code"; fi
fi

# ── 7. usage metering summary ────────────────────────────────────────────────
if [ -n "$TOKEN" ]; then
  code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 10 "$API/usage/summary" -H "Authorization: Bearer $TOKEN")
  if [ "$code" = "200" ]; then
    pass "GET /usage/summary → 200 ($(json_get plan) plan)"
  else
    fail "GET /usage/summary" "HTTP $code"
  fi
fi

echo "────────────────────────────────────────────"
if [ "$FAILED" -eq 0 ]; then
  printf '\033[32m✓ all smoke checks passed\033[0m\n'
  rm -f "$BODY"
  exit 0
else
  printf '\033[31m✗ %d check(s) failed\033[0m\n' "$FAILED"
  rm -f "$BODY"
  exit 1
fi
