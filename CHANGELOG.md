# Changelog

All notable changes, fixes, and new features shipped to `main` for ChatMood.
Each entry links the pull request it landed in. Dates are UTC.

---

## 2026-08-23

### 🪰 Fix — deploy-fly turned red while CI stayed green (PR #54)

The 2026-08-20 Fly deploy of the Cloudflare/CORS fix failed after ~6 min
(remote build / machine never became healthy), and **nothing since has reached
the Fly API** — CI's unit gate was green the whole time because it never boots
the app. Three gaps, three fixes:

- **Reproducible builds.** The image installed `requirements-full.txt` with
  loose `>=` pins, so the Fly remote builder (cold pip cache) could resolve a
  different — and broken — dependency world than CI (cached wheels) had
  validated. New `backend/constraints.txt` pins the exact set that passed
  694 tests + full boot + `/readyz` + CORS preflight; `Dockerfile.fly`,
  `backend/Dockerfile` and CI all install with `-c constraints.txt`.
- **CI now gates on a real boot.** New `scripts/boot-smoke.sh` (wired into
  `test.yml`) boots uvicorn exactly like the container CMD, waits for
  `/readyz`, then asserts: healthz ok, readyz `ready:true` with the postgres
  check ok, CORS preflight **allowed** for `FRONTEND_URL` and **denied** for a
  foreign origin, `/auth/me` 401s unauthenticated, and `/` redirects to the
  web app. "Unit green, machine dead" can no longer reach main silently.
- **Deploy failures are diagnosable.** `deploy-fly.yml` now tees the deploy
  output and posts the tail — plus `fly status` and boot logs — as
  **annotations and the step summary**, so the actual error survives even when
  raw job logs are unreachable. Health-check headroom widened to match
  reality: `grace_period` 40→60s (alembic + uvicorn boot), `/readyz` probe
  timeout 10→15s (Neon cold-start measured at 4–15s).

Tests: unchanged suite (694 passed on the pinned set) + new boot smoke.

---

## 2026-08-20

### ☁️ Fix — Cloudflare custom domains never reached the origin (522) (PR #52)

Connecting a domain through Cloudflare looked set up, then the browser could not
reach ChatMood. Three bugs stacked:

- **Record upsert looked up a relative name** (`chat`, `@`) while Cloudflare's
  list API matches on the FQDN. Retries never found the existing row, POST
  collided, and leftover **orange-cloud A records** kept pointing at a dead
  origin — Cloudflare Error **522 / 526**.
- **Verify only asked public DNS for a CNAME.** Orange-cloud / CNAME flattening
  hides that CNAME, so the domain stayed `pending_dns`, Caddy
  `/domains/allowed` 403'd, and on-demand TLS never issued.
- **System resolvers cached NXDOMAIN** for minutes after we wrote the records.

Now upsert matches by FQDN, replaces conflicting A/AAAA/CNAME, and **forces
DNS-only (grey cloud)** so Cloudflare is not the HTTPS client of Fly/Caddy.
Verify accepts flattened A records, falls back to 1.1.1.1 DoH, and treats the
Cloudflare API as authoritative on active zones. Unreachable `api.cloudflare.com`
is a clear `DomainError` instead of a raw connect failure.

Follow-up so the browser actually talks to the API after DNS is right:

- **CORS** now allows `FRONTEND_URL` (and its www twin) plus every **active
  custom domain**, so a white-label / Cloudflare host no longer dies as
  `Failed to fetch` → “Can't reach the ChatMood server”.
- Apex provision also writes a grey-cloud **www** record; Caddy `/domains/allowed`
  and `/domains/by-host` treat `www.` as the same site.

Tests: `test_domains_cloudflare.py`, `test_cors_domains.py`.

---

## 2026-08-19

### 🔐 Fix — chat always said "Invalid or expired token"

A leftover `mood_token` in localStorage (or a JWT the current backend no longer
accepts — secret rotated, already-expired, or the literal string `"undefined"`)
was treated as signed-in. `/login` bounced straight back to `/chat`, every send
401'd with **Invalid or expired token**, and there was no way out without
clearing site data.

- **Web + Flutter** now verify the stored JWT against `/auth/me` before treating
  it as a session, and any authenticated 401 clears it and returns to sign-in
  (`?expired=1` explains why). Login/register no longer attach a leftover Bearer.
- **JWT minting** writes `exp` as a Unix timestamp (datetime encoding could
  fail decode on the next request), floors TTL at 15 minutes so
  `ACCESS_TOKEN_EXPIRE_MINUTES=0` cannot mint an already-dead token, and decode
  allows 60s of clock skew.
