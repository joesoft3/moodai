# 5boost.me cutover plan

Temporary app-domain target for this deployment:

- **Web app:** `https://5boost.me`
- **Optional www:** `https://www.5boost.me`
- **API:** `https://api.5boost.me`

> This keeps the root domain user-facing and leaves the API on a clean subdomain.
> We can change both later without touching app code.

---

## 1) Hosting-side custom domains

Attach these domains in the hosting dashboards first:

- add **`5boost.me`** to the web app project
- add **`api.5boost.me`** to the backend project

The exact DNS targets come from those dashboards.

Common patterns in this repo:
- web app → Netlify or Vercel custom-domain screen
- backend → Railway / Fly / Vercel custom-domain screen

---

## 2) Namecheap DNS records

Once the hosting dashboards show the required targets, add them in Namecheap.

### Root web domain
Point **`5boost.me`** at the web host using the exact values shown by that host.

### API subdomain
Create:
- **Host:** `api`
- **Type:** usually `CNAME`
- **Value:** the backend host target shown by Railway / Fly / Vercel

### Optional www
If you want `www.5boost.me` live too, point it at the web host or redirect it to the root.

---

## 3) App/runtime values to use

Use these values for the current cutover:

### Frontend build
- `NEXT_PUBLIC_API_URL=https://api.5boost.me/api/v1`

### Backend runtime
- `CORS_ORIGINS=https://5boost.me,https://www.5boost.me`
- `FRONTEND_URL=https://5boost.me`
- `BACKEND_PUBLIC_URL=https://api.5boost.me`
- `BASE_DOMAIN=5boost.me`

If plugin OAuth is enabled, update provider callback URLs to `https://api.5boost.me/...` too.

---

## 4) Smoke-check after DNS propagation

Run:

```bash
python3 scripts/check_domain_cutover.py 5boost.me api.5boost.me
WEB_URL=https://5boost.me scripts/live-smoke.sh https://api.5boost.me
```

Expected:
- app root resolves and serves HTTPS
- API `/healthz` responds
- frontend calls the API at `https://api.5boost.me/api/v1`

---

## 5) Important note from current checks

During this session, DNS lookups for `5boost.me` were returning **SERVFAIL** from the sandbox.
That usually means the domain delegation / nameserver setup is not healthy yet, so fix that first in Namecheap before expecting the app cutover to work.

Once `5boost.me` resolves normally, the rest of the cutover is straightforward.
