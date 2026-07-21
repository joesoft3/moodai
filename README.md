# Mood AI — a Grok-class assistant built on xAI + FastAPI + Next.js

Mood AI is a full-stack AI super-app scaffold that delivers Grok-style capabilities by
**orchestrating existing frontier models and tools** instead of training anything from scratch.

- 💬 Streaming AI chat (Grok models via the xAI API)
- 🌐 Real-time web/X/news search grounding (xAI Live Search)
- 🧠 Long-term memory (semantic, per-user, stored in Qdrant) **+ cross-chat recall — Mood remembers what your previous conversations were about**
- 📄 PDF / Word / Excel / CSV / text analysis
- 🖼️ Image understanding (Grok vision) + image generation
- 🎤 Voice: **realtime WebSocket sessions** (live transcript, streaming replies, sentence-chunked TTS, barge-in) + REST STT/TTS
- 🤖 Multi-agent mode — researcher/coder work **concurrently**, writer synthesizes, 🧐 critic fact-checks
- ⚔️ **Arena (Pro)** — multi-model debate: drafts **stream token-by-token** from Grok / GPT / Gemini in parallel, blind ballots on anonymized drafts, **Grok-4 verdict + per-draft score cards** (accuracy/clarity 1–10), 🔁 **Rematch** (providers try to beat the previous winner), 🌐 **white-label arenas** per custom domain (own brand, judge model, custom panel, per-domain daily cap) · free plan 3/day teaser → Pro 100/day
- 🧠 **Think mode** — live reasoning traces from Grok-4 streamed into a collapsible panel, 2-sentence digest of the reasoning, elapsed time + tokens; persisted and restored with the message
- 🧰 **Pro perks enforced server-side** — 50 MB uploads (vs 25), 365-day memory retention (vs 30), 4× rate-limit throughput, plan-aware errors that always point at the upgrade
- 🔭 DeepSearch — multi-round agentic web research with citations
- 🧩 Plugins — Gmail, Google Calendar & GitHub via OAuth (encrypted tokens, function calling)
- 🔀 Multi-provider router — Gemini/OpenAI(/Claude via gateway) per task, env-driven, xAI default
- 👥 Team workspaces — shared conversations with authors + per-seat usage (owners)
- 🌐 Custom domains — connect your own domain (DNS-verified white-label) or **buy domains in real time** (registrar API + Stripe, auto-connected, auto-HTTPS)
- 🎨 Per-domain white-label theme — brand name, accent color, logo (+ favicon) applied live on your domain, including public surfaces (login, invite join, shared links)
- 🔁 Renewal billing & expiry tracking — expiry watchdog + registrar-synced auto-renew + one-click **paid renewal** (Stripe → registrar renewal after payment) + email reminders
- 📊 Domain analytics — real-time requests & unique users per custom domain (Redis counters, zero migrations)
- ✉️ Team invites & domain gating — shareable join links (emailed via the owner's Gmail) ; bind a domain and only `@company.com` emails can join
- ✋ Human-in-the-loop — write actions (send email, create event/issue) wait for in-chat approval
- 🎬 **Professional video studio with 🎙 Cinema Sound + Storyboard films** — duration/aspect/quality/style presets, negative prompts, ✨ prompt enhancer, templates (xAI video, provider seam), **AI voiceovers (10 voices, ▶ preview, tempo control) + 4 procedural music moods, loudness-polished ffmpeg mixing; async storyboard jobs split one idea into 2–4 directed scenes rendered 2-wide, stitched + voiced into a continuous film with optional burned-in subtitles, tracked in the 🎞 **Films** gallery (poll, resume, re-mix, share) — see [docs/VIDEO-SOUND.md](docs/VIDEO-SOUND.md)** · 🐍 Python sandbox tool
- 📱 Flutter mobile client (login + streaming chat) in `mobile/`
- 🔗 Share conversations via revocable public links · 📊 usage dashboard (tokens vs. plan tiers)
- 🔒 JWT auth, Redis rate limiting, Stripe subscription hooks
- 🛡 **Owner panel** — platform stats, user administration (plan/reset/admin/delete), sign-up gate (invite-only toggle + app access code, hashed) — plus an **env-bootstrapped owner account**
- 🗂 Files manager + 🎵🎞 audio/video analysis — transcripts & answers from songs/lectures/clips (ffmpeg frame sampling + Grok vision), CSV exports (usage & domain analytics)
- 🔁 **One-env LLM failover** — flip `LLM_FALLBACK_PROVIDER`/`LLM_FALLBACK_MODEL` and chat, picker tiers, vision & memory ride a stand-in provider (Gemini/OpenAI-compat) while the primary is down or unfunded; unset and Grok resumes
- 🐳 One-command Docker setup; Kubernetes-ready architecture

> See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the full technical blueprint,
> model routing strategy, multi-agent design, plugin framework, and scaling roadmap.
> Ready to ship? **[docs/DEPLOY-WALKTHROUGH.md](docs/DEPLOY-WALKTHROUGH.md)** — zero to live,
> web app on **Netlify** ([docs/NETLIFY-DEPLOY.md](docs/NETLIFY-DEPLOY.md)) · backend on
> **Vercel** ([docs/DEPLOY-VERCEL.md](docs/DEPLOY-VERCEL.md)) or **Railway/Render/VPS**
> ([docs/BACKEND-HOSTING.md](docs/BACKEND-HOSTING.md)) · verify with the
> **live smoke** ([docs/LIVE-SMOKE.md](docs/LIVE-SMOKE.md)).
>
> 🔁 **Auto-deploys on push**: `deploy-netlify` (web) + `deploy-vercel` (API) workflows →
> production on every `main` push (each skips cleanly until connected) ·
> `mobile-apk` workflow → tagged releases get an installable Android APK attached.

[![Deploy to Netlify](https://www.netlify.com/img/deploy/button.svg)](https://app.netlify.com/start/deploy?repository=https://github.com/joesoft3/moodai)
> custom domain + HTTPS + Stripe Pro in ~45 min.

---

## Quickstart (Docker)

```bash
cp .env.example .env
# Edit .env — the only required key is XAI_API_KEY (https://console.x.ai)
# Add OPENAI_API_KEY to enable voice features + OPENAI/GEMINI keys to widen the ⚔️ arena panel.
# .env already ships a bootstrapped owner login (ADMIN_BOOTSTRAP_*) and a sign-up
# access code (APP_PASSWORD) — change both before deploying anywhere public!

docker compose up --build
```

Then:
- Web app → http://localhost:3000
- API docs (Swagger) → http://localhost:8000/docs
- Qdrant dashboard → http://localhost:6333/dashboard

First boot downloads a ~90 MB embedding model (fastembed/ONNX) for memory — once only.

## Local dev (no Docker for app code)

```bash
docker compose up -d db redis qdrant        # infrastructure only

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload               # http://localhost:8000

# Frontend
cd frontend
npm install
npm run dev                                 # http://localhost:3000
```

## Repo map

```
mood-ai/
├── docker-compose.yml        # full stack: app + postgres + redis + qdrant
├── .env.example              # every configurable knob, documented
├── docs/ARCHITECTURE.md      # the blueprint (read this)
├── backend/                  # FastAPI service
│   └── app/
│       ├── main.py           # app factory, routers, lifespan
│       ├── config.py         # pydantic-settings, env-driven
│       ├── core/security.py  # JWT + password hashing
│       ├── db/               # SQLAlchemy 2.0 async models + session
│       ├── api/routes/       # auth, chat, conversations, files, voice, memory, billing
│       └── services/         # llm (xAI), memory (Qdrant), search, file_extract, voice
└── frontend/                 # Next.js 14 (App Router) + Tailwind
    └── app/ + components/    # responsive app shell (phone/tablet/desktop),
                              # chat, voice studio, image lab, settings, PWA
```

## API surface (v1)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/auth/register`, `/login` | JWT auth |
| GET  | `/api/v1/auth/me` | current user |
| CRUD | `/api/v1/conversations` | chat threads + messages |
| POST | `/api/v1/chat/stream` | **SSE streaming chat** (memory + search + files + doc-RAG) |
| POST | `/api/v1/agents/stream` | **multi-agent run** (plan → steps → answer, SSE progress) |
| POST | `/api/v1/agents/arena/stream` | ⚔️ **Pro arena**: provider drafts → blind ballots → Grok-4 verdict (plan-capped `arena_day`) |
| POST | `/api/v1/deepsearch/stream` | **DeepSearch** (subtopics → research rounds → gap analysis → cited report) |
| POST | `/api/v1/chat/image` | image generation |
| POST/GET/DELETE | `/api/v1/files` | document & image uploads |
| GET/POST | `/api/v1/files/{id}/download` · `/reanalyze` | raw download · re-run audio/video analysis |
| POST | `/api/v1/files/analyze-video` | 🎞 video → per-frame vision captions + audio transcript + AI answer |
| POST | `/api/v1/voice/transcribe` / `/tts` / `/chat` | voice pipeline |
| POST | `/api/v1/files/analyze-audio` | 🎵 audio/music upload → transcript/lyrics + AI analysis (lands in chat) |
| GET/DELETE | `/api/v1/memory` | manage long-term memories |
| GET | `/api/v1/usage/summary` | usage meters vs. plan limits + 14-day token series |
| GET | `/api/v1/usage/export` | usage events CSV (30d) · domains analytics `?format=csv` |
| POST/DELETE | `/api/v1/conversations/{id}/share` | create / revoke a public share link |
| GET | `/api/v1/share/{token}` | **public** read of a shared conversation |
| GET/DELETE | `/api/v1/plugins[/{provider}]` | list / connect / disconnect OAuth apps |
| POST | `/api/v1/plugins/actions/{id}/approve\|reject` | human-in-the-loop write actions |
| POST | `/api/v1/media/videos` | pro video generation (plan-capped, metered) · `audio=narration\|cinema` for 🎙 AI voiceover + 🎼 ambience |
| GET | `/api/v1/media/files/{name}` | public streaming of muxed (sound-finished) videos, 24 h TTL |
| POST | `/api/v1/media/videos/enhance` | ✨ professional video-prompt rewrite |
| GET/POST/DEL | `/api/v1/media/films[/{id}[/resume]]` | 🎞 async storyboard gallery: poll status, resume stuck renders, delete |
| GET | `/api/v1/media/public/films/{id}` | 🌐 public finished-film read → SEO share pages `/f/{id}` (OG video + hero poster) |
| GET/POST | `/api/v1/admin/devices` · `/push-test` · `/engagement` | owner dashboard v2/v3: push device stats · test notification · funnel & sound analytics |
| WS | `/api/v1/voice/ws?token=` | realtime voice session (chunks in, deltas+TTS out) |
| GET/POST | `/api/v1/workspaces[...]` | teams: create, members, shared convos, seat usage |
| POST | `/api/v1/workspaces/{id}/invites` · `/join` | invite links (owner) · redeem (domain-gated) |
| POST | `/api/v1/workspaces/{id}/invites/email` | mail the invite via the owner's connected Gmail |
| GET | `/api/v1/domains/search?q=` | real-time availability + pricing |
| POST | `/api/v1/domains/connect` · `/{id}/verify` | BYO domain: DNS TXT + CNAME |
| POST | `/api/v1/domains/purchase` | buy domain (Stripe checkout → registrar) |
| PATCH | `/api/v1/domains/{id}` | brand, accent, logo, auto-renew (registrar-synced), team gate |
| POST | `/api/v1/domains/{id}/refresh` · `/{id}/renew` | pull expiry · **paid renewal** — Renew now (Stripe → registrar) |
| GET | `/api/v1/domains/{id}/analytics` | per-domain requests & users (14d) |
| PUBLIC | `/api/v1/domains/by-host` · `/allowed` | white-label lookup · Caddy TLS gate |
| POST | `/api/v1/billing/checkout` / `/webhook` | Stripe subscriptions |
| GET/PUT | `/api/v1/admin/overview` · `/settings` | 🛡 owner panel: stats · signup/app-password gate |
| POST/DEL | `/api/v1/admin/users[...]` | owner: plans, password resets, admin flag, delete user |
| GET/POST | `/api/v1/media/designs` | 🎨 Design Studio: AI flyers/logos/banners, web + 300-DPI print tiers |
| GET | `/api/v1/media/designs/{id}/download` · `/export?preset=` | owner-gated PNG tiers · 🖨 A4/A5 bleed, WA status, IG presets |
| GET/PUT | `/api/v1/media/brand` · `/media/brand/icon` | ⭐ Brand kit + generated app-icon tiles |
| POST | `/api/v1/media/videos/i2v` · `/videos/storyboard-i2v` | 📷➡️🎬 photo → animated video · photo opens a storyboard film |
| POST/GET | `/api/v1/media/edits[/{id}]` | ✂️ Auto-Edit: upload clip + instruction → 202 + poll (trim/speed/reframe/grade/subs/music/stamp/**🎵 beat-sync**) |
| POST | `/api/v1/media/designs/batch` · `/batch-csv` | 🔁 Batch studio: ≤10 photos → matching flyer set · CSV rows → card flyers (local render) |
| GET/POST | `/api/v1/media/design-orders[/{id}/close]` | 🛍 Client mode: magic order links |
| DELETE | `/api/v1/auth/me` | 🗑 permanent account deletion (password gate — Play/App Store) · public guide at `/account-deletion` |
| GET/POST | `/api/v1/media/public/orders/{token}[/download]` | 🌐 public order page + delivered delivery download |

## Feature status

| Feature | Status |
|---|---|
| Streaming chat, conversations | ✅ scaffolded |
| Live web/X/news search + citations | ✅ via xAI Live Search (`SEARCH_PROVIDER=xai_live`) |
| Long-term memory (extract + retrieve) | ✅ Qdrant + fastembed |
| Cross-conversation recall | ✅ rolling chat summaries → semantic recall + recent-chats digest; resume last chat on return |
| Multi-agent mode | ✅ concurrent workers + critic quality gate |
| Usage metering | ✅ provider-reported tokens (est. fallback) → Settings dashboard vs. plan tiers |
| Share links | ✅ revocable public read-only links + `/shared/[token]` page |
| Plugins | ✅ Gmail / Calendar / GitHub OAuth (Fernet) + tool-call loop in chat |
| Human-in-the-loop | ✅ write tools stage to approval cards; approve/reject in chat |
| Code sandbox | ✅ built-in `run_python_code` tool (rlimits + timeout subprocess) |
| Video generation | ✅ xAI video behind VideoService seam, plan-capped, metered |
| Flutter app | ✅ mobile/: login, drawer, streaming chat, voice, file upload, agent-mode view, team workspaces + invite join |
| Realtime voice | ✅ WS sessions: live deltas, per-sentence TTS queue, barge-in |
| Multi-provider router | ✅ PROVIDER_* + ROUTE_MODEL_* envs, safe xAI fallback |
| Team workspaces | ✅ shared convos + authors + per-seat usage; Settings → Teams |
| Team invites & domain gating | ✅ expiring join links + revoke; emailed via owner's Gmail; bound-domain email gate on `/workspaces/join` |
| Custom domains | ✅ connect (TXT+CNAME verify) · buy (GoDaddy + Stripe webhook) · white-label · Caddy on-demand TLS |
| Domain theme & renewals | ✅ accent/logo/favicon retheme at runtime (incl. public pages); expiry watchdog + auto-renew + paid renewal via Stripe → registrar |
| Domain analytics | ✅ real-time requests & unique users per domain (`X-Mood-Host` attribution, Redis) |
| File analysis (PDF/DOCX/XLSX/CSV) | ✅ text extraction → context |
| Image analysis / vision | ✅ Grok vision, auto model routing |
| Voice STT/TTS + voice chat | ✅ needs `OPENAI_API_KEY`; 🎵 audio-file analysis in Voice page + mobile attach |
| Chat toolbar | ✅ always-visible bar: Share/Export (with content) · team panel · mode badges |
| Image generation | ✅ `grok-2-image` |
| Stripe subscriptions | ✅ optional, webhook-wired |
| Multi-provider model router | ✅ env-configurable (see docs) |
| Responsive app shell (phone / tablet / desktop) + PWA | ✅ |
| Voice studio / image lab / settings & memory pages | ✅ |
| **Doc-RAG** (docs auto-embedded; cross-chat semantic retrieval) | ✅ |
| **Multi-agent mode** (planner → researcher/coder/writer) | ✅ — toggle 🤖 in the composer |
| **DeepSearch** (multi-round agentic research, gap analysis, cited report) | ✅ — toggle 🔭 in the composer |
| **Pro chat UX** — stop generation, regenerate, copy + code-copy, read-aloud, export .md, rename chats, ⌘K / `/` / Esc shortcuts, per-answer model badge, persistent custom instructions | ✅ |
| **Alembic migrations** (baseline + guarded upgrades) | ✅ new |
| **Observability** — Prometheus metrics, LLM instrumentation, request-id logs, health/ready probes, optional OpenTelemetry tracing | ✅ new |

### Ops quick reference

```bash
# Database migrations (inside the backend container or venv)
alembic upgrade head                              # apply all migrations
alembic stamp 0001_initial && alembic upgrade head  # adopt migrations on a PRE-existing DB
alembic revision --autogenerate -m "add table x"    # new migration after changing db/models.py

# Observability
curl localhost:8000/healthz                        # liveness
curl localhost:8000/readyz                         # postgres+redis+qdrant connectivity
curl localhost:8000/metrics                        # Prometheus scrape (Grafana-ready)

# Tracing (optional): spin up Jaeger, then set OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
docker run -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one
```

Metrics exported: `mood_http_requests_total`, `mood_http_request_duration_seconds`,
`mood_llm_requests_total` (by model + kind), `mood_llm_request_duration_seconds`,
`mood_llm_stream_chunks_total`, `mood_streams_active`.
| Plugin/tool framework | 📐 designed (see ARCHITECTURE.md §12) |
| Video generation | 📐 phase 3 |

**Deploy:** get a public URL in ~30 min — see **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

### Responsive layout — fits all screens

| Width / condition | Behavior |
|---|---|
| **Tiny phones** (<380 px) | compact composer buttons and paddings; bottom-bar labels drop at <340 px |
| **Phones** (<768 px) | hamburger → slide-over drawer; fixed bottom tab bar; safe-area aware; `100dvh` (no URL-bar jumps) |
| **Tablets** (768–1024 px) | hamburger → 320 px drawer; roomier grids |
| **Laptops/desktops** (1024–1536 px) | persistent 288–320 px sidebar |
| **Large monitors** (1536–1920 px) | sidebar widens to 384 px; content columns widen; image grid 5-up |
| **Ultrawide** (>1920 px) | content stays centered and capped — never a wall of text |
| **Landscape / short screens** (<560 px height) | compact vertical spacing, scaled-down voice orb |

Global hardening: no horizontal overflow anywhere, long URLs/tables/code in answers
scroll instead of breaking layouts, images scale to their container, fluid clamp() typography.

Preview the tiers without running anything: open `docs/ui-design-preview.html`
(static mock — buttons are illustrative).

### Testing on a real phone (same Wi-Fi)

1. Find your computer's LAN IP (`ipconfig getifaddr en0` / `ip addr`): e.g. `192.168.1.50`.
2. **The API must be reachable from the phone** — `localhost` inside the phone means the phone itself! Rebuild the frontend with:
   ```bash
   NEXT_PUBLIC_API_URL=http://192.168.1.50:8000/api/v1 docker compose up --build
   ```
3. Open `http://192.168.1.50:3000` on the phone, register/login, then the bottom tabs work.
4. If taps feel "dead": hard-refresh first (old cached JS) — the shell pins the tab bar in normal flow above the visible viewport, so it is always on-screen and tappable.
