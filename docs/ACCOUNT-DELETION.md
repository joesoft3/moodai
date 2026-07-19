# 🗑 Account Deletion — Play & App Store compliance (v1.3.0)

Google Play (User Data policy, 2024) and the App Store (§5.1.1(v)) both require
apps that create accounts to offer **initiation of account deletion from within
the app**. Play additionally wants a **web link** where users can learn the
steps. Ship list:

| Surface | Where | Mechanism |
|---|---|---|
| Android/iOS app | Drawer → **Delete account** (red) | password re-confirm → `DELETE /api/v1/auth/me` |
| Web app | **Settings → Danger zone** | same endpoint, same password gate |
| Public web link (Play data-safety) | **/account-deletion** | static page: steps, scope, backups, email fallback |
| Support fallback | support@moodaiapp.com | verified owner, ≤ 72 h |

## What one call erases (service: `app/services/account.py`)

- profile + subscription record + usage events
- conversations & **all authored messages** (incl. inside team chats), share
  links, staged ✋ approvals
- uploads and extracted text, and the blobs on disk
- designs (web + print PNG tiers), brand kits, client order links
- films (video + poster), auto-edit sources/outputs
- Qdrant memories (best-effort purge — `clear_memories`)
- OAuth plugin tokens, push devices
- **teams:** owned workspaces dissolve completely (memberships, invites, team
  conversations); memberships in others' teams are left

Explicit children-first deletes — no reliance on FK cascades (sqlite-safe),
with a basename guard before any media unlink. Covered by
`backend/tests/test_v13.py` (purge-everything, cross-user isolation,
traversal guard) — **136 backend tests green**.

## Play Console / App Store Connect answers

- **"Does your app provide in-app account deletion?"** → *Yes — app drawer →
  Delete account; password re-confirm; deletion completes immediately.*
- **Deletion web URL** → `https://<your-web-domain>/account-deletion`
- **"Deleted data types"** — profile, content, files, purchases metadata; all
  deleted immediately; backups/log rotations purge ≤ 30 days.
