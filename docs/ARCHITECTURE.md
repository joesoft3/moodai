# Mood AI — Architecture Blueprint

A production-oriented design for a **Grok-class AI super-app** built by orchestrating
existing frontier models (xAI/Grok primary), a FastAPI backend, and a Next.js web client.
No model training required — every capability is an integration concern.

---

## 1. Product pillars

| Pillar | What users feel | How it's delivered |
|---|---|---|
| Fast | Tokens stream instantly; search answers in one turn | SSE streaming, Live Search, model routing |
| Personal | The assistant remembers you | Memory extraction + vector retrieval (Qdrant) |
| Current | Answers cite today's web/X/news | xAI Live Search (`search_parameters`) |
| Multimodal | Talk, upload, look, generate | Whisper/TTS, text extraction, Grok vision, image gen |
| Extensible | Agents + plugins do work | Tool registry, multi-agent orchestrator (phased) |

---

## 2. High-level architecture

```
                         ┌─────────────────────────────┐
                         │        Next.js web app       │
                         │  chat UI · voice UI · files  │
                         │  (Later: Flutter mobile app) │
                         └──────────────┬───────────────┘
                                 HTTPS / SSE / JWT
                                        │
                         ┌──────────────▼───────────────┐
                         │        FastAPI backend        │
                         │ ┌───────────────────────────┐ │
                         │ │        API layer          │ │
                         │ │ auth · chat · files ·     │ │
                         │ │ voice · memory · billing  │ │
                         │ └───────────┬───────────────┘ │
                         │ │      Orchestration layer    │ │
                         │ │ context builder · persona · │ │
                         │ │ model router · rate limits  │ │
                         │ └───────────┬───────────────┘ │
                         │ │         Service layer       │ │
                         │ │ llm (xAI) · memory · search │ │
                         │ │ file_extract · voice        │ │
                         │ └───────────┬───────────────┘ │
                         └─────────────┼─────────────────┘
        ┌────────────────┬─────────────┼───────────────┬────────────────┐
        ▼                ▼             ▼               ▼                ▼
   ┌─────────┐     ┌──────────┐  ┌──────────┐   ┌───────────┐    ┌───────────┐
   │ xAI API │     │ Postgres │  │  Qdrant  │   │   Redis   │    │  Storage  │
   │ chat ·  │     │ users ·  │  │  memory  │   │ rate-lim. │    │ uploads → │
   │ vision ·│     │ convos · │  │ vectors  │   │ cache ·   │    │ S3/CDN in │
   │ search ·│     │ billing  │  │ (later:  │   │ queue     │    │ prod)     │
   │ images  │     │          │  │ doc-RAG) │   │           │    │           │
   └─────────┘     └──────────┘  └──────────┘   └───────────┘    └───────────┘
        ▲
        │  voice only        ┌──────────┐
        └────────────────────│  OpenAI  │ Whisper STT · TTS (swappable:
           (OPENAI_API_KEY)  │ Whisper/TTS│ ElevenLabs, Deepgram, edge-tts)
                             └──────────┘
```

**Why this shape?** The backend never talks to the model directly from request handlers;
everything flows through small, replaceable services. Swapping xAI for Anthropic/Gemini/an
open-weight model is a config change at the router layer, not a rewrite.

---

## 3. Chat request lifecycle (the core loop)

1. **Auth + rate limit** — JWT verified; Redis token bucket (`chat:{user_id}`, 30/min default).
2. **Conversation resolution** — existing thread or create; user message persisted.
3. **Context assembly** (`build_messages`):
   - Persona system prompt (witty, truthful, citation-aware).
   - **Memory block** — semantic top-k facts for this user + current message (Qdrant, score ≥ 0.30).
   - **Past-chat recall block** — semantic top-k summaries of *other* conversations (Qdrant `kind="chat"`, score ≥ 0.38).
   - **Recent-chats digest** — brand-new threads also get the 2 most recent chat summaries, so
     *"continue where we left off"* / *"what did we discuss last time?"* work directly.
   - **File context** — extracted text wrapped in `<file>` tags; images become vision content parts.
   - **Search context** — either xAI Live Search enabled on the request *or* Tavily snippets injected.
   - Last 20 turns of history (sliding window).
