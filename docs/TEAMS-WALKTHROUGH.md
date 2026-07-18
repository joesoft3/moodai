# 👥 Teams & Workspaces — walkthrough + test checklist

Teams in Mood AI = **workspaces**: shared space with members, a per-team conversation list,
invite links (optional email-gated), and per-workspace usage metering. No extra auth —
your normal account can belong to many workspaces.

## Where things live

| Surface | What you get |
|---|---|
| **Settings → Teams** | create a workspace, see yours, generate/revoke invites |
| **Chat header** | workspace switcher — personal ↔ team context |
| **`/join/<token>`** | the magic invite link; bounces signed-out people to login and back (`?next=`) |
| **Owner panel → Users/Teams** | platform-level view for admins |

API (all under `/api/v1/workspaces`): create `POST /`, list `GET /`, invites
`POST /{id}/invites` · `GET /{id}/invites` · `POST /{id}/invites/email` · `DELETE /{id}/invites/{iid}`,
join `POST /join`, members `POST/DELETE /{id}/members`, conversations `GET /{id}/conversations`,
usage `GET /{id}/usage`.

## The 2-minute tour

1. **Create** — Settings → Teams → *New workspace* → name it (e.g. `Team Mood`). You are owner.
2. **Invite** — open the workspace → *Create invite* → copy the link `https://<app>/join/<token>`. Optionally restrict to one **email domain** (e.g. `@mood.ai`) or send an **email invite** from the same panel.
3. **Join** — on the teammate's device: open link → create account / sign in → auto-bounced back onto `/join/<token>` → *in the team* (domain-gated invites reject mismatched emails politely).
4. **Work together** — teammates switch to the workspace in the chat header; messages sent there appear in **workspace conversations** for everyone; memory stays personal, arenas/quota still per-user.
5. **Meter** — workspace → Usage shows the team's token/actions roll-up; plan limits apply per member, so personal caps still guard the bill.
6. **Manage** — owner: add/kick members, revoke invites instantly; members: leave any time.

On a **verified custom domain**, the same workspace screens are white-labeled (brand +
judge panel) — see [CUSTOM-DOMAIN-SALES-PAGE](CUSTOM-DOMAIN-SALES-PAGE.md).

## ✅ Test checklist (run on the live deployment)

- [ ] Create workspace → appears in Settings → Teams with member count 1 (you/owner)
- [ ] `POST /workspaces/{id}/invites` → token link opens the brand-styled `/join/<token>` page
- [ ] Signed-out join → bounced to `/login?next=/join/<token>` → returns + joins after auth
- [ ] Domain-gated invite rejects a non-matching email with a clear message (not a 500)
- [ ] Two members chatting in the workspace → both see entries in workspace conversations
- [ ] Workspace usage endpoint returns a roll-up that grows after a chat
- [ ] Owner kicks a member → member loses workspace in the header switcher immediately
- [ ] Revoked invite link → join page shows “invite expired/invalid”
- [ ] Personal chats stay private (never listed in the workspace tab)
- [ ] Mobile: same flows on the 🧩/chat screens after API URL points at the deployment

🛠 If a step fails on production, run the same flow locally: `scripts/smoke.sh` covers the API
paths, and any regression belongs in `backend/tests/` next to the workspaces routes.
