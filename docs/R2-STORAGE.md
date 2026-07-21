# 📦 Cloudflare R2 — durable file storage

User uploads become durable once `R2_*` envs are set: files land in your
R2 bucket (S3-compatible, **zero egress fees**), with time-limited download
links generated on demand. Without R2, files stay on local disk (dev) or the
host volume (Fly `/data`) — both work, R2 just survives serverless/rebuilds.

DB rows keep either a local absolute path or an `r2:<key>` marker, so mixing
(older local files + newer R2 files) is safe, and account deletion purges both.

## Setup (≈4 min)

1. 🖱 [dash.cloudflare.com](https://dash.cloudflare.com) → your account →
   **R2 Object Storage** (left rail) → enable (card required; free tier:
   10 GB storage, 10M reads/1M writes a month)
2. 🖱 **Create bucket** → name `moodai` → region: automatic
3. 🖱 **Manage R2 API Tokens** → **Create API token** → *Admin Read & Write* →
   copy **Access Key ID** + **Secret Access Key**; your **Account ID** is on the
   R2 overview page's right side
4. Set env vars on the backend host:

| Var | Value |
|---|---|
| `R2_ACCOUNT_ID` | from the R2 overview page |
| `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | the token pair |
| `R2_BUCKET` | `moodai` |
| `R2_PRESIGN_SECONDS` | optional, default 3600 (download-link TTL) |
| `R2_PUBLIC_BASE_URL` | optional — public bucket/`r2.dev`/custom CDN base for permanent links |

5. Redeploy → uploads now persist in R2. ✅ Check: upload a file in the app,
   open the bucket in the dashboard — `uploads/<user>/<id>_<name>` appears.

## How it behaves

- **Upload** → straight to the bucket (or disk if R2 unset)
- **Download/view** → `307` redirect to a presigned (1 h) URL, or the public
  base URL when configured
- **AI analysis** (audio/video/docs) → reads back through the storage layer;
  nothing user-facing changes
- **Delete file / delete account** → objects purged from the bucket too
- Rendering outputs (flyers/films under `MEDIA_DIR`) stay on local disk for
  now — they're regenerable TTL artifacts; only source uploads are user data.
