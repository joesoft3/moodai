# 🏪 Play Store submission run — Mood AI (internal track → production)

End-to-end runbook: every form answer pre-written, every click in order.
Pair with [PLAY-CONSOLE.md](PLAY-CONSOLE.md) (listing copy + store assets) — this
doc is the *submission paperwork*.

**Prereqs:** Play Console account ($25) · repo secrets `MOOD_UPLOAD_KEYSTORE` +
`MOOD_UPLOAD_STORE_PASSWORD` + `MOOD_UPLOAD_KEY_ALIAS` + `MOOD_UPLOAD_KEY_PASSWORD`
set (→ every `v*` tag CI attaches a **signed** `app-release.aab` to the release) ·
✅ newest AAB: [releases/latest](https://github.com/joesoft3/moodai/releases/latest).

---

## 1) Create the app (5 min)

| Field | Answer |
|---|---|
| App name | **Mood AI** |
| Default language | English (United States) |
| App or game | App |
| Free or paid | Free |
| Declarations | ✓ Play policies · ✓ US export laws |

Store presence → category **Productivity** (alt Tools), tags:
`ai chat` `video ai` `multi model` `assistant` `grok` `arena`.

## 2) Data safety form (paste-ready answers)

Path: **Policy → App content → Data safety**. One section per data type:

| Data type | Collected | Shared | Purpose | Notes to paste |
|---|---|---|---|---|
| Personal info → **Email address** | ✅ | ❌ | Account management | "Required for sign-in and account recovery." |
| Personal info → **User IDs** | ✅ | ❌ | Account management | server-generated uuid |
| App activity → **App interactions** | ✅ | ❌ | Analytics | "Aggregate usage stats (feature counts) for plan limits & reliability. Not per-user advertising." |
| **Files and docs** | ✅ | ✅ → "AI processing providers" | App functionality | "User uploads are sent to the AI providers you connect (via your own API keys) to produce answers. Not used for advertising, not shared with data brokers. Deletable in-app." |
| **Audio files** (voice mode) | ✅ | ✅ AI providers | App functionality | same as files |
| **Photos and videos** | ✅ | ✅ AI providers | App functionality | same as files |
| **Device or other IDs** (FCM token) | ✅ | ✅ → "Firebase Cloud Messaging (Google)" | App functionality — push notifications | "Push token, rotated by the OS. Pruned automatically when stale. Deletable via Settings → sign out." |

Every page: **Encrypted in transit = YES** (TLS everywhere) ·
**Users can request deletion = YES** (in-app: Settings → Memory/Files/Account + owner panel).

> The two "shared" categories = Google FCM (push) and the user's OWN configured
> AI providers (BYOK) — both are *service delivery*, not data sales. Say that in
> the free-text fields; reviewers accept it.

## 3) Content rating (IARC questionnaire)

| Question | Answer |
|---|---|
| Category | Utility, productivity, communication |
| Violence / sexuality / language / drugs | **No** to all |
| User-generated content | **Yes** — users can exchange AI text |
| …further detail | "AI-generated text responses to user prompts" |
| Uncontrolled sharing | Users may share text (chat share links) |
| Location sharing | No |
| Gambling | No |

Expected result: **Everyone 10+ / PEGI 3–7 w/ "users interact" notice**. (If the
form offers "AI chatbot" nuance, pick the honest interactive option — lands Teen at
worst; that's fine for an AI app.)

## 4) Other declarations

| Form | Answer |
|---|---|
| Ads | **No ads** |
| Target audience | **18+** (13+ acceptable; pick 18+ to skip child-safety review rabbit holes) |
| News app | No |
| COVID-19 contact tracing | No |
| Government app | No |
| Financial features | No (Stripe billing is deferred/not shipped) |
| Data deletion page | `https://<your-site>/privacy` plus in-app path |

## 5) Internal testing track (15 min)

1. **Testing → Internal testing → Create new release.**
2. Upload **`app-release.aab`** from the latest `v*` GitHub release assets.
3. Release name: `v0.4.0 — Cinema Sound + Storyboard films` (mirror the GitHub notes).
4. Release notes: paste the "What's new" block from the GitHub release.
5. **Testers** → create email list `mood-internal` → add your Gmail(s).
6. Save → **Review release** → fix any yellow warnings (almost always: missing
   content rating/data-safety — covered above) → **Start rollout to Internal testing**.
7. Copy the **invite link** → open it on your phone → install from Play (replaces
   the sideloaded APK; future updates arrive through Play).

## 6) Play App Signing + integrity checklist

- Enroll **Play App Signing** (Google holds the app key; your `mood-upload.jks`
  stays the *upload* key — already what CI signs with).
- App integrity → confirm "Google Play signing" shows the SHA-256 cert — paste it
  nowhere else; Firebase needs it **only if** you later enable App Check.
- Push check: install via Play → sign in → owner panel → **Send test push** → ping arrives. 🔔

## 7) Production path (when internal feels solid)

1. Internal track → **Promote release → Production**.
2. Production countries: start Ghana + a handful; no other paperwork needed for free apps.
3. Pre-launch report (auto-runs on the AAB across ~12 devices): read crashes only —
   screenshot/video quality of the crawler is irrelevant.
4. Roll out at 20% → 50% → 100% across a week; reply to the first 10 reviews personally.

## Rollback / hotfix plan

Bump `versionCode` in CI is automatic per tag — hotfix = fix + `git tag v0.4.1` +
push → signed AAB attaches → upload over the same track. Users auto-update; **no
key work ever again** (keystore lives only in GitHub secrets + your offline backup —
store `mood-upload.jks` + passwords in a password manager *offline* too).

---

*Paperwork done = listing (PLAY-CONSOLE.md) + this file + the signed AAB from CI.
Total human time: about one focused evening.* 🎬

---

## 🗑 Account deletion (store-required)

- **In-app:** drawer → **Delete account** → password → *Delete forever* (immediate, irreversible).
- **Web:** Settings → **Danger zone** — same flow.
- **Public guide URL for the Data safety form:** `https://<your-web-domain>/account-deletion`
- Scope + mechanics: [`docs/ACCOUNT-DELETION.md`](ACCOUNT-DELETION.md). Backups/logs rotate out ≤ 30 days.
