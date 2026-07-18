# 🔑 Play upload key — APK Part 2 (5 minutes, one time)

Your Play upload key **already exists** — generated offline in the workspace at
`.secrets/mood-upload.jks` (RSA-2048, alias `mood`, valid to ~2053). The folder is
git-ignored: it **never leaves this machine** except when you paste it into
GitHub's secret vault.

## The 4 secrets — GitHub → moodai → **Settings → Secrets and variables → Actions**

| Secret name | Value | Where it lives now |
|---|---|---|
| `MOOD_UPLOAD_KEYSTORE` | the base64 text | **`.secrets/mood-upload.jks.b64`** — open it, copy the whole single line (3,428 chars) |
| `MOOD_UPLOAD_STORE_PASSWORD` | 20-char password | in **`.secrets/README-SECRETS.txt`** |
| `MOOD_UPLOAD_KEY_ALIAS` | `mood` | — |
| `MOOD_UPLOAD_KEY_PASSWORD` | 20-char password | in **`.secrets/README-SECRETS.txt`** |

Paste each → **Add secret**. That's all of part 2.

## What changes automatically

Every `v*` tag's Android workflow (`mobile-apk.yml`, already merged since v0.2.0):
1. base64-decodes `MOOD_UPLOAD_KEYSTORE` → `mood-upload.jks`
2. writes `key.properties` with store/key passwords + alias
3. builds the release APKs/AAB with the Gradle **release** signing config
4. attaches **production-signed** artifacts to the GitHub release.

Until the secrets exist, the workflow logs
`release signing: skipped — debug signature used` and carries on; the moment all
four exist, every next tag comes out Play-ready. Verify on any run: the
"conditional release signing" step prints `release signing: ENABLED (mood)`.

## Then

`git tag v0.4.1 && git push --tags` (or wait for the next feature tag) → grab
`app-release.aab` from the release → follow
[PLAY-STORE-SUBMISSION.md](PLAY-STORE-SUBMISSION.md) §5 (internal track).

## Safety rules (what NOT to do)

- ❌ Don't commit `.secrets/` (git would carry your key to GitHub in the clear — the `.gitignore` line blocks it).
- ❌ Don't paste the values into any chat/issue/PR.
- ✅ Do copy `.secrets/` offline (password manager attachment or USB). Losing the
  upload key after Play App Signing enrollment = support-ticket recovery, so it's
  recoverable but annoying; the backup makes it a non-event.
- 🔁 Rotation never needed — upload keys don't expire before 2053.
