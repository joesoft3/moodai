# Mood AI — Privacy Policy

**Effective date:** 18 July 2026 · **Last updated:** 18 July 2026

This policy explains what Mood AI (“we”) collects, why, and your choices. Short version:
**your chats belong to you, plugins always ask before acting, you can delete everything.**

## 1. What we collect

| Category | Examples | Why |
|---|---|---|
| **Account** | email, display name, password hash | auth, security, plan management |
| **Conversations & memory** | your messages, assistant replies, 🧠 reasoning traces and digests, mood memory facts you let it keep, cross-conversation recall embeddings | to provide chat, recall past context, improve per-account experience |
| **Uploads** | documents, images, audio/video you attach | text extraction, analysis, vision/VLM answers, embeddings in your private document collection |
| **Plugin tokens** | Gmail / Google Calendar / GitHub OAuth tokens | only to answer your requests and stage actions you approve in the ✋ inbox — stored encrypted (Fernet), revocable any time |
| **Arena & usage telemetry** | run counts, tokens, model mix, arena debates, arena votes | metering, quotas, owner analytics (aggregate), abuse prevention |
| **Operational logs** | IP, timing, errors, device/browser clues | security, debugging — short retention |
| **Billing (when enabled)** | handled by Stripe; we store plan status/ids, not card numbers | subscriptions |

We do **not** sell personal data, do not use your content to train models ourselves, and do not
show you third-party advertising.

## 2. How we use it

Running the Service (generate answers — your content is sent to the configured AI providers
xAI/Grok, OpenAI, Google Gemini as needed), remembering preferences, enforcing quotas, securing
accounts, owner analytics (aggregated), supporting you, and legal compliance.

## 3. Legal bases (EEA/UK folks)

Contract performance (operate the Service you ask for), legitimate interests (security, product
improvement on aggregate data), consent (plugins/OAuth, memory features you can clear), legal
obligations.

## 4. Sharing & processors

- **AI providers:** xAI, OpenAI, Google — receive conversation context needed to respond.
- **Hosting/infra:** Railway (compute/database), Netlify (web), Qdrant (vector store), Redis,
  Stripe (billing), GitHub (code/CI).
- **White-label operators:** on customer domains, the operator is the controller for their
  end-users’ data; see their own privacy notice.
- We may disclose if the law requires, or to defend rights/safety.

## 5. Retention & deletion

Conversations, uploads and memory persist until you delete them (or your account). Deleting a
conversation removes it and its embeddings soon after; account deletion removes remaining data
within ~30 days (backups rotate out after that). Arena aggregate stats and de-identified usage
totals may persist. Plugin tokens are erased immediately on disconnect.

## 6. Security

TLS in transit, encryption at the provider level at rest, hashed passwords (PBKDF2-SHA256),
human-in-the-loop gating on every external write action, audited dependencies, and owner-only
admin surfaces. No method is 100% secure; report issues through GitHub or the in-app channel.

## 7. Your rights

Access, export (account data on request), rectification, deletion, restriction, objection and
portability where applicable (GDPR-style rights); and consent withdrawal (plugins/memory).
Settings gives you direct control over memory, files and plugins. EEA/UK/Ghana Data Protection
Commission complaints lie with your local authority.

## 8. Children

The Service is not for children under 13 (16 in the EEA/UK); we close such accounts on notice.

## 9. International transfers

Processing may occur anywhere our providers operate (US/EU/etc.); transfers rely on contractual
safeguards offered by each processor.

## 10. Cookies & storage

Sign-in uses a local-storage JWT (no third-party trackers, no ad cookies). Security/flood
limiting uses short-lived server state.

## 11. Changes

Material changes announced in-app/email; history lives next to this doc in the repo.

## 12. Contact / data controller

**Joesoft — Mood AI** (Accra, Ghana) · privacy questions via the in-app feedback channel or the
GitHub repo. White-label deployments: contact the domain operator first.

---
*Template note for the owner: confirm controller identity, support inbox, and provider list accuracy
before launch; Stripe rows activate when billing ships. Not legal advice.*