4. **Model routing** — vision model if images are present, otherwise the chat model.
5. **SSE stream** — events: `meta` (conversation id/model) → `delta` tokens → `citations` → `done` / `error`.
6. **Post-turn (background)** — assistant reply persisted; **memory extraction** runs on cheap model;
   **rolling conversation summary** refreshed (debounced: first exchange, then every other one);
   conversation title generated for new threads.

Everything after step 5 is fire-and-forget, so latency stays at model speed.

---

## 4. Model routing

| Task | Default model | Why | Override |
|---|---|---|---|
| Main chat / coding / reasoning | `grok-4` | frontier quality, long context, tools | `MODEL_CHAT` |
| Memory extraction, titles, summaries | `grok-3-mini` | cheap + fast JSON | `MODEL_FAST` |
| Image understanding | `grok-2-vision-1212` | vision API support | `MODEL_VISION` |
| Image generation | `grok-2-image-1212` | xAI image endpoint | `MODEL_IMAGE` |
| Embeddings for memory | `all-MiniLM-L6-v2` (local, fastembed/ONNX) | zero API cost, private | `EMBED_MODEL` |
| STT / TTS | `whisper-1` / `tts-1` (OpenAI) | xAI has no public STT/TTS — abstracted behind `VoiceService` | `WHISPER_MODEL`, `TTS_MODEL` |

**Multi-provider path (per your instinct to route per-task):** all model names are env vars and
`XAI_BASE_URL` points at any OpenAI-compatible endpoint. Add `LLMService` subclasses per provider,
keyed by task, to route e.g. coding → Claude, long-context → Gemini, default → Grok.

---

## 5. Long-term memory design

- **Write path:** after each turn, `grok-3-mini` runs an extraction prompt over the exchange and
  returns strict JSON `{memories:[{fact, category}]}`. Facts are embedded locally and upserted
  into Qdrant with a deterministic id (`uuid5(user_id + fact)`), so re-learning the same fact
  overwrites instead of duplicating.
- **Read path:** the current user message is embedded; top-k (default 6, score ≥ 0.30) facts for
  that user are injected as a system block: *"Known facts about this user — use naturally, never recite."*
- **Control:** users can list/delete/clear memories via `GET/DELETE /api/v1/memory` (privacy by design).
- **Roadmap:** fact decay (score × age), contradiction resolution prompts, per-conversation
  scratchpad vs. global memory, doc-RAG collection reuse.

### 5.0 Usage metering & sharing

Plan ladder enforced server-side (`PLAN_LIMITS`): tokens/images/deep-search/agents/videos per month
or day; `arena_day` (free 3 teaser → pro 100); **Pro perks** — `upload_mb` 25→50 (413 error names the
upgrade), `mem_days` 30→365 (fact/digest pruning in `extract_and_store` via `prune_old_memories`),
`plan_rate_mult` 1×→4× on all per-minute rate limits.


- **Metering:** every user-facing action writes a `usage_events` row (kind, model, tokens).
  Token counts are provider-reported (`stream_options=include_usage`, response `usage`) when
  available, else a chars/4 estimate flagged `estimated=true`. `GET /api/v1/usage/summary`
  aggregates month/day meters vs. plan tiers (`PLAN_LIMITS` in `services/metering.py`) plus a
  14-day series → Settings usage dashboard.
- **Sharing:** `POST /conversations/{id}/share` mints a revocable `shared_links.token`;
  `GET /api/v1/share/{token}` is public (IP rate-limited) and powers the login-free
  `/shared/[token]` page.

### 5.1 Cross-conversation recall (remembering previous chats)

Facts tell Mood *who you are*; recall tells it *what you've discussed*. Two pieces in `services/recall.py`:

- **Rolling summaries.** After replies (debounced — 1st exchange, then every other one),
  `grok-3-mini` maintains a ≤100-word summary per conversation, stored on `conversations.summary`
  and embedded into the same Qdrant collection with payload `kind="chat"` and a deterministic
  point id (`uuid5(chat:{user}:{conv})` → upsert = update in place). Summaries also power the
  title-bearing recall lines and the Settings "Past conversations" list.
