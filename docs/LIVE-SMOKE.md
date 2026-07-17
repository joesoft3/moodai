# 🧪 Live smoke runbook

`scripts/live-smoke.sh` exercises the **real paid paths** on a deployed stack —
not mocks. Use it after every deploy/env change, or wire it into CI
(`.github/workflows/live-smoke.yml`).

## What it checks

| # | Path | Pass criteria |
|---|---|---|
| 1 | `GET /healthz` · `/readyz` | 200, deps reachable |
| 2 | `POST /auth/register` | fresh account + token (honors the `APP_PASSWORD` sign-up gate) |
| 3 | `POST /chat/stream` | real model tokens + `done` |
| 4 | Think mode (`think: true`) | `thinking_start` → final `thinking` event (traces if the model emits `reasoning_content`) |
| 5 | ⚔️ `POST /agents/arena/stream` | drafts + ballots + `arena_verdict` + answer · notes when <2 providers are keyed |
| 6 | `GET /usage/summary` | arena meter incremented by the debate |
| 7 | Arena quota | free cap (3/day) fires `plan_limit` exactly on the 4th run |
| 8 | `SMOKE_STRIPE=1` | real Stripe checkout session created |

## Run it

```bash
# provision real keys + gate first (interactive or NONINTERACTIVE=1 with env keys)
scripts/provision-env.sh

# against staging/prod (base URL — no /api/v1 suffix)
SMOKE_APP_PASSWORD=<gate code from .env> scripts/live-smoke.sh https://api.staging.example.com

# parts you can't serve yet
SMOKE_ARENA=0 scripts/live-smoke.sh https://api.example.com   # no 2nd provider key yet
```

Exit code `0` = green. On failure it keeps the last response/SSE artifacts and
prints their paths.

## CI (manual trigger on demand)

`Actions → live-smoke → Run workflow` · set these repo/environment **secrets**:

- `SMOKE_BASE_URL` — e.g. `https://api.staging.example.com`
- `SMOKE_APP_PASSWORD` — the `APP_PASSWORD` gate code

Optional input `skip_arena` maps to `SMOKE_ARENA=0`. The run uploads
`live-smoke.log` as an artifact.

## Stripe loop (end-to-end subscription proof)

Webhooks can't be faked without the signing secret — do it with the Stripe CLI:

```bash
stripe listen --forward-to https://api.your-domain.com/api/v1/billing/webhook
stripe trigger checkout.session.completed
SMOKE_STRIPE=1 SMOKE_APP_PASSWORD=<code> scripts/live-smoke.sh https://api.your-domain.com
```

The register/chat arena steps above cover the rest; the meter moves to
`pro` once the webhook lands (check `GET /usage/summary` → plan/quota fields).

## Troubleshooting matrix

| Symptom | Likely cause |
|---|---|
| register 403 | sign-up gate on → pass `SMOKE_APP_PASSWORD` |
| chat stream `error` event | `XAI_API_KEY` missing/invalid on the server |
| arena 1 draft only | only one provider keyed (degraded mode is *by design*) |
| quota probe never limits | custom caps / pro test account — check `PLAN_LIMITS` and the user row |
| think events missing traces | non-reasoning model routed — only grok-4 family emits `reasoning_content` |
