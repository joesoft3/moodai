# 🌍 Custom domain + white-label arena — quickstart

Two different "custom domain" stories — don't mix them:

| Story | Domain | Terminates at |
|---|---|---|
| **Your platform API** | `api.yourdomain.com` | Railway/Render/VPS (A/CNAME to the host) |
| **Your platform app** | `app.yourdomain.com` | Netlify (Site settings → Domain management → points at Netlify) |
| **White-label sales domains** | e.g. `acme-ai.com` | Your **Caddy edge** (VPS path) — Mood AI issues TLS on-demand and serves the customer's branding + arena |

Story 1 & 2 are in [BACKEND-HOSTING.md](BACKEND-HOSTING.md) §Path A step 4 and
[NETLIFY-DEPLOY.md](NETLIFY-DEPLOY.md) §Custom domain. Story 3 below.

---

## Story 3 — sell "your own AI" under a customer's domain

1. **You need the VPS/Caddy path** (white-label TLS on-demand doesn't exist on
   Railway/Render — their edge can't call our `/domains/allowed` hook).
2. DNS at the customer: `acme-ai.com` → CNAME `cname.<your-platform>` (shown in Settings → Domains → Connect).
3. In-app **Settings → Domains → Connect a domain** → add `acme-ai.com`.
4. Create the two records the wizard shows:
   - `TXT _mood-verify.acme-ai.com = <token>` (ownership proof)
   - `CNAME acme-ai.com → <platform target>`
5. Click **Verify** → status flips to `active` → Caddy issues the cert on first visit.
6. Open the manage card on the domain and flip on **⚔️ White-label Arena**:
   - Arena brand (e.g. "Acme Arena") — replaces "Grok-4" in the judge line & panel header
   - Judge model — default `grok-4`, or `grok-4-fast` for cheaper verdicts
   - Daily cap per visitor — on top of plan caps (tightens only, never loosens)
   - Custom panel — up to 6 provider/model entrants (server-skips providers without keys)
7. Optional **team gate**: bind a workspace so the join link only accepts `@acme.com` emails.

**Per-domain analytics** (14-day requests/users + CSV export) are on the same card —
your per-customer billing ammo.

### API recap (all live in the repo)

| Endpoint | Purpose |
|---|---|
| `POST /domains/connect` · `POST /{id}/verify` | BYO domain + DNS proof |
| `PATCH /{id}` | brand, accent, `arena_enabled`, `arena_brand`, `arena_judge`, `arena_daily_cap`, `arena_panel` |
| `GET /domains/by-host?host=` | public white-label lookup incl. arena brand |
| `GET /domains/{id}/analytics[?format=csv]` | per-domain traffic/users |
| `POST /agents/arena/stream` | white-labels itself via `X-Mood-Host` header (the app sends it automatically) |

### Why it needs Caddy

`Caddyfile` in the repo root has an `on_demand_tls { ask …/domains/allowed }` block:
Caddy asks the API "is this host allowed?" before minting a Let's Encrypt cert,
so customers' domains get HTTPS **without you touching anything**.
