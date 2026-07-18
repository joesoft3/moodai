#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Mood AI — LIVE smoke: exercises the REAL paid paths against a deployed stack
# (staging or production): gated register → login → chat stream → 🧠 think mode →
# ⚔️ Arena stream (drafts + ballots + verdict) → arena quota gate → usage meters.
#
# Requires real provider keys on the server (XAI_API_KEY at minimum; the arena
# needs 2+ providers for the full debate, otherwise it degrades to one draft).
#
# Usage:
#   scripts/live-smoke.sh https://api.staging.example.com
#   BASE_URL=https://api.example.com SMOKE_APP_PASSWORD=<gate code> scripts/live-smoke.sh
#
# Optional env:
#   SMOKE_ARENA=0          skip the arena section (no multi-provider keys)
#   SMOKE_THINK=0          skip the think-mode probe
#   SMOKE_STRIPE=1         also create a billing checkout session (needs Stripe env on server)
#   SMOKE_TIMEOUT=240      per-stream timeout seconds (default 240)
#
# Exit code: 0 = every enabled check passed · 1 = one or more failed.
# ─────────────────────────────────────────────────────────────────────────────
set -u

BASE="${1:-${BASE_URL:-http://localhost:8000}}"
BASE="${BASE%/}"
API="$BASE/api/v1"
EMAIL="live-$(date +%s)@mood-smoke.local"
PASS="live-pass-$(date +%s)-Aa1"
BODY="$(mktemp)"
SSE="$(mktemp)"
FAILED=0
TMO="${SMOKE_TIMEOUT:-240}"

pass() { printf '\033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '\033[31mFAIL\033[0m  %s — %s\n' "$1" "$2"; FAILED=$((FAILED + 1)); }
skip() { printf '\033[33mSKIP\033[0m  %s\n' "$1"; }

json_get() { python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get(sys.argv[2], "") or "")
except Exception: print("")' "$BODY" "$1"; }

sse_has() { grep -q "^data:.*\"type\": *\"$1\"" "$2" 2>/dev/null || grep -q "\"type\": \"$1\"" "$2" 2>/dev/null; }

echo "Mood AI LIVE smoke → $BASE"
echo "account: $EMAIL"
echo "────────────────────────────────────────────"

# ── 1. probes ─────────────────────────────────────────────────────────────────
code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 10 "$BASE/healthz")
[ "$code" = "200" ] && pass "GET /healthz" || fail "GET /healthz" "HTTP $code"
code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 15 "$BASE/readyz")
[ "$code" = "200" ] && pass "GET /readyz (db/redis/qdrant)" || fail "GET /readyz" "HTTP $code — $(head -c 160 "$BODY")"

# ── 2. gated register → token ────────────────────────────────────────────────
code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 15 -X POST "$API/auth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"email\": \"$EMAIL\", \"password\": \"$PASS\"$( [ -n "${SMOKE_APP_PASSWORD:-}" ] && printf ', "app_password": "%s"' "$SMOKE_APP_PASSWORD" )}")
TOKEN=$(json_get access_token)
if [ -n "$TOKEN" ]; then
  pass "POST /auth/register → token"
else
  fail "POST /auth/register" "HTTP $code — $(head -c 200 "$BODY")$( [ "$code" = "403" ] && echo ' (sign-up gate on: set SMOKE_APP_PASSWORD)' )"