- **Read path.** Every message: vector-search past-chat summaries (`score ≥ 0.38`, current chat
  excluded, top 3) → injected as *"Memories from this user's PREVIOUS conversations…"*. Brand-new
  threads additionally receive the **2 most recent summaries** straight from Postgres, so temporal
  references ("yesterday", "last time") resolve without relying on embeddings.
- **Consistency:** deleting a conversation purges its recall vector; *Clear all* in Settings wipes
  facts, recall vectors **and** Postgres summaries. Frontend also re-opens your last active
  conversation on return (`localStorage` key `mood.lastConvId`).
- **Knobs:** `RECALL_TOP_K` (3), `RECALL_MIN_SCORE` (0.38), `RECENT_CHATS_DIGEST` (2).

---

## 5.2 ⚔️ Arena — the Pro feature (multi-model debate)

`services/arena.py` + `POST /api/v1/agents/arena/stream`.

- **Panel (streamed).** Drafts generate **token-by-token in parallel** (`_stream_drafts` multiplexes
  one `llm.stream_chat` per provider through a single queue → `draft_delta` events so the UI shows
  live char counts), from every provider that has
  an API key: xAI `ARENA_XAI_MODEL` (default `MODEL_CHAT`, also the judge), OpenAI
  `ARENA_OPENAI_MODEL` (gpt-4o), Gemini `ARENA_GEMINI_MODEL` (gemini-2.5-pro), plus an
  optional user-picked extra (`gemini-2.5-flash` / `grok-code-fast-1`). Providers without keys
  are skipped with `warning` events; a single configured provider degrades to a direct answer.
- **Blind ballots.** Drafts are shuffled into anonymous slots A/B/C; every contestant then votes
  for the best answer (`vote_cast` events; malformed ballots marked invalid).
- **Verdict + scores.** Grok-4 judges drafts + ballots, names the winner by slot and returns
  per-draft **score cards** (`{"accuracy","clarity"}` 1–10 → chips on each draft row).
  (`arena_verdict`: winner, drafts, draft_order, votes, per-provider token usage). Judge fallbacks:
  plurality of ballots → first slot.
- **Rematch.** `rematch: true` re-runs the arena with the previous winning answer injected into
  every drafter's prompt ("beat this answer"); the topic event carries `rematch: true` and the UI
  shows a 🔁 one-tap Rematch button on arena answers.
- **Answer.** The winning draft streams as `delta`s and persists with `meta.mode="arena"`
  (verdict + drafts + ballots), so reloads restore the full panel — replays render statically.
- **Gating & metering.** `PLAN_LIMITS[*]["arena_day"]` (free 3/day teaser, pro 100/day) enforced
  before any LLM call; over-limit streams a `plan_limit` error event (frontend shows the
  ✨ Upgrade to Pro banner). Usage meters per-provider in/out tokens as kind `arena`.

## 6. Real-time search grounding

Primary: **xAI Live Search** — a `search_parameters` field on the chat request
(`mode: auto`, sources: web + X + news, `return_citations: true`). The model itself decides when
to search and returns citation URLs, surfaced in the UI under each answer.
Fallback/alt: `SEARCH_PROVIDER=tavily` injects classic retrieval snippets as context instead —
useful for cost control or when Live Search is unavailable.

### 6.1 DeepSearch (Grok-style deep research)

`POST /api/v1/deepsearch/stream` runs an agentic research loop for complex questions:

```
goal → decompose into 4–5 research questions (planner)
     → ROUND: live-search all questions concurrently (xAI Live Search)
     → gap analysis: critic identifies what's missing → follow-up queries
     → repeat 2× ("deep") or 3× ("deeper", up to 40 unique sources)
     → writer synthesizes a structured markdown report with inline [n](url) citations
```

SSE events: `subtopics → round_start → query_start/done → reflect → writing → delta`.
The UI shows subtopic chips + a rolling research log above the streamed report.

---

## 7. File intelligence

**Phase 1 (in scaffold):** upload → type-detect → extract text (`pypdf`, `python-docx`, `openpyxl`)
→ store raw file + extracted text (capped at 30 K chars) → injected into the chat context in
`<file>` tags. Images bypass extraction and go straight to the vision model as downscaled
(≤1600 px) data URLs.

