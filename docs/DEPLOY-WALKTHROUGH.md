# ☁️ Mood AI — production deploy walkthrough

From zero to a live, custom-domain, Pro-gated deployment. ~30–45 minutes.
Your repo ships a working `docker-compose.yml`, a Caddy **edge** profile with
on-demand HTTPS, one-command DB migrations, and a smoke test.

---

## 0. What you need

| Requirement | Where to get it |
|---|---|
| A server (≥2 GB RAM) | Railway / Render / Fly / any VPS with Docker |
| **xAI API key** (required) | https://console.x.ai |
| OpenAI key (voice + ⚔️ arena panel) | https://platform.openai.com/api-keys |
| Gemini key (wider ⚔️ arena panel) | https://aistudio.google.com/apikey |
| Stripe account (Pro subscriptions) | https://dashboard.stripe.com/apikeys |
| A domain you own (optional) | any registrar — or buy one **inside the app** later |

> Minimal viable deploy = server + XAI key. Everything else adds features.

---

## 1. Prepare `.env`

```bash
cp .env.example .env
```

The starter `.env` we generated for you already contains a real JWT secret,
the **owner bootstrap login** and a **sign-up access code**. Before going public,
**rotate all three** directly in `.env`:

```ini
JWT_SECRET=<new 64-char random>
ADMIN_BOOTSTRAP_EMAIL=you@yourdomain.com     # ← YOUR email, not admin@mood.local
ADMIN_BOOTSTRAP_PASSWORD=<new strong password>
APP_PASSWORD=<new access code or leave empty to disable>

XAI_API_KEY=xai-...
OPENAI_API_KEY=sk-...        # voice + gpt-4o in the arena
GEMINI_API_KEY=...           # gemini in the arena

STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...    # recurring price for Pro

BASE_DOMAIN=app.yourdomain.com   # your platform's own domain
ACME_EMAIL=ops@yourdomain.com    # Let's Encrypt contact
```

In production also set `AUTO_CREATE_TABLES=false` and run migrations yourself (step 3).

## 2. Boot the stack

```bash
docker compose up -d --build
docker compose logs -f backend   # wait for "bootstrap: owner account created"
```

Services: postgres · redis · qdrant · backend (:8000) · frontend (:3000).

## 3. Verify (3 minutes)

```bash
docker compose exec backend alembic upgrade head      # only when AUTO_CREATE_TABLES=false
export SMOKE_APP_PASSWORD='<your APP_PASSWORD>'       # skip if gate disabled
./scripts/smoke.sh https://api.yourdomain.com
```

Expect: `✓ all smoke checks passed`.

Then in the browser: sign in as the bootstrap owner → sidebar gets a **🛡 Owner** link.
From the owner panel you can flip sign-ups to invite-only and rotate the access code
(panel values always win over `.env`).

## 4. Go HTTPS on your own domain (edge proxy)

```bash
docker compose --profile edge up -d
```

Point DNS **A record** of `app.yourdomain.com` → your server IP. Caddy gets a real
certificate automatically (email from `ACME_EMAIL`).

## 5. Stripe → Pro plan (for the ⚔️ arena + perks)

1. Create a **recurring price** in Stripe → copy its id into `STRIPE_PRICE_ID`.
2. Add webhook endpoint `https://api.yourdomain.com/api/v1/billing/webhook`
   (events: `checkout.session.completed`, `customer.subscription.deleted`) →
   copy the signing secret into `STRIPE_WEBHOOK_SECRET`; restart backend.
3. A user subscribes from **Settings → Subscription**; the webhook sets `plan=pro`.

Pro immediately unlocks: ⚔️ arena 100/day *(free 3/day teaser → `plan_limit` event →
upgrade banner in chat)*, 5M tokens/mo, 50 MB uploads *(vs 25)*, 365-day memory
retention *(vs 30)*, 4× rate-limit throughput, 60 videos/day.

## 6. Checklist before announcing

- [ ] Owner login rotated; you can reach `/admin` and see stats
- [ ] Access code rotated (or gate intentionally open — owner panel toggle)
- [ ] `./scripts/smoke.sh` green against the public URL
- [ ] Stripe webhook test event delivered (200)
- [ ] ⚔️ Arena runs with all configured providers (chat → ⚔️ Arena → ask something)
- [ ] Rematch works: after a verdict, hit the ⚔️ button on that answer

## Troubleshooting

| Symptom | Fix |
|---|---|
| Register says "requires an access code" | Gate is on — give the code or remove it in the owner panel |
| Arena answers from Grok only | Set `OPENAI_API_KEY` / `GEMINI_API_KEY`; the panel skips keyless providers |
| `plan_limit` event right at 1st arena | `arena_day` cap: 3/day free — upgrade to Pro or edit `PLAN_LIMITS` |
| MCP/voice features 503 | Voice needs `OPENAI_API_KEY` (Whisper + TTS) |
| Cert never issues | `BASE_DOMAIN` must match the public hostname; port 80/443 open |
