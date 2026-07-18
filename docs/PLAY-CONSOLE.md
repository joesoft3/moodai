# 🏪 Play Console — listing pack for Mood AI

Everything below is copy-paste ready. The **build artifacts** already exist:
`app-release.aab` on the [v0.2.0 release](https://github.com/joesoft3/moodai/releases/tag/v0.2.0)
(dev-signed until you set the `MOOD_UPLOAD_*` secrets — Play *requires* your own upload key for
production uploads; then Play App Signing covers the app key).

## Listing copy

| Field | Text |
|---|---|
| **App name** | Mood AI |
| **Short description** (80) | AI super-app: chat, ⚔ Arena debates, 🎬 video with AI voice & sound. |
| **Full description** | below |

```
Mood AI is a Grok-class AI super-app — and now it directs films. Every major model competes
for your attention, and it always shows its work.

🎬 VIDEO STUDIO WITH CINEMA SOUND — type an idea, get a finished video: AI-written voiceover
in 10 studio voices, a cinematic ambient mix, and loudness-polished audio. Storyboard mode
splits your idea into 2–4 directed scenes, stitches them into one continuous film, and burns
subtitles in on request.

⚔️ ARENA — send one question, watch S1 Mood-4, GPT and Gemini draft answers in parallel, vote
on each other's work blind, then get a judge verdict with accuracy & clarity score cards.
Losers' drafts are re-challengeable with one tap.

🧠 THINK MODE — open the purple panel and watch the model reason (live thinking traces +
a 2-line digest) before the final answer.

🔭 DEEP SEARCH — multi-round agentic research: sub-questions, parallel live-web queries and a
synthesis with tappable source chips. Reports save to your Research library automatically.

📧🗓️ PLUGINS WITH BRAKES — connect Gmail, Calendar and GitHub. Every write action stops in the
✋ inbox until YOU approve. Nothing sends without you.

🔔 PUSH NOTIFICATIONS — arena verdicts and approval requests follow you to your pocket.

🎤🖼️ MORE IN ONE APP — realtime voice chats, image generation, file & vision analysis with
long-term memory, team workspaces, and custom-domain white-label arenas for communities.

Your chats belong to you. Delete your memory, files and account any time — see the Privacy
Policy inside the app.
```

| Field | Value |
|---|---|
| Category | Productivity (alt: Tools) |
| Tags | ai chat, multi model, assistant, gpt, grok, gemini, voice ai, research |
| Privacy policy URL | `https://<your-site>/privacy` (ships with the web deploy) |
| Email | owner/support inbox |

## Data safety cheat (mirrors docs/PRIVACY.md)

| Data type | Collected? | Shared? | Purpose | Deletable? |
|---|---|---|---|---|
| Email, user ID | ✅ | ❌ | account | ✅ account delete |
| Messages/files/audio | ✅ | ✅ AI processors | app functionality | ✅ in-app |
| Installed plugins tokens | ✅ | ❌ (encrypted) | functionality | ✅ disconnect |
| App activity / usage | ✅ | ❌ | analytics (aggregate) | ✅ |
| Crash logs / performance | ✅ | ❌ | stability | auto-rotate |

## 🖼 Store assets (in `store-assets/`)

| File | Play slot | Spec |
|---|---|---|
| `feature-graphic.png` | Feature graphic | 1024×500 ✓ |
| `screenshot-arena.png` | Phone screenshot | 1080×1920 ✓ |
| `screenshot-chat.png` | Phone screenshot | 1080×1920 ✓ |
| `screenshot-plugins.png` | Phone screenshot | 1080×1920 ✓ |
| `screenshot-think.png` | Phone screenshot | 1080×1920 ✓ |
| launcher icon | App icon | `mobile/assets/icon/app_icon.png` 512² (scale once) |
| app icon hi-res (512×512) | Console icon | export from the ✦ source PNG |

> These are polished brand-true mockups — after the public web/mobile deploy, replacing the
> 2 hero shots with real captures is a 10-minute upgrade (same file names = git diff visible).

## Console checklist (≈30 min, all clicks)

1. Sign up Play Console ($25 one-time) → **Create app** → name/default lang/category.
2. Create the **release signing identity** on your machine:
   `keytool -genkey -v -keystore mood-upload.jks -keyalg RSA -keysize 2048 -validity 10000 -alias mood`
   then `base64 -w0 mood-upload.jks` → GitHub secret `MOOD_UPLOAD_KEYSTORE` (+ 3 sibling secrets
   listed in the workflow footer). Re-tag any `v*` — the AAB comes out **signed with your key**.
3. Internal track → Create release → upload `app-release.aab` → paste release notes from the tag.
4. Fill Store listing (copy from this doc) + Data safety (table above) + Content rating (IARC:
   reference/simulated themes → Everyone) + complete the *Declarations* (no ads, no target-kids).
5. Enroll **Play App Signing** (recommended) → download badge asset when live → party. 🎉

## Post-launch loop

- crash-free % lives in Android vitals; symbols for the obfuscated builds are the
  `mood-ai-android-symbols` CI artifact (upload to Play → Deobfuscation files).
- bump `version` in `mobile/pubspec.yaml` (`0.2.1+3` style) per release tag.
- web ↔ store cross-link: put the Play badge on the landing page + /privacy footer.