- Missing `Authorization` is a consistent **401** (not FastAPI's default 403).
- Mobile `1.9.11+27`. Tests: `test_session_token.py`.

---

## 2026-08-19

### ❓ Landing FAQ — best questions, straight answers

The landing page now answers the nine questions people actually ask, right
above the footer (`#faq`, also in the nav's Explore menu):

- "What is ChatMood?", "Is ChatMood free?", models, live web search,
  image/video creation, memory, the mobile app, MoMo payments and privacy —
  each a one-glance answer, no marketing fog.
- Native `<details>` accordions: server-rendered (zero client JS), keyboard +
  screen-reader accessible for free, styled to the home palette with an
  animated chevron.
- **FAQPage JSON-LD** is generated from the same `FAQ_ITEMS` source as the
  rendered copy, so rich results can never drift from what visitors read.
- e2e covers it: section renders, structured data present, accordion expands.

---

### 🎬🆓 Free video cascade — Veo + Hugging Face join the chain

`VIDEO_PROVIDER` gains two free-of-charge engines alongside reel /
pollinations / xai, with the same lean cascade semantics (first success
wins, each hop fail-soft):

- **gemini** (alias `veo`) — Google Veo via the Gemini API `predictLongRunning`
  op, polled to done; AI Studio's free tier carries a small daily Veo quota
  when the key's project is granted it. Over-quota/unfunded keys cascade on.
  Reuses `GEMINI_API_KEY`; model pinned to `veo-3.1-fast-generate-preview`
  (`GEMINI_VIDEO_MODEL` to override).
- **huggingface** (alias `hf`) — HF Inference text-to-video (Wan2.1-T2V-1.3B
  default, the free-credit-friendly variant) on the free `HF_API_TOKEN`, with
  cold-model `estimated_time` wait-and-retry.
- Both save provider bytes via the media janitor, so soundtrack mixing and
  library archiving see a plain `/api/v1/media/files/…` URL like every clip.
- Chain docs + examples in `.env.example`; brain status reports per-provider
  readiness/reasons for the new engines.

e.g. `VIDEO_PROVIDER=gemini,huggingface,reel` = Veo free quota first, HF
credits second, zero-key Reel as the always-on floor.

---

### 🎨 Free image cascade — three more free generators

`IMAGE_FALLBACK_PROVIDER` is now a comma-separated **cascade of free image
engines**, tried left→right whenever xAI image gen fails or is unfunded
(e.g. `gemini,huggingface,pollinations`).

- **pollinations** — free FLUX, no API key at all (as before, now one hop of a chain).
- **gemini** — Gemini image models via the native generateContent API; free daily
  quota in AI Studio, reuses `GEMINI_API_KEY`.
- **huggingface** — HF Inference free daily credits on a free `HF_API_TOKEN`
  (FLUX.1-schnell default, model overridable).
- **cloudflare** — Workers AI free 10k neurons/day; dedicated `WORKERS_AI_*`
  pair, falling back to the existing `CLOUDFLARE_*` creds.

An engine with missing credentials, an HTTP error, quota exhaustion, or an
image-less response is skipped to the next automatically. With no `XAI_API_KEY`
the first working entry **is** the image engine (fully-free stack). Single-value
`pollinations` behaves exactly as before; brain/admin status surfaces report the
chain per engine (`enabled`/`configured`).

---

### 🖼️ Free image fallback pinned in the Fly deploy

`fly.toml` now ships `IMAGE_FALLBACK_PROVIDER=pollinations`, so image
generation never hard-fails when xAI team credits are at $0: Grok stays
primary and Pollinations FLUX takes over automatically — daily free images,
no extra API key needed. (The support was in the code; it relied on a
manually-set secret that a redeploy could lose.)

---

### 🔗 Production link opens the app, not a bare 404

The public production URL (the GitHub repo homepage link and anything pointing
at the API host, e.g. `moodai-alpha.vercel.app`) answered `{"detail":"Not
Found"}` at `/`, so following it looked like the app was down.

- **`GET /` now redirects** to the web app (`FRONTEND_URL`) with a 302.
- Dev (`localhost` default) and the deploy guide's `https://pending`
  placeholder fall back to `/docs`, so the bare API host always lands somewhere
  useful.
- Kept out of the OpenAPI schema (it is a human landing, not an API surface).
- Regression-covered in `tests/test_boot.py`.

---

### 🏠 ChatGPT home style

The product home is now the chatgpt.com layout — not a Grok studio with Ask /
Imagine / Reel chrome.

- **Empty `/chat`** is greeting → composer → starter chips. No brand bubble,
  model-pill row, or tab strip. Model choice lives in a header dropdown.
- **Composer** is a calm rounded bar: `+` opens attach/tools, mic and send sit
  on the right, active modes are dismissible chips.
- **Sidebar** is New chat, Images / GPTs / Projects / Library, a collapsed More
  list, chats grouped Today / Yesterday / Previous 7 days, and an account footer.
- **Messages** drop the boxed cards. User turns are a soft bubble; assistant
  turns are plain text.
- **Marketing `/`** matches the same home (Ask anything + chips). Signed-in
  visitors go straight to `/chat`.
- Palette shifts to ChatGPT neutrals (`#212121` canvas, `#171717` rail,
  `#303030` composer) with a restrained brand green.

---

### 🔐 First-class Sign up and Sign in

Sign up and Sign in are now separate destinations instead of one `/login`
toggle that always opened on “Welcome back”.

- **`/signup`** creates an account. **`/login`** and **`/signin`** sign in.
- Landing hero, nav, and footer expose both actions. “Get started” no longer
  dumps a new visitor onto the sign-in form.
- Switching between the two keeps `?next=` so invite and deep links survive.
- Guests bounced from the app shell return to the page they asked for after
  auth. `next=` rejects protocol-relative URLs (`//evil.example`).
- After account deletion, `/login?deleted=1` confirms the wipe.

---

### 🖥 Hosted preview / iframe loads (PR #46)

`next dev` now accepts more preview hosts (`*.e2b.dev`, `*.arena.ai`,
`*.loca.lt` plus the existing tunnel origins) and sends
`Content-Security-Policy: frame-ancestors *` so Arena and other hosted
previews can load ChatMood inside an iframe instead of a blank frame.

---

## 2026-08-18

### 🌍 Global refresh + dependency error pass

The app shell now gets a subtle global surface refresh from the theme tokens:
ambient background gradients, consistent focus-visible rings, selection color,
mobile tap handling and native accent coloring apply across every route without
per-page patches. The web dependency lockfile was also refreshed to Next
`15.5.23` and PostCSS `8.5.26`, clearing the npm audit errors without taking a
breaking Next 16 upgrade.

### 🔐 Fix — sign-up works on access-code protected deployments

The email sign-up screen now includes the owner-provided **app access code**
field and sends it as `app_password` to `/auth/register`. Before this, any
deployment that enabled the sign-up gate could only return “requires an access
code” because the web and Flutter clients had no place to enter one.

Also tightened Flutter auth validation so the 8-character rule only blocks new
account creation, not sign-in to an existing account. Backend signup-gate tests
now cover missing, wrong, correct and closed-signup cases. Mobile `1.9.10+26`.

### 🩹 Fix — opening the deployed link showed a blank page

Two independent bugs, both of which produced an empty screen in a real browser
while everything looked fine locally.

- **The browser was told to call `localhost:8000`.** `NEXT_PUBLIC_API_URL`
  defaulted to `http://localhost:8000/api/v1`, and that default is *inlined into
  the client bundle at build time*. For any visitor, `localhost` is their own
  machine — so every call failed (and was blocked outright as mixed content on
  an https host), leaving the shell with no data. The base now falls back to the
  same-origin path `/api/v1`, which `next.config.mjs` rewrites onto
  `BACKEND_ORIGIN` (default `http://localhost:8000`). Deployments that already
  set `NEXT_PUBLIC_API_URL` are unaffected — the absolute URL still wins and the
  rewrite stays inert.
- **Netlify's SPA catch-all swallowed every route.** `/* → /index.html 200` was
  serving a file the App Router build never emits, so real routes resolved to
  nothing. Removed; the Next.js runtime owns routing, SSR and 404s.

Also fixed along the same seam: the voice WebSocket now derives `wss://` from
the page origin (a bare `/api/v1` is not a valid WS URL), the public film share
page separates its **server-side** fetch base from the **browser-facing** media
URLs it emits, and `next dev` accepts hosted preview origins
(`allowedDevOrigins`) so tunneled dev servers load their `/_next/*` assets.

Verified: production build contains no `localhost:8000` in any client chunk;
`/`, `/login`, `/chat`, `/voice` all render and `POST /api/v1/auth/login`
succeeds through the web origin.

---

## 2026-08-18

### 🤖 ChatGPT-parity pack — Custom GPTs, Study, archive, search, ratings, Continue

Nothing was removed. This pack adds the ChatGPT surfaces ChatMood was still
missing so the product can merge and deploy as a serious assistant, not a
thin Grok wrapper.

- **🤖 Custom GPTs.** `/gpts` is a real store: eight catalog assistants
  (Writing Coach, Code Reviewer, Interview Prep, Data Analyst, Study Tutor,
  Meeting Notes, Email Pro, Daily Pulse) plus private user-built GPTs with
  instructions, starters and knowledge files. `/chat?gpt=` starts a thread
  that keeps that brief on every turn.
- **📚 Study mode.** Socratic tutor on the model row, Settings, and Flutter
  drawer. Persists as `users.study_mode`; a turn can also send `study: true`.
- **📦 Archive.** Hide a chat from the live sidebar without deleting it.
  Restore from Archived. `conversations.archived`.
- **🔎 Full-text search.** The sidebar search now hits titles *and* message
  bodies (`GET /conversations/search?q=`).
- **👍👎 Ratings.** Thumbs on an assistant turn store `meta.feedback`.
- **▶️ Continue.** Grow the last answer in place — no extra user turn.
- **⎘ Duplicate + JSON export.** Fork a thread; download JSON or Markdown
  from the API. The existing client Markdown export stays.
- **🌅 Pulse, honestly.** Daily Pulse is a catalog GPT; **Schedule daily
  Pulse** creates a real 08:00 UTC task with live search. Not a fake
  always-on agent.

Migration `0030_chatgpt_parity` is existence-guarded. Tests:
`test_chatgpt_parity.py`. Mobile `1.9.9+25`.

### 😄 Grok-parity pack — Fun, temporary chats, editable memory, DeeperSearch, Canvas, math

ChatMood already had the Grok core. This pack closes the remaining *user-facing*
holes so a grok.com user can land here and not miss the daily controls.

- **😄 Fun mode.** One tap on the model row (also Settings + Flutter drawer).
  Persists as `users.fun_mode`; a turn can also send `fun: true`. The system
  prompt gets the Grok Fun voice — jokes and slang, facts stay true.
- **👻 Temporary chat.** Hidden from the sidebar, never written to memory or
  past-chat recall. `conversations.temporary`. You can still read the thread
  this session via its id.
- **✏️ Edit a memory.** Settings → a fact → Edit. `PATCH /memory/{id}`
  re-embeds and swaps the deterministic point id. Past-chat digests stay
  read-only.
- **🔭 DeeperSearch.** Research mode now has Deep (2×4) and Deeper (3×5)
  pills — the backend `depth` switch was already there; the UI never exposed it.
- **🖊 Canvas.** Long answers get an Open in Canvas control: a side workspace
  to edit, copy, download, or send back into the composer.
- **∑ KaTeX.** `$inline$` and `$$display$$` render in chat (remark-math +
  rehype-katex).

Migration `0029_grok_parity` is existence-guarded. Tests: `test_grok_parity.py`.

### 📱 Finish the chat on Flutter — edit, pin, follow-ups, media file_id (PR #43)

The last pass finished the *web* chat. The phone still treated a just-generated
image as a dead preview, had no way to rewind a mistyped turn, and listed
every chat in recency order with no pin. Same four holes, same contracts.

- **✏️ Edit & resend.** Tap Edit on your bubble, change the text, Save &
  resend. The client drops that turn and everything after it, then posts
  `edit_from` on `/chat/stream` (the only endpoint that honors a rewind —
  arena/agent paths are forced off so the old answer cannot linger). The
  `meta.user_message_id` is stored on the just-sent bubble so you can edit
  it without reloading the thread. Hidden in team workspaces: the API is
  owner-only.
- **📌 Pin / 🗑 delete in the drawer.** Personal chats get a pin (stays
  above recency, same `PATCH {pinned}` as the web sidebar) and a delete
  with a confirm. Team lists stay read-only.
- **💬 Suggested follow-ups.** After a text answer, up to three
  tap-to-send chips land above the composer from the `suggestions` SSE
  event. Cleared on send, new chat, and idle home-reset.
- **⬇✏️🗑 Media `file_id`.** The live `media` event and restored
  `meta.media` now carry the FileAsset id. Download goes through the
  stable `/files/{id}/download` route into the share sheet (hotlinks fall
  back to a plain GET). Edit prefills “Edit this image/video:”. Delete
  confirms, then `DELETE /files/{id}` and drops the card locally.

`mobile` version `1.9.8+24`.

### ✏️📌💬 Finish the chat — edit, pin, follow-ups, and a live media-id bug

The chat surface was one layer short of feeling finished. Four holes, one pass.

- **Download/edit/delete on a freshly generated image did nothing.** The
  backend already put `file_id` on the `media` SSE event (PR #24) but the
  web handler dropped it, so the manage buttons hid until you reloaded the
  thread. The type, the handler, and the media-flow test now all carry the
  id through.
- **✏️ Edit a user message.** Hover (or tap) Edit on your bubble, change
  the text, Save & resend. The server rewinds from that turn — that
  message and everything after it are deleted, then the new text is sent
  as a normal turn. Cross-tenant and assistant-id edits 404. The `meta`
  event now includes `user_message_id` so the just-sent bubble is
  editable without a reload.
- **💬 Suggested follow-ups.** After a text answer, three tap-to-send
  chips land above the composer (cheap model, 4s budget, fail-open, skipped
  in quota-economy). They never delay the last token.
- **📌 Pin a chat.** Sidebar pin keeps it above recency; unpin restores
  the old order. `PATCH /conversations/{id}` now accepts `{title}`,
  `{pinned}`, or both. Migration `0028_conversation_pins` is
  existence-guarded.
- **Upgrade CTA** from a plan-limit banner now goes to `/upgrade`, not
  Settings.
- **Vercel cache headers** so the HTML shell is `no-store` and hashed
  `/_next/static/*` assets stay immutable — the live site can no longer
  pin a stale layout after a successful deploy.

Tests: +8 in `tests/test_chat_finish.py`, plus a `file_id` /
`user_message_id` assertion on the existing image SSE contract.

---

## 2026-07-27

### 🔐 Sign-in page — autofill, labels, and a heading that isn't a duplicate

`/login` is the app's front door and the one page that bypasses `AppShell`, so
it missed conventions the rest of the app already follows.

- **Password managers couldn't fill it.** Not one input carried an
  `autocomplete` attribute, so browser/iOS/Android autofill had nothing to key
  off. Now `email`, `current-password` / `new-password` (mode-aware) and `name`
  — matching what Settings already does for its password fields.
- **No field had a `<label>`.** All three relied on placeholders, which vanish
  as soon as the user types and give voice control nothing to target
  (WCAG 3.3.2 / 2.5.3). Real `<label>`s now, `sr-only` so the compact look is
  unchanged.
- **Two `<h1>`s on one page.** At `lg` the marketing headline and the card
  heading both rendered. The headline lives in a `hidden lg:flex` section, so
  promoting *it* would leave no `<h1>` below `lg` — the card renders at every
  breakpoint, so it keeps the heading and the tagline became a `<p>`.
- **Failed sign-ins were silent.** The error `<p>` had no `role="alert"`, so a
  screen-reader user got no feedback that anything went wrong.
- **`minLength={8}` applied when signing in**, so an existing shorter password
  was blocked by the browser with a native tooltip that reads like the password
  is wrong. Now only enforced when creating an account.
- **`100vh` → `100dvh`.** iOS Safari counts the collapsible URL bar in `100vh`,
  so `min-h-screen` + `calc(100vh-4rem)` reserved more than the visible screen
  and pushed the submit button and Terms links below the fold on first paint.
  The rest of the app avoids raw `vh` via `.app-height` / `--app-h`; this page
  now opts into `dvh` directly.

Verified against a production build: exactly one `<h1>`, both `sr-only` labels
wired via `htmlFor`/`id`, `.sr-only` present in the emitted CSS, and no stray
`100vh` outside Next's own error page.

### 🏠 ChatGPT-style chat home — real centering, real heading, reachable starters

The empty chat home was already ChatGPT-shaped (greeting → composer → model row
→ starter pills); these are the fixes that make it behave like one.

- **It wasn't actually centered.** The block used
  `min-h-[calc(100dvh-11rem)]`, but it lives *inside* a flex column that has
  already subtracted the mobile header, the bottom tab bar and its own padding.
  One hardcoded `11rem` can't be right at every breakpoint: on desktop it
  over-subtracted (content floated high above dead space), and on a phone with
  safe-area insets it *under*-subtracted, so the min-height exceeded the box and
  the "centered" column overflowed into a scroll. It now centers with `flex-1`
  against the real remaining space, measured at every size.
- **The page had no `<h1>`.** On the empty home `headerCenter` replaces
  AppShell's mobile `<h1>`, leaving "What can I help with?" as an `<h2>` — the
  only heading on the page, at a skipped level, with nothing for a screen reader
  to anchor to. Promoted to `<h1>`.
- **Starter pills announced nothing useful.** Six buttons labelled "Help me
  write", "Make a plan"… with no indication they *prefill the composer*. Each
  now carries an `aria-label` naming the exact prompt it types, sourced from the
  same `prompt` string the composer receives, so the two can't drift. The group
  is a `<nav aria-label="Conversation starters">` (the label previously sat on a
  plain `<div>`, where it announced nothing), icons are `aria-hidden`, and the
  pills have a visible focus ring.
- **The stack lines up.** Starters were `max-w-2xl` under a `max-w-xl`
  composer — visibly wider than the input they feed. Greeting, composer, model
  row and starters now share one width token, which also softens the jump when
  the first message swaps in the conversation composer.
- **`prefers-reduced-motion` is respected.** `.mood-fade-up` wraps the chat
  surface and several premium cards and animated unconditionally; it's now
  disabled (element still visible) when the OS asks for reduced motion.
- Dropped a dead `Lightbulb` import.

Verified against a production build served locally: `/chat` returns the `<h1>`,
the `nav`, the per-pill aria labels and the flex chain; the old `100dvh-11rem`
calc is gone; `/`, `/chat`, `/images`, `/reel` and `/settings` all 200 with a
clean server log. `npm run typecheck` and `npm run build` pass.

> Note: PRs #22 and #27 also rewrite this same block, in conflicting directions
> (#22 keeps the pills, #27 deletes them). Both branch from before project mode,
> media edit/delete and `?c=`/`?billing=` deep-link handling landed, so merging
> #22 as-is would silently revert those. This change is built on current `main`
> and keeps all of them.

### 🚦 Health checks now detect a broken deploy (readiness ≠ liveness)

Every deployment probe — `fly.toml`, `render.yaml`, `docker-compose.yml` — gated
on `/healthz`, which returns 200 whenever the uvicorn process is alive. A machine
whose **database was unreachable kept a green health check while serving 500s**;
nothing in the platform noticed, and `frontend` in compose would start against a
half-wired backend.

The obvious fix — repoint the probes at `/readyz` — would have **taken production
down**. `/readyz` 503'd if *any* of postgres/redis/qdrant failed, and Fly
provisions no Redis (no `REDIS_URL` secret → the `redis://localhost:6379/0`
default → nothing listening). `/readyz` was already a permanent 503 in
production; gating on it would have failed every machine's check and stalled the
next rolling deploy.

- **Readiness now separates required from optional deps.** New
  `READINESS_REQUIRED` setting (default `postgres`). Only those deps can 503.
  Redis and the vector store are optional *by design* — the rate limiter fails
  open (`api/deps.py`) and memory/RAG degrade to "no recall" — so losing them
  reports `degraded` at 200 rather than pulling a still-serving machine.
- **Three states instead of two:** `ok` (200), `degraded` (200, optional dep
  down, still serving), `unready` (503, required dep down). Every check reports
  `status`, latency `ms`, and `required`, so an operator sees the degraded
  dependency instead of just a green light.
- **Probes repointed at `/readyz`** — Fly (timeout 5s → 10s, since a DB probe on
  a waking Neon compute needs more than a liveness budget), Render, and compose,
  which gates on all three because it actually runs all three and `frontend`
  waits on that healthcheck.
- **Smoke scripts** (`smoke.sh`, `live-smoke.sh`) treat `degraded` as a pass and
  say which dependency is down, instead of failing a healthy Fly deployment.
- **15 regression tests** (`backend/tests/test_readiness.py`) covering the state
  machine and the probe wiring — verified to fail against the old code, 9 of
  them including the Redis-down outage case. Suite: 641 passed, 0 regressions.

> ⚠️ **One follow-up needs a human.** The `deploy-fly` workflow's step summary
> still advertises `/healthz → {"ok":true}`, which no longer describes what the
> machine check watches. The Arena app token lacks GitHub's `workflows`
> permission, so that file is unchanged here. It is cosmetic — the summary text
> only, no deploy behaviour — but worth a one-line edit when convenient.

### 🚀 Redeployed the updated layout, and made "is it live?" answerable

The redesigned chat home layout was merged to `main`, but the last production
deploy predated it — so the live site was still serving the older build.

- **Re-triggered the production deploy.** `deploy-vercel-web` fires only on
  pushes touching `frontend/**`, and the app token is 403 on
  `workflow_dispatch`, so a real `frontend/` change is the way to ship. This
  push re-runs the `--prod` Vercel deploy against current `main`.
- **Build provenance in the served HTML.** The root layout now emits
  `<meta name="build-commit">`, baked in at build time from
  `VERCEL_GIT_COMMIT_SHA` (falling back to `GIT_COMMIT_SHA`, then `dev`
  locally). Until now there was no way to tell from outside whether production
  was running the merged commit or a stale build — exactly the ambiguity that
  hid this one. Verify with
  `curl -s https://<site>/ | grep build-commit`.
- **Verified before pushing:** `npm ci`, `npm run typecheck` and
  `npm run build` all clean against the current `frontend/` tree.

---

## 2026-07-26

### 🧪 The "sandbox-only" failures were mostly real bugs

The authenticated sweep reported 7 failures; six were initially dismissed as
environment noise. Re-examined properly, **three were genuine defects** that a
production Postgres deployment merely papers over.

- **`date_trunc` was registered on one engine, not all of them.** The sqlite
  compatibility shim bound to `engine.sync_engine` — the module-level engine
  alone. Every other engine (all 34 test fixtures, any script or self-hoster
  tool) silently lacked it, so `/admin/overview`, `/admin/users` and
  `/admin/analytics` raised `no such function: date_trunc` through any of them.
  Now registered on the `Engine` class so every sqlite connection gets it.
  (First attempt sniffed the connection's module and **broke the previously
  working path** — aiosqlite returns an `AsyncAdapt_*` wrapper, not a raw
  `sqlite3` object. Now duck-types on `create_function`.)
- **`GET /media/films/resumable` ignored the session it was handed.** It
  declares `db: AsyncSession = Depends(get_db)` and then called
  `resumable_orphans()`, which opens its own `SessionLocal()` — bypassing the
  caller's session, including `get_db` overrides, and querying the globally
  configured database rather than the one serving the request. The session is
  now threaded through; background callers keep the old default.
- **pgvector logged a fake outage.** `_ensure()` ran Postgres-only DDL on
  sqlite, retried it, and surfaced `syntax error near "EXTENSION"` twice —
  indistinguishable from a broken deployment, when it is really an
  unconfigured optional feature. It now fails fast naming the actual cause.
- **Confirmed genuinely correct:** `/memory` → 503 (verified it returns 200 the
  moment a store is reachable) and `/readyz` → 503 (that *is* the signal when
  Redis/Postgres are down).
- **Tests: +8** (626 total) in `tests/test_sandbox_parity.py`, each
  mutation-verified by reverting its fix. One pins the engine to sqlite rather
  than trusting the ambient `DATABASE_URL` — the settings default is Postgres,
  so a bare `pytest` run skipped the guard entirely and the test passed while
  proving nothing, a trap caught only by running the full suite.

### 🎨 Brand Kit app-icon download was a guaranteed 500 — fixed

A full A–Z re-verification (backend compile · 618 tests · web typecheck ·
production build · wiring gate · docs gate · authenticated runtime sweep) turned
up one **live production bug** the existing gates could not see.

- `GET /media/brand/icon` declared `size: int = Query(default=512,
  pattern="^(192|512)$")`. `pattern` is a **string** constraint; pydantic raises
  `TypeError` while *building* the validator, so the route returned **500 on
  every single request — including the default**, with no input that could
  succeed. The ⭐ "app icon" download in the Design studio had never worked.
- Fixed with an `IconSize(IntEnum)` (192 / 512). It keeps the original
  whitelist, **coerces the `"192"` string a real query string delivers**, and
  returns a clean 422 for anything else.
- **A near-miss worth recording:** the first fix used `Literal[192, 512]`. That
  passes static checks and the OpenAPI schema assertion, but `Literal` does
  **not** coerce — so every genuine `?size=192` request would have 422'd. Only
  driving a real authenticated request to actual PNG bytes exposed it.
- **Why no gate caught it:** the route is authenticated, so the unauthenticated
  sweep saw 401 and moved on. `check-wiring.mjs` verifies the path *exists*, not
  that it returns successfully.
- **Tests: +3** (618 total), each mutation-verified:
  - a **generic** scan flagging string-only constraints (`pattern` /
    `min_length` / `max_length`) on numeric params and the mirrored mistake —
    this whole bug class, not just one route;
  - a schema guard on the 192/512 whitelist;
  - an **end-to-end render test** that signs in, saves a Brand Kit and asserts
    real PNG bytes at both sizes — the only check that catches the `Literal`
    trap.
  - Two bugs in the guards themselves were found and fixed while validating
    them: constraints live in pydantic's `.metadata` (not attributes), and
    `app.routes` only exposes 3 of 153 routes because routers mount as
    `_IncludedRouter` wrappers. Both made the scan silently pass everything.

### ⬇✏️🗑 Generated images & videos are downloadable, editable and deletable

Every generation was already archived as a `FileAsset` — but the id was thrown
away, so the client only ever held a **presigned URL that expires after 7 days**
(`IMAGE_PERSIST_TTL_S`). Download quietly rotted, and there was no way to delete
a generation at all.

- `_persist_generated_media()` now returns `(url, stored, file_id)`, and that id
  reaches the client on the SSE media event and `POST /chat/image`.
- **⬇ Download** uses the stable `GET /files/{id}/download` route instead of the
  expiring render link. Implemented via `lib/download.ts`, not `<a download>`:
  the route is cross-origin and Bearer-authenticated, so an anchor would 401 or
  silently navigate instead of saving. Blob-fetch + synthetic click gives a real
  file with a prompt-derived name, and falls back to a new tab if CORS blocks it.
- **✏️ Edit** prefills the composer (chat) or reloads the prompt (studio),
  routing through the existing media-refine intent.
- **🗑 Delete** calls `DELETE /files/{id}` — row, bytes and vector chunks — and
  drops the card locally so the thread matches reality without a reload.
- Available on chat media cards, Images studio tiles, the lightbox, and video
  cards. Gallery tiles were restructured from `<button>` to `<div>` because
  nesting the new action buttons inside one is invalid HTML and breaks keyboard
  focus order.
- **Fail-open preserved:** when archiving fails, `file_id` is `""`, the
  generation still renders, and the UI hides the manage actions rather than
  showing buttons that 404.
- **Tests: +8** (615 total). Ownership is enforced — a second account gets 404 on
  both download and delete. Mutation-tested: discarding the `file_id` fails 6
  tests, and dropping the ownership check fails the cross-tenant test.

### ✅ A–Z wiring audit — two live 500s fixed, Play Store readiness

Audited every interactive control (344 `onClick`/`href` sites, 57 distinct API
calls) and the Android release path. Guide: [docs/QA-AUDIT.md](docs/QA-AUDIT.md).

- **Two production 500s found and fixed.** Both only fire when a real request
  reaches the line, so unit tests never saw them:
  - `settings.MODELS_VIDEO` (4 references) — that setting never existed; it's
    `MODEL_VIDEO`. `POST /media/videos/grok` and `GET /media/videos/grok-info`
    raised `AttributeError`.
  - `NEGATIVE_DEFAULT` was used in `routes/media.py` but never imported —
    `NameError` on `grok-info`, hidden *behind* the first bug until it was fixed.
- **`scripts/check-wiring.mjs` — an offline gate against dead buttons.** Verifies
  every `apiFetch` path against the live FastAPI route table (expanding
  `${cond ? "a" : "b"}` so both branches are checked, not waved through), every
  internal `href` against the Next.js route tree, and flags any `<button>` with
  no handler. Validated by injecting all three bug classes and confirming each is
  caught. Currently: 67 files · 23 pages · 153 API routes · **0 problems**.
- **`tests/test_wiring_audit.py`** scans every route module for undefined
  `settings.*` attributes and undefined module constants — the two classes above.
  Re-introducing either bug fails the suite (verified).
- **Runtime sweep:** 39 signed-in + admin surfaces all return 200; unauthenticated
  requests correctly 401 and non-admins correctly 403. The three 503s in a bare
  sandbox (`/readyz`, `/memory`, `/media/films/resumable`) are correct-by-design —
  they need Redis/Qdrant or the app's own session factory.
- **📱 Play Store: `POST_NOTIFICATIONS` was missing from the manifest.** Since
  Android 13 it's a runtime permission — `requestPermission()` was being called,
  but with nothing declared the dialog never appeared and **every push was
  dropped silently**. `scripts/android-manifest-perms.py` now owns the permission
  set with per-permission justifications for the reviewer, and is idempotent
  (`android/` is regenerated by `flutter create` each CI run).
  ⚠️ The one-line workflow edit that calls it **could not be pushed** — this
  session's GitHub App lacks `workflows` permission. See QA-AUDIT.md.
- Confirmed already compliant: AAB output, `targetSdk 36`, R8 + obfuscation,
  in-app account deletion, public privacy/terms URLs, store assets. Remaining
  pre-submission items (incl. **Google Play Billing** if you ever sell inside the
  Android app — MoMo is fine on web, not in-app) are checklisted in the guide.

### ⭐🔴 Creator Pro + Go Live on the Reel

The Reel gets a paywall and real live broadcasting.
Guide: [docs/REEL-PREMIUM.md](docs/REEL-PREMIUM.md).

- **Creator Pro** — free: watermarked 720p, 60s/60MB clips, basic effects. Pro:
  watermark-free **1080p**, **3-minute/100MB** uploads, the cinematic
  **Noir/Dream/Vintage** grades, analytics and Go Live. Posting and duets stay
  free deliberately — a feed nobody can post to is worth nothing, so the paywall
  sells polish and reach, not access.
- **One entitlement source.** Every gate resolves through
  `reel_premium.entitlements()`, and the UI renders its padlocks from that same
  payload (`GET /reels/premium`) — a lock can't claim something the server
  doesn't enforce, and a perk can't silently stop applying. Blocked actions
  return **402** with actionable copy, never a bare 403. Admins are premium;
  future tiers are premium by default.
- **Reels now respect the watermark.** They previously bypassed it entirely — a
  real revenue gap, since the Reel is the most public surface in the product.
- **🔴 Go Live.** A broadcast *is* a reel row (`kind="live"`): it floats to the
  top of the feed while streaming and becomes a replay when ended, so viewers
  keep the post they were watching. One broadcast at a time, owner-only
  teardown, and a concurrent-viewer counter that tracks peak and can't go
  negative.
- **Security: the stream key never leaves the owner.** It's a *write* credential
  — anyone holding it could broadcast as that creator — so it's returned exactly
  once by `/live/start`, and `LiveTarget.as_viewer_dict()` exists so the feed
  payload physically cannot carry it. A test asserts it never appears in a feed
  response.
- **Provider-agnostic, honest about infra.** This repo doesn't host video;
  `services/live_stream.py` adapts Mux / Cloudflare Stream / LiveKit behind one
  normalized shape, so swapping is an env change. With no provider configured it
  **raises rather than inventing a URL** — a Pro creator sees "Go Live isn't
  switched on yet" (503) instead of a Start button that does nothing.
  Entitlement and infrastructure are tracked separately for exactly that reason.
  ⚠️ Managed streaming bills per minute; `LIVE_MAX_MINUTES` caps runaways.
- Config: `LIVE_PROVIDER`, `MUX_*`, `CLOUDFLARE_STREAM_*`, `LIVEKIT_*`.
  Migration `0027_reel_live_premium`.
- **Tests: +34** (604 total, all passing). One existing test correctly caught the
  upload cap becoming plan-aware and was updated. Both security guards were
  mutation-tested: leaking the stream key into the feed, and dropping the Go Live
  paywall, each fail the suite.

### 💳 Payments — manual mobile money, admin-verified

Revenue can start **today**, with no gateway contract: the admin publishes a MoMo
number, the user pays and submits their transaction ID, the owner verifies it in
the panel, and the plan activates. Guide: [docs/PAYMENTS.md](docs/PAYMENTS.md).

- **Admin console** (owner panel → 💳 Payments): publish MoMo / bank / cash
  destinations with payer instructions, review a queue showing payer email +
  amount + reference + phone (everything needed to match a MoMo alert), and
  approve or reject with a reason the user sees. Plus a **direct grant** for comps
  and refund fixes, which still writes a zero-amount `approved` row so the audit
  trail always explains why an account is Pro.
- **User flow** (`/upgrade`): pick monthly or yearly, copy the number, pay, paste
  the transaction ID. The page polls while an admin confirms. Settings' *Upgrade
  to Pro* now falls through to this page instead of dead-ending on a Stripe 503.
- **Rules that protect the money** — each one is a way to lose money if missed:
  submitting **never** grants a plan (only admin approval does, or anyone could
  self-upgrade with a made-up reference) · approval is **idempotent** (a
  double-clicked Approve must not hand out two months) · a reference can be
  claimed **once**, compared after normalization because refs get retyped off a
  phone screen · **one** pending payment per user · periods **extend** rather than
  reset, so renewing early never discards paid days · amounts are integer minor
  units (`1.15 × 100 = 114.999…` in float — money never touches floats).
- **Expiry sweep.** Gateways fire a webhook when a period ends; MoMo has nobody to
  fire anything, so a background loop returns lapsed accounts to free — otherwise
  one month of MoMo would grant Pro forever. Stripe-managed subscriptions are
  skipped (its webhook owns that lifecycle). Visible on `/healthz`.
- **Gateways are declared, not hidden.** Paystack, Flutterwave and Stripe appear
  in the provider list as "needs key" until configured, and `default_provider()`
  switches to an automatic gateway the moment one is wired. They write the same
  `Payment` row, so nothing downstream changes when they're switched on.
- Config: `CURRENCY`, `PRO_PRICE_MONTHLY_MINOR`, `PRO_YEAR_MONTHS` (yearly is
  *derived* from monthly, so the discount can't drift), `MANUAL_PAYMENTS_ENABLED`,
  `PAYSTACK_*`, `FLUTTERWAVE_*`. Migration `0026_payments`.
- **Tests: +39** (570 total, all passing). Three money-critical mutations were
  verified to fail the suite: removing the idempotency guard, making renewal reset
  instead of extend, and letting a user's own submission self-approve (10 tests).

### 🏷 Rebrand: Mood AI → **ChatMood**

The product is now **ChatMood** ("Smart conversations. Real connections."), since the
`moodai` domain wasn't available at the registrar.

- **Renamed everywhere users can see it** — app name, page titles & metadata, PWA
  manifest, OG/Twitter cards, legal pages, the assistant's own persona ("You are
  ChatMood…"), in-chat creation labels (ChatMood Canvas / ChatMood Reel), plugin
  runner, push copy, mobile strings, watermark text, and all 20 docs. `APP_NAME`
  now defaults to `ChatMood`, so the free-tier badge reads "Made with ChatMood"
  automatically.
- **Deliberately NOT renamed — these are wire identifiers, not branding.** Changing
  them would be a silent breaking change with zero brand benefit:
  | Identifier | Why it stays |
  | --- | --- |
  | `mood_token`, `mood_theme` | localStorage keys — renaming logs out every existing user |
  | `X-Mood-Host` | request header the per-domain analytics middleware reads |
  | `mood-flagship` / `-fast` / `-mini` / `-code` | **public API model aliases** shipped as *stable*; renaming breaks every customer integration |
  | `mood-gen-*` filenames | already-stored assets would become unreachable |
  | `mood_ai_mobile`, `ai.mood` | Dart package id + Android `applicationId` — the appId is permanent once published to Play |
  | postgres `mood` db/user, `joesoft3/moodai` | infrastructure, not product identity |
- If the public API aliases should become `chatmood-*`, the safe path is adding them
  **alongside** the existing ones rather than replacing them — happy to do that on request.
- Verified live: `/healthz` reports ChatMood, `X-Mood-Host` still returns 200, and the
  API aliases still resolve. 512 tests pass (two correctly caught the user-visible
  label rename and were updated).

### 🏷 Free-tier watermarking (Pro & admins render clean)

Generated output on the free plan now carries a subtle "Made with ChatMood" badge.
Paid plans and admins are unaffected. Guide: [docs/WATERMARKING.md](docs/WATERMARKING.md).

- **One entitlement rule, one place** (`services/watermark.should_watermark()`), because
  the two failure modes cost real money in opposite directions: a badge on a paying
  customer's export is a refund request, and a missing badge on free output is lost
  conversion. Paid detection is a **denylist of one** (`plan != "free"`) so any future
  tier is exempt by default — the safe direction to be wrong in. Admins
  (`is_admin` **or** an `ADMIN_EMAILS` entry) render clean even on the free plan, so
  owner demos and store screenshots need no plan juggling.
- **Applied across every creation surface** — 🎨 Design Studio (web *and* print tiers),
  🎬 storyboard films (film + poster), ✂️ Auto-Edit clips, and 💬 in-chat image/video,
  which is stamped at the single `_persist_generated_media()` chokepoint.
- **Stamped at render time, not download.** Design exports are cached by filename with
  no entitlement in the key, so badging at delivery would mean re-deriving entitlement
  on four separate download paths *or* serving a stale artifact after an upgrade. Baking
  it into the source render means every downstream path inherits it and there is no
  cache to invalidate. Films additionally **persist** the decision, so a render resumed
  after a restart re-applies the original one instead of half-badging a film whose owner
  upgraded mid-render.
- **Pillow draws the badge, ffmpeg composites it.** Not `drawtext` — this codebase
  already documents that the shipped ffmpeg build lacks it and serverless images ship no
  fonts. Rasterizing once to a transparent PNG means the same asset overlays onto both
  stills and video via a filter every build supports. The badge scales with output width
  (so it neither dominates a reel nor vanishes on a 4000px print export) and is cached
  per width bucket.
- **Fail-open by construction.** Missing ffmpeg, missing font, failed encode, timeout or
  corrupt bytes all return the original file/bytes untouched; the swap is atomic and
  scratch files are cleaned up. Losing a badge is acceptable; losing a paid-for render
  is not.
- Config: `WATERMARK_ENABLED` · `WATERMARK_TEXT` (white-label) · `WATERMARK_TIMEOUT_S`.
  Migration `0025_watermark_flags` adds `designs.watermarked` / `films.watermarked`
  (guarded, re-runnable, verified up→down→up).
- **Tests: +29** (512 total, all passing) covering entitlement in both directions,
  future-tier safety, env-listed owners, fail-safe behavior when the admin lookup throws,
  badge rendering/scaling, the argv builders (video re-encodes but copies audio), the
  bytes path incl. JPEG targets, fail-open paths, and wiring through the design, film and
  in-chat routes. Both regression directions were confirmed by mutation testing —
  breaking the paid exemption fails 6 tests; disabling free-tier badging fails 6.

### ⏰🗂🔑 Scheduled tasks · Projects · OpenAI-compatible developer API

Three Grok-parity surfaces that turn Mood from *something you ask* into *something
that works for you*. Full guide: [docs/TASKS-PROJECTS-API.md](docs/TASKS-PROJECTS-API.md).

- **⏰ Scheduled tasks (`/tasks`).** Save a prompt once and Mood runs it unattended —
  `once` / `hourly` / `daily` / `weekly` (weekday mask), all in UTC with the local
  equivalent shown as you pick. A task runs through `chat`, `deepsearch` or `agent`
  mode, appends its answer to a dedicated conversation (so a recurring task reads as
  one growing briefing thread rather than littering the sidebar), and pushes a
  notification. **Run now** tests a task *without* consuming its next scheduled slot.
  - Correctness by construction: due tasks are **claimed atomically**
    (`UPDATE … WHERE last_status != 'running'`), so multiple Fly machines can never
    double-run one; `next_run_at` advances **at claim time**, so a crash mid-run
    resumes on the next slot instead of hot-looping on an overdue row; runs are capped
    by `SCHEDULER_RUN_TIMEOUT_S` and metered as `task` usage events; a failing task
    records the error, keeps its schedule, and never kills the loop.
  - Schedule arithmetic is **cron-free and pure** (`services/schedule.py`) — four
    shapes cover the product, and being I/O-free is what makes it testable without a
    clock. `/healthz` now reports scheduler state for operators.
- **🗂 Projects (`/projects`).** Durable containers for work spanning many chats: a
  **standing brief** plus **pinned documents** that every chat inside inherits, on
  every turn. Project context is injected directly after the persona so it outranks
  memory, recall and doc-RAG; budgets are bounded so a long-lived project can't push
  the actual conversation out of the window; the whole path is fail-open. Injection
  keys off the *conversation's* project, so a filed chat keeps its brief forever, not
  just on the turn that created it. **Deleting a project deletes nothing real** — its
  chats and uploads simply unfile.
- **🔑 Developer API (`/api/v1/public`).** OpenAI-compatible, so `openai-python`, the
  Vercel AI SDK, LangChain and existing curl snippets work by changing two strings.
  `/chat/completions` (streaming `chat.completion.chunk` frames + `[DONE]`),
  `/search` (grounded answer + structured citations), `/images`, `/models`, `/usage`.
  Stable `mood-*` aliases decouple callers from the backing models, and an unknown
  alias falls back to the flagship rather than breaking a pinned integration.
  - Keys are `mk_live_…`, stored as **SHA-256 only** — the plaintext appears exactly
    once, in the response that mints it. Scoped (`chat`/`search`/`images`),
    per-key rate-limited, soft-revocable (immediate, but the audit row survives).
    Session JWTs are rejected on the developer surface and vice-versa, so revoking a
    key genuinely revokes that integration. Every call meters as an `api` event and
    counts against the same plan and dashboard.
- **Plumbing.** Migration `0024_projects_tasks_keys` (existence-guarded, re-runnable,
  verified up → down → up); `conversations.project_id`; `task`/`api` meters added to
  both plan tiers; Tasks + Projects in the app nav; the API-key manager in Settings;
  `/chat?project=…` and `/chat?c=…` deep links.
- **Fixed along the way:** the `?billing=` cleanup in chat rewrote the URL with only
  `?ws=`, silently discarding every other query param — it now preserves them, which
  is what makes the new `?project=` / `?c=` deep links survive a Stripe return.
- **Tests: +62** (482 total, all passing) covering schedule arithmetic and DST-free
  UTC edges, the atomic claim under a simulated race, unattended run/failure/metering
  paths, project context injection and non-destructive deletion, cross-tenant access
  on every new route, key hashing/scope enforcement/revocation, and the OpenAI
  envelope + streaming frame shapes.

### 📚 Docs index + automated housekeeping gate (PR #21)

- **`docs/README.md` — a real documentation index.** All 33 guides in `docs/` are now
  listed in one place, grouped by task (start here · hosting & infra · domains &
  white-label · product surfaces · mobile & store release · auth/policy/compliance ·
  testing & ops), each with a one-line description of what it actually covers. Previously
  the only way to find a guide was to `ls docs/` and guess from the filename.
- **`scripts/check-docs.mjs` — offline, dependency-free docs gate.** Verifies that (1)
  every relative markdown link resolves to a file that exists, (2) every `#anchor`
  exists as a heading in its target document, (3) no guide in `docs/` is orphaned from
  the index, and (4) every guide opens with a level-1 `# Title`. Fenced and inline code
  are stripped first, so illustrative snippets like `[n](url)` in ARCHITECTURE.md don't
  trip it. Failures are grouped per file with an actionable message.
- **Ready to wire into CI as a third `test.yml` job** alongside `backend-unit` and
  `web-typecheck` — the copy-paste job block lives in [docs/README.md](docs/README.md#wiring-the-gate-into-ci).
  (Not applied in this PR: the automation that opened it cannot write to
  `.github/workflows/`.) The check never fetches external URLs, so it cannot flake
  on a third-party outage.
- **README:** links the new index from the intro and the repo map, and adds a
  **"Checks to run before opening a PR"** table mapping each CI job to its local
  command (`pytest backend/tests -q`, `npm run typecheck`, `node scripts/check-docs.mjs`).
- Docs/CI only — no application, API or schema changes.

---

## 2026-07-25

### 🎵 TikTok-style Reel polish (PR #20)

- **TikTok-style interactions on the existing full-bleed vertical snap feed** (the feed itself
  shipped in PR #18): creator **avatar + red follow "+" badge** atop the action rail (local-only,
  `localStorage`-persisted follow set), **double-tap-to-like** with a heart that bursts where you
  tapped (single tap still pauses; 240 ms disambiguation; double-tap never unlikes), a **spinning
  vinyl music disc** in the bottom-right corner, a scrolling **"♪ original sound — @author"**
  marquee under the caption, and **TikTok-style underline top tabs** (For you / Saved / My reels).
- Frontend-only (`frontend/app/reel/page.tsx`) — no backend/API/schema changes; `npm run verify`
  (typecheck + build) green.

### 📺 Creator Reel (merged from PR #16)

- **`/reel` creator feed** — one shared public feed: full-bleed vertical snap, one reel per
  screen, `IntersectionObserver`-gated autoplay (only the on-screen reel decodes), optimistic
  likes reconciled against the server, once-per-card views, *For you* + *My reels* tabs.
- **Two ways in** — upload your own clip, or share a finished film / in-chat generation
  (nothing copied; shares only accept media this deployment serves — hotlinks rejected).
- **🎞 Reel editor** — record or add clips, timeline with duplicate/split/reorder, overlay
  text, effects (CSS-accurate previews of the ffmpeg chain), auto-captions, then publish in
  one ffmpeg pass; **_r/_rp files are deliberately outside the media janitor's sweep patterns,
  so reels survive the 24h TTL** that purges ephemeral films.
- **Duet, effects, repost & social share sheet**, view/like counters, saved tab and
  per-reel stats; backend schema in migrations `0021_reels` → `0023_reel_studio`.
- **🖨 Print-grade graphics (Design Studio)** — sticker kind with die-cut transparency,
  per-kind DPI/print sizes, export presets filtered to what each design actually rendered.
- 🛠 Also merges PR #16's reliability work: backend pytest gate restored, cascade-attempt
  count read live from settings, terminal reel progress uses the canonical `{stage, done,
  total}` completion contract.

### 👁 Reel button visibility fixes (this branch, on top of #16)

- **Mobile bottom tab bar dropped the Reel button** — the phone bar renders `NAV.slice(0, 5)`
  and PR #16 inserted Reel at index 5, so on phones it was drawer-only. Reel now sits in the
  first five (Chat · Voice · Images · **Reel** · Films); a code comment guards the ordering.
- **The chat Reel tab vanished in conversations** — Ask/Imagine/Reel only rendered on the
  empty-chat home, so the moment a conversation opened there was no Reel entry anywhere on
  screen. The conversation toolbar pill now carries **Reel** too (all viewport sizes).


### 🎬 Landing & onboarding

- **Ambient video hero on the home page** — seamless 8-second procedural video loop
  (`frontend/public/hero-ambient.mp4`, 195 KB, H.264) in the Arena leather/teal palette,
  instant-paint JPEG poster, and `prefers-reduced-motion` support (loop pauses, poster stays). (#15)
- **Sticky `LandingNav` with an accessible Explore dropdown** — outside-click + Escape close,
  ↑/↓ arrow-key navigation, `aria-haspopup`/`aria-expanded` semantics — linking Chat,
  Deep Research, Films, Images, Design and Voice. (#15)
- **Calmer landing structure** — full-viewport video hero melting into the page background,
  trimmed 6-card feature grid, same 3-steps + Android sections. (#15)

### 🛡 Reliability & ops

- **Atomic Redis rate limiter** — the old `INCR` + `EXPIRE` pipeline could leave keys without
  an expiry after a crash, permanently throttling users. Replaced with a single **Lua script**
  so increment and expiry happen atomically. All rate-limit paths (chat, picker, videos,
  battles, invites, exports) now ride it. (#14)
- **React `ErrorBoundary`** — a render/runtime fault anywhere in the app shell now shows a
  polished recovery UI (icon, message, "Try again") instead of a blank page; sidebar, tab bar
  and navigation survive. Wrapped around every page's content in `AppShell`, plus the landing
  hero/nav. (#14, #15)
- **Structured `/readyz`** — readiness now returns JSON with per-dependency latency in ms,
  version, and timestamp for ops dashboards and monitoring. (#14)
- **Docker Compose health checks** — `qdrant`, `backend` and `frontend` health checks with
  condition-based `depends_on` (`service_healthy`) so services start in order without races. (#14)

### 📜 Scrolling, layout & hit-testing (site-wide fix)

Audited every screen at 320–1600px in headless Chromium, asserting on computed layout and
`elementFromPoint` hit-testing: (#17)

- **Restored window scrolling on all public pages** — `html, body { height: 100% }` +
  `overflow-x: hidden` on both elements turned `<body>` into a fixed-height scroller, so
  End/PageDown/Space, `scrollIntoView()`, `#anchor` links and scroll restoration did nothing
  and /terms /privacy footer links were unreachable. Now `min-height` + `overflow-x` on
  `<html>` only.
- **Design Studio and Research got real scrollports** — both rendered ~1700px of content into
  an 844px box with no way to reach the rest (Generate design, Brand Kit, Batch studio,
  Client links were permanently off-screen). Both now own a `flex-1 min-h-0 overflow-y-auto`
  scrollport; `/plugins` received the missing `min-h-0` too.
- **Freed trapped sidebar buttons** — at viewport heights ≤720px the shrunken history list
  painted its “New chat” button *under* the nav block: visible but impossible to click.
- **Voice analyzer no longer overlaps the live transcript** — closed `<details>` panels are
  now collapsed outright instead of keeping a measured box on top of the transcript.
- **Touch targets** — footer/legal/auth links (13–16px) and Design checkboxes (13px) grew to
  comfortable tap sizes.

### ✨ Chat experience refinements (#2–#5, #9–#12)

- **Focused Ask / Imagine chat home** — the empty chat surface is now a minimal composer with
  three clean starter actions; the full conversation composer and controls return once a chat
  starts. (#2)
- **Home action fixes** — cursor lands at the end of prefilled drafts, “Research a topic”
  visibly enters research mode with a prefilled prompt, plus a clear research-mode control and
  contextual placeholder in the minimal composer. (#3)
- **Calmer chat recovery** — disruptive connection alerts became inline dismissible notices;
  safe read requests auto-retry while the backend wakes from idle; “Chat” always opens a clean
  new-chat surface while explicit history/library selection is preserved; the ChatMood mark sits
  centered on the empty chat home. (#5)
- **Clean conversation header** — removed the redundant Live/Chat/Auto/message-count status row,
  the auto-saved subtitle, and the extra Ask tab marker so conversation text flows. (#9)
- **Anchored streaming answers** — each new answer pins its start and grows top-to-bottom
  instead of chasing the last streamed line on every delta. (#10)
- **Focused assistant screen experiment** — a chrome-free `/assistant` route was tried (#11)
  and reverted (#12) after review; the integrated chat surface remains the single home.

### 🎨 Mobile & voice polish (#4, #6–#8)

- **Arena warm paper/leather palette across the app** — replaced blue-gray surfaces, borders
  and text ramps; typed composer text explicitly inherits the theme foreground so it stays
  visible. (#6)
- **Roomier mobile composer** — bigger touch area and textarea; Agent, Deep, Plugins and Voice
  collapsed into one compact “More tools” menu; redundant tool-chip/status rows removed. (#4)
- **Voice Studio mobile layout** — content scrolls independently without overflowing into the
  bottom navigation, and the live transcript sits in a bounded scroll region that can't cover
  the orb, analysis panel, or navigation. (#7)
- **Simplified Voice mobile chrome** — header bar removed (menu button stays in its safe-area
  position), and the analyzer's default disclosure triangle is gone. (#8)

## 2026-07-24

### 🔧 Platform hardening (#1)

- Stabilized the frontend build/typecheck flow (Next dynamic-route typing for public/shared
  pages, route-aware typecheck, production build verification) and cleared current dependency
  audit findings.
- **Cloudflare-assisted custom-domain setup** with provider-readiness visibility for
  registrars/DNS.
- **Brain routing observability** for text/image/video plus image-generation fallback
  behavior.
- SEO crawl controls and a **5boost.me cutover runbook + checker**
  ([docs/5BOOST-ME-CUTOVER.md](docs/5BOOST-ME-CUTOVER.md)).

---

## Earlier foundation (pre-PR baseline)

The initial scaffold already shipped: streaming Grok chat with Live Search grounding,
long-term memory with cross-chat recall (Qdrant), document & media analysis, image
generation, realtime voice sessions (WebSocket with barge-in + sentence-chunked TTS),
multi-agent mode, ⚔️ Arena multi-model debates with rematches and white-label arenas,
Think mode, DeepSearch, Gmail/Calendar/GitHub plugins with human-in-the-loop approvals,
team workspaces, custom domains (DNS-verified + registrar purchases with Stripe renewals),
domain analytics, owner panel, plan-aware Pro perks, one-env LLM failover, pluggable
R2/local/Docker file storage, the professional 🎬 video studio with 🎙 Cinema Sound and
🎞 Storyboard films, auto-deploy workflows (Vercel/Netlify/Fly), and the Flutter mobile
client — see the [README](README.md) feature list for the full surface.