**Phase 2:** chunk + embed documents into a separate Qdrant collection (`doc_chunks`), cite
page/sheet, OCR fallback for scanned PDFs. The memory service is already generic enough to reuse.

---

## 8. Voice pipeline

- **Dictation:** browser `MediaRecorder` (webm) → `POST /voice/transcribe` (Whisper) → textarea.
- **Audio-file analysis:** `POST /files/analyze-audio` (mp3/wav/m4a/ogg/flac, ≤`MAX_AUDIO_UPLOAD_MB`,
  5/min) → Whisper transcript (music → lyrics) → structured LLM analysis (transcript/lyrics,
  what-it-is, themes & mood, song identification) → always landed as a user/assistant exchange
  in a conversation so it's resumable/exportable; metered as `voice`. Web Voice page card +
  Flutter audio-aware attach both call it.
- **Voice mode:** audio → transcribe → same chat context-builder as text → complete →
  `tts-1` → `{transcript, reply, audio_b64}` → client plays immediately.
- xAI has no public STT/TTS API; the `VoiceService` is a seam — swap in ElevenLabs/Deepgram/
  local faster-whisper+edge-tts without touching routes or UI. WebRTC/Realtime API for
  low-latency barge-in is the phase-3 upgrade path.

---

## 9. Media generation (image now, video later)

`POST /chat/image` → xAI Images API (`grok-2-image-1212`), URL or base64 returned.
**Video (phase 3):** define a `MediaService` interface (`generate_video(prompt, duration, aspect)`)
with pluggable providers (xAI when public, Runway, Pika, Luma) — same pattern as `VoiceService`.
Jobs are long-running → move to the background queue (§13) with webhook/polling status.

---

## 10. Data model (Postgres)

```
users ─────────┐  id · email · hashed_password · display_name · plan · created_at
               │ 1:N
conversations ─┤  id · user_id · title · created_at · updated_at
               │ 1:N
messages ──────┤  id · conversation_id · role · content · meta(JSON) · created_at

files           id · user_id · conversation_id? · filename · mime · path ·
                size_bytes · extracted_text · created_at

subscriptions   id · user_id (unique) · stripe_customer_id ·
                stripe_subscription_id · status · current_period_end

Qdrant "user_memories":  point = { id, vector(384), payload: {user_id, fact, category} }
```

Migrations: scaffold uses `create_all` at startup; adopt **Alembic** before production.

---

## 11. Multi-agent mode ✅ (implemented: concurrent + critic)

**Pattern:** one **Orchestrator** (planner) + role agents, all on top of the same `LLMService`
with per-agent system prompts, models and tools. Agents communicate via structured JSON plans,
not free chat.

| Agent | Model | Tools | Job |
|---|---|---|---|
| Planner/Orchestrator | `grok-4` | agent dispatch | decompose goal, route subtasks, synthesize |
| Researcher | `grok-4` + Live Search | web/X/news search, fetch_page | gather + cite sources |
| Coder | `grok-4` (or Claude via router) | file read/write, sandbox runner | produce & smoke-test code |
| Writer | `grok-4` | style memory | long-form drafting |
| Critic | `grok-3-mini` | — | fact-check/cost-aware review |

Execution (implemented): the Planner returns 2–4 steps; specialist steps (researcher/coder)
run **concurrently** as asyncio tasks — `step_start` events fire up front, `step_done` fires in
completion order (all events carry a step index `i`). The **writer** then synthesizes with full
visibility of worker outputs, and a **critic** pass (added automatically, not by the planner)
fact-checks, fills gaps and polishes the draft before it streams to the client. Token usage is
accumulated across all agents and metered as one "agent" usage event.

---

## 12. Plugin / tool framework ✅ (implemented v1: Gmail, Calendar, GitHub)

- **Connectors (implemented):** Gmail (list/send), Google Calendar (list/create), GitHub
  (repos, issues, create issue) — `services/plugins/` with a provider **registry**
  (OAuth URLs, scopes, API base), **Fernet-encrypted** tokens in `plugin_connections`
  (`PLUGIN_TOKEN_KEY`; dev falls back to a JWT_SECRET-derived key), server-side **refresh** for
  Google tokens, and signed-JWT OAuth state (`/api/v1/plugins/{p}/connect|callback`).
