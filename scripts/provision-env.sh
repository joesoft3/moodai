#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Mood AI — interactive .env provisioner.
#
# Copies .env.example → .env, generates strong random secrets, and fills in API
# keys from your environment or interactive prompts. Idempotent: never
# overwrites an existing .env unless FORCE=1.
#
# Non-interactive usage (CI):
#   XAI_API_KEY=... OPENAI_API_KEY=... GEMINI_API_KEY=... STRIPE_SECRET_KEY=... \
#     NONINTERACTIVE=1 scripts/provision-env.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u
cd "$(dirname "$0")/.."

if [ -f .env ] && [ "${FORCE:-0}" != "1" ]; then
  echo "📦 .env already exists — leaving it untouched (FORCE=1 to regenerate)."
  exit 0
fi

cp .env.example .env
echo "📄 .env.example → .env"

rand() { python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }
randpw() { python3 -c 'import secrets; print(secrets.token_urlsafe(9))'; }

setkv() { # setkv KEY VALUE — replace or append a key in .env
  if grep -q "^$1=" .env; then
    python3 - "$1" "$2" << 'PY'
import re, sys
k, v = sys.argv[1], sys.argv[2]
p = ".env"
s = open(p).read()
s = re.sub(rf"^{re.escape(k)}=.*$", f"{k}={v}", s, flags=re.M)
open(p, "w").write(s)
PY
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

ask() { # ask VAR "prompt" [secret]
  local var="$1" prompt="$2"
  eval "cur=\"\${$var:-}\""
  if [ -n "$cur" ]; then echo "🔑 $var ← environment"; return 0; fi
  if [ "${NONINTERACTIVE:-0}" = "1" ]; then echo "·  $var (blank)"; return 0; fi
  printf '🔑 %s (Enter to skip): ' "$prompt" > /dev/tty
  read -r cur < /dev/tty || true
  eval "$var=\"$cur\""
}

# --- generated secrets (always fresh) ────────────────────────────────────────
setkv JWT_SECRET "$(rand)"
setkv ADMIN_BOOTSTRAP_PASSWORD "Mood-$(randpw)"
setkv APP_PASSWORD "MOOD-$(randpw)"
echo "🎲 JWT_SECRET · ADMIN_BOOTSTRAP_PASSWORD · APP_PASSWORD generated"

# --- provider keys ───────────────────────────────────────────────────────────
ask XAI_API_KEY "xAI API key (console.x.ai) — REQUIRED for chat"
ask OPENAI_API_KEY "OpenAI API key (voice + 2nd arena contestant)"
ask GEMINI_API_KEY "Gemini API key (3rd arena contestant)"
ask TAVILY_API_KEY "Tavily key (alternative web search)"
ask STRIPE_SECRET_KEY "Stripe secret key (subscriptions)"
ask STRIPE_WEBHOOK_SECRET "Stripe webhook secret"
ask STRIPE_PRICE_ID "Stripe Pro price id"

for k in XAI_API_KEY OPENAI_API_KEY GEMINI_API_KEY TAVILY_API_KEY STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET STRIPE_PRICE_ID; do
  eval "v=\"\${$k:-}\""
  [ -n "$v" ] && setkv "$k" "$v"
done

echo ""
echo "✅ .env provisioned."
echo "   Owner login : $(grep -m1 '^ADMIN_BOOTSTRAP_EMAIL=' .env | cut -d= -f2) / $(grep -m1 '^ADMIN_BOOTSTRAP_PASSWORD=' .env | cut -d= -f2)"
echo "   Sign-up code: $(grep -m1 '^APP_PASSWORD=' .env | cut -d= -f2)"
[ -z "${XAI_API_KEY:-}" ] && echo "   ⚠️  XAI_API_KEY is blank — chat will 503 until you add it."
