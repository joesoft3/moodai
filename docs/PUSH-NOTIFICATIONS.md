# 🔔 Push Notifications — blueprint (FCM, CI-ready)

> **Status: Phase 1 backend ✅ + Phase 2 mobile code ✅ shipped** — the app registers devices,
> shows foreground banners, and asks permission in-context. CI injects `google-services.json`
> + the gms plugins **only when** the `FCM_GOOGLE_SERVICES_JSON` secret exists (default builds
> unaffected). **Remaining: 5 console clicks** below — no more code needed.
>
> 1. 🖱 [console.firebase.google.com](https://console.firebase.google.com) → **Add project** → `mood-ai` (Analytics off is fine).
> 2. 🖱 **Add Android app** → package **`ai.mood`** (must match the build's applicationId) → register.
> 3. 🖱 Download **`google-services.json`** → GitHub repo → *Settings → Secrets and variables → Actions* →
>    **`FCM_GOOGLE_SERVICES_JSON`** = the whole JSON, one line.
> 4. 🖱 Firebase → *Project settings → Service accounts → Generate new private key* → Railway *moodai* → Variables:
>    `FCM_PROJECT_ID` = `<project-id>` · `FCM_SERVICE_ACCOUNT_JSON` = entire JSON one line.
> 5. 🖱 Tag any `v*` (or re-run mobile-apk with your API URL) → install → stage a Gmail action →
>    **“✋ Approval needed” buzzes your phone**; an arena verdict push follows on your next debate.

## What gets a push (MVP set)

| Moment | Title | Body | Tap → opens |
|---|---|---|---|
| Staged action waiting | ✋ Approval needed | “Send email: Q3 launch…” | 🧩 Action inbox (/plugins) |
| ⚔️ Arena finished | verdict in | “Grok-4 verdict: Draft C wins 7-5” | the conversation |
| Team mention (later) | @you in Team Mood | first 80 chars | workspace chat |

## Architecture

```
Flutter app ──(FCM token)──▶ POST /api/v1/devices  ──▶ devices table (user_id, token, platform)
                                                        │
backend events (action_staged, verdict) ──▶ services/notify.py ──▶ FCM HTTP v1 (service-account)
                                                        └── prunes dead tokens on 404/410
```

- **FCM HTTP v1** (not legacy keys): one service account JSON, `oauth2` token cached 50 min,
  `POST https://fcm.googleapis.com/v1/projects/<project>/messages:send`.
- **Android 13+**: ask `POST_NOTIFICATIONS` at first open, in-context (not at splash).
- **flutter_local_notifications** for foreground display; `firebase_messaging` for tokens/data taps.

## Phases

**Phase 1 — backend (≈1 day)**
- migration `0011_devices` (`devices` table), `POST /devices` (upsert), `DELETE /devices`
- `services/notify.py`: `send_to_user(user_id, title, body, data)` + cooldown per type
- hooks: plugins staging (after stage), arena verdict event → notify
- config: `FCM_PROJECT_ID`, `FCM_SERVICE_ACCOUNT_JSON` (whole JSON as env secret)

**Phase 2 — mobile (≈1 day)**
- create Firebase project `ai.mood` → download `google-services.json`
- CI secret `FCM_GOOGLE_SERVICES_JSON` → workflow writes `mobile/android/app/google-services.json`
  before the build (never committed)
- deps: `firebase_core`, `firebase_messaging`, `flutter_local_notifications` → small
  `lib/push.dart`: init, permission, token upload, tap routing → `chat_screen` deep-link

**Phase 3 — web (later)**: FCM web or VAPID web-push; the Service Worker already ships with the PWA shell.

## Secrets & CI wiring (when you do Phase 1/2)

| GitHub/ Railway secret | Holds |
|---|---|
| `FCM_SERVICE_ACCOUNT_JSON` (backend env) | full service-account JSON (server sender) |
| `FCM_PROJECT_ID` (backend env) | e.g. `mood-ai-push` |
| `FCM_GOOGLE_SERVICES_JSON` (repo secret, mobile build) | `android/app/google-services.json` content |

The mobile-apk workflow already scaffolds `android/` — Phase 2 adds 3 lines there,
mirroring the existing manifest-patch pattern.

## Costs & risks

FCM is free (generous). Risks are: dead-token churn (prune on send errors), notification fatigue
(cooldowns + a Settings → Notifications matrix), and privacy (push bodies carry no message
content for admins' visibility — payloads say *what kind*, the app loads the *what* after auth).

**Next step when ready:** say “build push Phase 1” and I’ll land the migration, endpoints,
and sender in one PR-sized push.