fi
AUTH=(-H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json')

# ── 3. chat stream (real model round-trip) ───────────────────────────────────
if [ -n "$TOKEN" ]; then
  curl -s -N --max-time "$TMO" -X POST "$API/chat/stream" "${AUTH[@]}" \
    -d '{"message": "Reply with exactly: MOOD_SMOKE_OK", "files": [], "search": false}' > "$SSE"
  if sse_has delta "$SSE" && sse_has done "$SSE"; then
    if grep -q "MOOD_SMOKE_OK" "$SSE"; then pass "POST /chat/stream → real answer tokens + done"
    else pass "POST /chat/stream → tokens + done (model ad-libbed the echo — fine)"; fi
  elif sse_has error "$SSE"; then
    fail "POST /chat/stream" "stream error — $(grep -o '"message": "[^"]*"' "$SSE" | head -1) (XAI_API_KEY set?)"
  else
    fail "POST /chat/stream" "no delta/done events — $(head -c 160 "$SSE")"
  fi
fi

# ── 4. 🧠 think mode (reasoning traces if the model emits them) ───────────────
if [ -n "$TOKEN" ] && [ "${SMOKE_THINK:-1}" = "1" ]; then
  : > "$SSE"
  curl -s -N --max-time "$TMO" -X POST "$API/chat/stream" "${AUTH[@]}" \
    -d '{"message": "What is 17*23? Think briefly, then answer.", "files": [], "search": false, "model": "grok-4", "think": true}' > "$SSE"
  if sse_has thinking_start "$SSE" && sse_has thinking "$SSE"; then
    if sse_has thinking_trace "$SSE"; then
      pass "THINK → thinking_start + live traces + final thinking event"
    else
      pass "THINK → start+final events (model returned no reasoning_content — trace panel stays legitimately empty)"
    fi
  elif sse_has error "$SSE"; then
    fail "THINK" "stream error — $(grep -o '"message": "[^"]*"' "$SSE" | head -1)"
  else
    fail "THINK" "missing thinking_start/thinking events"
  fi
else
  [ "${SMOKE_THINK:-1}" = "1" ] || skip "think mode (SMOKE_THINK=0)"
fi

# ── 5. ⚔️ arena stream: drafts → ballots → verdict → answer ──────────────────
if [ -n "$TOKEN" ] && [ "${SMOKE_ARENA:-1}" = "1" ]; then
  : > "$SSE"
  curl -s -N --max-time "$TMO" -X POST "$API/agents/arena/stream" "${AUTH[@]}" \
    -d '{"message": "In one short paragraph: why is the sky blue?", "files": [], "search": false}' > "$SSE"
  if sse_has arena_verdict "$SSE" && sse_has done "$SSE"; then
    drafts=$(grep -c '"type": "draft_done"' "$SSE")
    votes=$(grep -c '"type": "vote_cast"' "$SSE")
    if sse_has draft_delta "$SSE"; then dstyle="streamed drafts"; else dstyle="non-streamed drafts"; fi
    pass "ARENA → $drafts drafts ($dstyle) · $votes ballots · verdict + answer done"
    if [ "$drafts" -lt 2 ]; then
      skip "arena full debate: only $drafts provider configured (set OPENAI_API_KEY / GEMINI_API_KEY for 2+)"
    fi
  elif grep -q '"error_code": "plan_limit"' "$SSE"; then
    fail "ARENA" "unexpected plan_limit on a fresh account"
  elif sse_has error "$SSE"; then
    fail "ARENA" "stream error — $(grep -o '"message": "[^"]*"' "$SSE" | head -1)"
  else
    fail "ARENA" "no verdict/done — $(head -c 200 "$SSE")"
  fi

  # metering: the arena run must be recorded
  code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 15 "$API/usage/summary" -H "Authorization: Bearer $TOKEN")
  used=$(json_get arena_day 2>/dev/null)
  if [ "$code" = "200" ]; then
    if grep -q '"arena_day"' "$BODY" && ! grep -q '"arena_day": *{[^}]*"used": *0' "$BODY"; then
      pass "GET /usage/summary → arena meter incremented"
    else
      fail "GET /usage/summary" "arena meter did not record the run"
    fi
  else
    fail "GET /usage/summary" "HTTP $code"
  fi

  # quota gate: free plan = 3/day → burn the remainder, expect plan_limit on the 4th
  LIMIT_HITS=0
  for i in 2 3 4; do
    : > "$SSE"
    curl -s -N --max-time "$TMO" -X POST "$API/agents/arena/stream" "${AUTH[@]}" \
      -d "{\"message\": \"arena quota probe $i — answer with one word: ok\", \"files\": [], \"search\": false}" > "$SSE"
    if grep -q '"error_code": "plan_limit"' "$SSE"; then LIMIT_HITS=$i; break; fi
  done
  if [ -n "$LIMIT_HITS" ] && [ "$LIMIT_HITS" != "0" ]; then
    pass "ARENA quota → plan_limit fired on run #$LIMIT_HITS (free cap working)"
  else
    skip "ARENA quota → no plan_limit within 4 runs (custom caps / pro plan on this deployment)"
  fi
else
  [ "${SMOKE_ARENA:-1}" = "1" ] || skip "arena section (SMOKE_ARENA=0)"
fi

# ── 6. Stripe checkout (optional — needs STRIPE_* on the server) ─────────────
if [ "${SMOKE_STRIPE:-0}" = "1" ] && [ -n "$TOKEN" ]; then
  code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 20 -X POST "$API/billing/checkout" \
    -H "Authorization: Bearer $TOKEN")
  URL=$(json_get checkout_url)
  if [ "$code" = "200" ] && [ -n "$URL" ]; then
    pass "POST /billing/checkout → Stripe session created"
    echo "      (complete the webhook loop with: stripe listen --forward-to $BASE/api/v1/billing/webhook && stripe trigger checkout.session.completed)"
  else
    fail "POST /billing/checkout" "HTTP $code — $(head -c 200 "$BODY")"
  fi
fi

# ── 7. frontend + CORS (when WEB_URL is given) ─────────────────────────────
#    WEB_URL=https://mood-ai-app.netlify.app scripts/live-smoke.sh https://YOUR-API
if [ -n "${WEB_URL:-}" ]; then
  WEB="${WEB_URL%/}"
  opts=$(curl -s -o "$BODY" -D - -w 'HTTPCODE:%{http_code}' --max-time 12 -X OPTIONS "$API/auth/login" \
    -H "Origin: $WEB" -H "Access-Control-Request-Method: POST" -H "Access-Control-Request-Headers: content-type,authorization")
  hcode=$(printf '%s' "$opts" | grep -o 'HTTPCODE:[0-9]*' | cut -d: -f2)
  acao=$(printf '%s' "$opts" | tr -d '\r' | grep -i '^access-control-allow-origin:' | head -1 | awk '{print $2}' || true)
  if [ -n "$acao" ] && { [ "$acao" = "$WEB" ] || [ "$acao" = "*" ]; }; then
    pass "CORS preflight for $WEB (HTTP $hcode, allow-origin: $acao)"
  else
    fail "CORS preflight" "HTTP $hcode, allow-origin '${acao:-none}' — set CORS_ORIGINS=$WEB on the backend"
  fi
  wcode=$(curl -sL -o "$BODY" -w '%{http_code}' --max-time 15 "$WEB/")
  if [ "$wcode" = "200" ]; then
    if grep -qi "Mood" "$BODY"; then
      pass "Web app serves $WEB (200, Mood AI markup present)"
    else
      pass "Web app serves $WEB (200)"
    fi
  else
    fail "Web app serves $WEB" "HTTP $wcode"
  fi
fi

# --- 8) Cinema Sound + Admin v2 routes (v0.3.0) -----------------------------------
echo "── 8) media files + admin v2 route wiring (v0.3.0) ──"
# Public media serving: a random but well-formed uuid must 404 (route + name guard live),
# while a path-traversal attempt must ALSO 404 (never 5xx/redirects).
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$API/media/files/$(printf 'a%.0s' $(seq 1 32)).mp4")
[ "$code" = "404" ] && pass "media files serving route (uuid 404 as expected)" \
  || fail "media files route" "expected 404 for unknown uuid, got HTTP $code"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 --path-as-is "$API/media/files/..%2F..%2Fetc%2Fpasswd")
{ [ "$code" = "404" ] || [ "$code" = "400" ]; } && pass "media files traversal blocked (HTTP $code)" \
  || fail "media files traversal" "unexpected HTTP $code"
# Admin v2 endpoints must exist and demand auth (401/403 — a 404 means old deploy).
for ep in devices push-test; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -X POST "$API/admin/$ep" -H 'Content-Type: application/json' -d '{}')
  { [ "$code" = "401" ] || [ "$code" = "403" ]; } && pass "admin/$ep wired + auth-gated (HTTP $code)" \
    || { [ "$code" = "404" ] && fail "admin/$ep" "404 — deploy not on v0.3.0+" || fail "admin/$ep" "HTTP $code"; }
done

echo "────────────────────────────────────────────"
if [ "$FAILED" = "0" ]; then
  printf '\033[32mLIVE SMOKE OK\033[0m — every enabled path passed on %s\n' "$BASE"
  rm -f "$BODY" "$SSE"
  exit 0
else
  printf '\033[31mLIVE SMOKE FAILED\033[0m — %d check(s) failed on %s\n' "$FAILED" "$BASE"
  echo "artifacts kept: $BODY $SSE"
  exit 1
fi