- **Loop (implemented):** when the composer 🧩 toggle is on, `resolve_plugins()` runs up to
  `PLUGIN_MAX_CALLS` function-calling rounds (tools = built-ins + the user's *connected*
  providers), collects results, and injects them as a system context block the streamed Grok
  pass answers from. The client shows 🧩 pills for every executed call.
- **Human-in-the-loop (implemented):** write tools (`gmail_send_message`,
  `calendar_create_event`, `github_create_issue`) never execute in the loop — they become
  `pending_actions` rows, the stream emits a `confirm` event, and the UI renders an approval
  card (Approve/Reject → `POST /plugins/actions/{id}/approve|reject`). Mood’s reply is told
  explicitly not to claim completion.
- **Built-in tools (implemented):** `run_python_code` — subprocess sandbox (`services/sandbox.py`,
  isolated mode, CPU/memory rlimits, hard timeout, clipped output; documented as NOT a hardened
  boundary — front with gVisor/Firecracker for hostile multi-tenant prod).
- **Roadmap:** Drive, Slack; per-tool audit log; `memory_write` tool; remote sandbox provider.

---

## 12b. Media & mobile

- **Video Studio (professional):** options (duration/aspect/quality/style/negative) → prompt
  compiler layers style presets + quality tags; lean-retry if the provider rejects extended
  params; ✨ enhancer rewrites rough ideas into director-grade prompts (`grok-3-mini`);
  frontend shows templates, option chips, staged progress, and meta badges on results.
- **Realtime voice:** `WS /api/v1/voice/ws` — browser streams 300ms audio chunks; server does
  STT → streamed LLM deltas → per-sentence TTS (bounded concurrency, ordered) → playback queue
  client-side; `interrupt` = barge-in. REST `/voice/*` remains for Flutter & simple clients.
- **Multi-provider router:** `LLMService` keeps one client per provider (xai/gemini/openai —
  any OpenAI-compat endpoint); `route(task)` honors `PROVIDER_<TASK>` + `ROUTE_MODEL_<TASK>`
  with a deterministic xAI fallback. Live Search stays xAI-only (researcher/deepsearch).
- **Team workspaces:** `workspaces` + `workspace_members`; `conversations.workspace_id` marks
  shared threads; `messages.user_id` tags authors. Owners manage members (by email) and get a
  per-seat usage rollup (join over `usage_events`).

- **Video:** `services/media.py` `VideoService` — provider seam (`VIDEO_PROVIDER`, default
  `xai`; async-task polling, tolerant response parsing). `POST /api/v1/media/videos` is gated
  by plan-tier daily caps (`count_today` over `usage_events`) and metered as kind `video`.
  Image Lab UI doubles as Media Lab with a 🖼/🎬 toggle.
- **Mobile:** `mobile/` — Flutter client (login/register, conversation drawer, streamed SSE
  chat with markdown, voice + file parity, agent steps). **Teams parity:** drawer workspace
  switcher (`GET /workspaces` + `/{id}/conversations` with author labels on bubbles) and
  invite redemption (`POST /workspaces/join`, paste link or bare code). API root injected via
  `--dart-define=API_URL=…`.

## 12c. Custom domains (business white-label)

- **Connect your own:** `POST /domains/connect` returns a TXT token + CNAME target; **Verify**
  does real dnspython lookups; active domains are white-labeled (brand served via public
  `/domains/by-host`, sidebar + tab title swap at runtime).
- **Buy in real time:** `GET /domains/search` (GoDaddy availability + suggest + cost) → `POST
  /domains/purchase` creates Stripe checkout (cost + `DOMAIN_MARKUP_PCT`) → `checkout.session.
  completed` webhook calls `fulfill_domain_purchase`: buy at registrar, point DNS (www CNAME +
  optional apex A), seed expiry, status active, optional Vercel attach. `GODADDY_ENV=ote` = free
  sandbox for testing the whole loop; `production` = real money/registrations.
