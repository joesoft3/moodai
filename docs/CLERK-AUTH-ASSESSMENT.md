# 🔐 Clerk auth — honest assessment & adoption plan

**Verdict up front: launch with the built-in auth; adopt Clerk later only if
you specifically need its extras.** This document is the permanent record of
why, and exactly how to adopt it when the time comes.

## What we have today (working, tested, $0)

- Email + password auth (JWT, 7-day tokens), owner bootstrap, admin gating
- Play/App-Store compliant account deletion (password-gated, full data purge)
- Owner panel with per-user administration, plan tiers, usage metering
- Teams/workspaces, invites, plugin OAuth identities, device tokens
- 164 backend tests including the full auth lifecycle

## What Clerk would add

- Social logins (Google/Apple/GitHub buttons) with polished hosted UI
- MFA/passkeys, session management dashboards, impersonation for support
- 10,000 MAU free, then per-MAU pricing (~$25/mo tiers up)

## What a migration actually touches (the real cost)

| Area | Work |
|---|---|
| Backend auth guard (`api/deps.get_current_user`) used by **every** route | swap HS256 secret verify → Clerk JWKS verify + user sync/lazy-provision |
| Data model keying (`users.id` = our UUID on 20+ FK tables) | add `clerk_user_id`, backfill/link, migrate ownership |
| Frontend | replace login page + token storage with `ClerkProvider`/hosted pages; every `Authorization: Bearer` call switches to Clerk session tokens |
| Flutter app | `clerk_flutter` SDK integration, token refresh loop, deep links |
| Webhooks | Clerk `user.created/deleted` → sync plan/deletion flows (deletion must purge BOTH systems) |
| Compliance | account-deletion flow reworked + re-tested (store requirement) |
| Testing | re-run the whole auth surface + live smoke |

Realistic effort: **2–4 focused engineer-days** to do it properly — right
when the app is one database-paste away from being live.

## When Clerk *is* the right call

1. You want **"Sign in with Google/Apple"** buttons (Apple Sign-In becomes
   *mandatory* on iOS once you offer any third-party login — Clerk covers both)
2. You need MFA/passkeys for business customers
3. Sign-up fraud becomes a real problem

## Recommended phased path

- **Phase 0 (now):** launch on built-in auth. Zero rework risk.
- **Phase 1 (shipped, v1.6.0):** the federation seam **exists** already —
  `POST /api/v1/auth/clerk` verifies Clerk session JWTs (RS256 + JWKS, issuer
  checks, key-rotation refresh), links by email (find-or-provision, signup
  gates respected), and mints our standard token. Zero schema changes.
  To light it up: set `CLERK_ISSUER` (+`CLERK_SECRET_KEY` when tokens carry no
  email claim) on the backend, add a **Continue with Clerk** button to the
  login page (needs `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` + `@clerk/nextjs`).
  6 seam tests cover provision/link/forgery/expiry/gates/disabled.
- **Phase 2 (only if it wins):** migrate sessions fully, retire password UI,
  keep our backend as the source of truth for plans/deletion.
