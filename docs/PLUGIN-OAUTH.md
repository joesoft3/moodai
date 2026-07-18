# 🔑 Plugin OAuth — connect Gmail, Google Calendar & GitHub for real

The Plugin Store (web `/plugins`, mobile 🧩 tab) already works end-to-end —
tokens are stored encrypted, every write action is staged in the ✋ inbox.
The ONLY missing piece is your own OAuth client credentials, set as backend
environment variables. ~10 minutes, one-time.

> Convention below: **`https://YOUR-API`** = your Railway backend URL
> (e.g. `https://moodai-production-ab12.up.railway.app`), no trailing slash.

---

## Part 1 — Google (covers BOTH Gmail 📧 + Calendar 📅)

One Google OAuth client serves both providers. Scopes the app requests:

- `gmail.readonly`, `gmail.send` (+ Calendar: `calendar.readonly`, `calendar.events`)

**G1.** 🖱 [console.cloud.google.com](https://console.cloud.google.com) → top bar →
**New Project** → name `Mood AI` → **Create**.

**G2.** 🖱 **APIs & Services → Enabled APIs & services → + ENABLE APIS AND SERVICES**:
search and enable **Gmail API**, then again for **Google Calendar API**.

**G3.** 🖱 **APIs & Services → OAuth consent screen → Get started**:

- App name **Mood AI**, user support email = yours
- Audience: **External** → Contact: your email
- Finish. It starts in **Testing** mode — fine: add yourself as a
  **Test user** (Audience → Test users → + Add users). Up to 100 test users
  can connect before Google app verification (production publishing is a
  someday-task; Testing mode works indefinitely).

**G4.** 🖱 **Data access / Scopes → Add or remove scopes** — add:
`.../auth/gmail.readonly`, `.../auth/gmail.send`, `.../auth/calendar.readonly`, `.../auth/calendar.events`.

**G5.** 🖱 **Credentials → + Create Credentials → OAuth client ID**:

- Application type: **Web application** · Name: `Mood AI backend`
- **Authorized redirect URIs** — add BOTH:
  - `https://YOUR-API/api/v1/plugins/gmail/callback`
  - `https://YOUR-API/api/v1/plugins/google_calendar/callback`
- **Create** → copy the **Client ID** and **Client secret**.

**G6.** 🖱 Railway → *moodai* → **Variables**:

| Name | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | *〈client id, ends `.apps.googleusercontent.com`〉* |
| `GOOGLE_CLIENT_SECRET` | *〈client secret〉* |
| `BACKEND_PUBLIC_URL` | `https://YOUR-API` *(so the backend builds the same callback URIs you whitelisted)* |

---

## Part 2 — GitHub 🐙

**H1.** 🖱 [github.com/settings/developers](https://github.com/settings/developers) →
**OAuth Apps → New OAuth App**:

| Field | Value |
|---|---|
| Application name | `Mood AI` |
| Homepage URL | your Netlify web URL |
| Authorization callback URL | `https://YOUR-API/api/v1/plugins/github/callback` |

**H2.** 🖱 **Register application** → **Generate a new client secret** → copy both values.

**H3.** 🖱 Railway variables:

| Name | Value |
|---|---|
| `GITHUB_CLIENT_ID` | *〈client id〉* |
| `GITHUB_CLIENT_SECRET` | *〈client secret〉* |

---

## ✅ Verify (1 minute)

1. Web app → **🧩 Plugins** → a provider card now shows **Connect** (not "Not configured").
2. Click it → provider consent screen → back to **/plugins?plugin=connected** with the pill flipped.
3. Ask in chat: *“check my unread emails and summarise”* — the staged actions appear in the ✋ Action inbox.
4. Approve one → it executes; reject one → nothing happens (HITL intact).

🛠 **Troubleshooting**

| Symptom | Fix |
|---|---|
| *redirect_uri_mismatch* (Google) | The URI on screen must EXACTLY equal `https://YOUR-API/api/v1/plugins/<provider>/callback` — check `BACKEND_PUBLIC_URL` + G5. |
| "Not configured" still on card | Restart didn't happen — Railway redeploys on variable change; verify the 4 vars saved. |
| GitHub works, Google says *app untested* | You're in Testing mode — add your email under **Test users** (G3). |

*More: [RAILWAY-CHEATSHEET](RAILWAY-CHEATSHEET.md) (env catalog) · [GO-LIVE-CLICKSHEET](GO-LIVE-CLICKSHEET.md)*