- **Edge:** optional Caddy (`--profile edge`) with on-demand TLS `ask` → `/domains/allowed`
  (200 = active, 403 = refuse) — unverified domains can't even get a cert.
- **Renewals & expiry:** `domains.expires_at` is synced from the registrar by a background
  **expiry watchdog** (`DOMAIN_SYNC_HOURS`, refreshes anything unknown/expiring <90d, starts 90s
  after boot) and on-demand via `POST /domains/{id}/refresh`. The auto-renew toggle (`PATCH
  /domains/{id}`) calls GoDaddy `PATCH /v1/domains/{d} {renewAuto}` for purchased domains and is a
  reminder-preference for connected ones; the UI badges red/amber as expiry approaches.
- **Paid renewal:** inside the window (`DOMAIN_RENEW_WINDOW_DAYS`) the UI offers 🔁 **Renew now** →
  `POST /domains/{id}/renew` builds a Stripe checkout at the original marked-up per-year rate → the
  webhook (`metadata.type=domain_renewal`) calls `fulfill_domain_renewal`: registrar
  `POST /v1/domains/{d}/renew` then re-syncs the expiry. When auto-renew is OFF and the domain is
  inside the window, the watchdog also **emails the owner once per expiry** (via their connected
  Gmail; Redis dedup key includes the expiry date).
- **Per-domain theme:** `accent` (#rrggbb) + `logo_data` (≤150 KB data-URL) served by
  `/domains/by-host`; AppShell injects a `#mood-brand` stylesheet overriding the compiled accent
  Tailwind classes, swaps the sidebar logo + favicon. White-label is name → color → mark.
- **Per-domain analytics:** the browser sends `X-Mood-Host: <page origin>` on every API call
  (`apiFetch`/`streamChat`); a fire-and-forget middleware resolves host → active Domain
  (Redis-cached 5 min, negatives 60s, DB at most once per interval) and bumps daily
  `domstat:{id}:req:{ymd}` counters + `domstat:{id}:usr:{ymd}` sets (40d TTL). Owners read
  `GET /domains/{id}/analytics` → tiles + 14d chart; zero schema changes, fail-open.

### 12c-i. Team invites & domain gating

Owners mint expiring invite links (`POST /workspaces/{id}/invites`, `INVITE_TTL_DAYS`, revocable,
max 20 listed). Anyone signed in redeems via `POST /workspaces/join` (frontend `/join/[token]`,
with `/login?next=` round-trip for logged-out visitors). If the workspace has an **active bound
domain** (`PATCH /domains/{id} {workspace_id}`, owner-only), joins are gated: the account's email
domain must equal the bound domain or share a subdomain/parent boundary with it (bound
`chat.acme.com` admits `@acme.com` and `@chat.acme.com`). Gate failures return **403** with the
accepted domains. This is the "business" half of custom domains: brand *and* access control ride
the same Domain row.

Invites can also be **emailed** (`POST /workspaces/{id}/invites/email`, owner): the backend reuses
an existing valid link (or mints one) and sends it through the owner's connected **Gmail plugin**
(`services/notify.py` → `gmail.send` scope, auto-refreshing tokens, best-effort per recipient,
409 when Gmail isn't connected so the UI can fall back to copy-link). The same notifier powers
domain renewal reminders. White-label travels with the links: `/join/[token]`, `/login` and
`/shared/[token]` all resolve `useBrand()` (host → active domain) and re-theme + show the owner's
logo — invitees experience the company brand end-to-end.

## 13. Background jobs & caching

Scaffold uses FastAPI `BackgroundTasks` for memory extraction and titling. Production:
**ARQ or Celery on Redis** for job retries (embeddings, doc ingestion, video jobs).
Redis also provides: rate limiting (done), conversation hot-cache, idempotency keys,
and pub/sub to fan-out agent progress to the UI.

---

## 14. Security checklist

- ✅ Passwords: pbkdf2 (swap to argon2/bcrypt trivially); JWT HS256, 7-day expiry
- ✅ Per-user data isolation enforced in every query (`user_id` filter on memories/files)
- ✅ Upload allowlist, size caps, filename sanitization, image downscale
- ✅ Rate limiting on chat and voice
- ☐ Add: refresh tokens or swap in **Clerk/Firebase Auth** (your original plan — drop-in at `get_current_user`)
- ☐ Secrets via platform secret store; CORS locked to your domains; HTTPS-only cookies option
- ☐ Audit log for plugin actions; PII redaction toggle for memory extraction

---

## 15. Billing

Stripe Checkout (subscription mode) + webhook → `subscriptions` table. `plan` field on the user
gates rate limits (free: 30 msgs/min·day caps; pro: higher + voice + image gen).
Both degrade gracefully (503 with setup hint) when keys are absent — local dev stays free.

---

## 16. Deployment path

**Now:** `docker compose up` — single host, internal networking, named volumes.

**Scale up (Kubernetes):**
- Backend: stateless Deployment, HPA on CPU/RPS, rolling updates; secrets via env from Secrets.
- Frontend: Next.js Deployment behind CDN; `NEXT_PUBLIC_API_URL` as build arg.
- Data: managed Postgres (RDS/CloudSQL), Redis (ElastiCache/MemoryStore), Qdrant Cloud — or in-cluster
  with StatefulSets if you must. Uploads → S3/GCS (`UPLOAD_DIR` becomes object storage prefix).
- Ingress: TLS at edge; WebSocket/SSE-friendly (increase proxy timeouts, disable buffering —
  we already send `X-Accel-Buffering: no`).
- Observability: structured logs (done), add OpenTelemetry traces around LLM calls,
  token-usage metrics per user for cost dashboards, Sentry on both tiers.

---

## 17. Cost optimization playbook

1. Route bulk/generative tasks (extraction, titles) to `grok-3-mini` — already the default.
2. Sliding-window history (20 turns) + file text caps (30 K chars) keep prompt sizes bounded.
3. Redis-cache memory retrieval for hot conversations; dedupe uploads by content hash.
4. Rate limits + plan tiers; per-user token accounting in `messages.meta` (usage events).
5. Prefer Live Search `mode: auto` over `on` so the model only searches when needed.

---

## 18. Phased roadmap

| Phase | Scope (from your feature list) |
|---|---|
| **P0 — this scaffold** | chat + memory + live search + files/vision + voice + auth + Stripe hooks + image gen |
| **P1** | doc-RAG ✅, Flutter mobile app (API is already mobile-friendly), Clerk/Firebase swap, Alembic, usage metering |
| **P2** | multi-agent mode v1 ✅ (concurrent subtasks + critic next), plugin framework + Gmail/Calendar/GitHub connectors (§12), job queue, code-execution sandbox |
| **P3** | video generation, Realtime voice (WebRTC), team workspaces, enterprise SSO, on-prem/open-weight model option |

---

## 19. Open decisions for you

1. **Voice provider** — OpenAI (default) vs. ElevenLabs (better voices, more cost).
2. **Auth** — keep built-in JWT or move to Clerk/Firebase at P1 (recommended for social logins).
3. **Storage** — local volume now; pick S3 vs. Cloudinary (good if you want image transforms/CDN).
4. **Model strategy** — single-provider (simplest) vs. the router you described (best quality/cost mix).

## 15. 🛡 Owner bootstrap & sign-up gate

- **Env-bootstrapped owner.** `ADMIN_BOOTSTRAP_EMAIL` + `ADMIN_BOOTSTRAP_PASSWORD`
  (shipped in the generated `.env`) create—or promote to `is_admin`—a guaranteed owner login
  at every backend boot (`services/bootstrap.py`, idempotent, never overwrites an existing
  password). `ADMIN_EMAILS` additionally marks any login email as admin.
- **Sign-up gate.** `POST /auth/register` consults `platform_settings`:
  `signup_open` (owner panel toggle) and `app_password_hash` (access code, pbkdf2-hashed).
  `APP_PASSWORD` in `.env` seeds the hash once at boot; rotations in the owner panel win.
  Register requests supply `app_password` when a gate is active (login page has the field;
  smoke test via `SMOKE_APP_PASSWORD`).
- **Owner panel** (`/admin`, frontend `app/admin/page.tsx`): platform overview tiles, gate
  controls, user administration (plan change, password reset, admin flag, delete) — all under
  `require_admin` (is_admin flag or ADMIN_EMAILS).
