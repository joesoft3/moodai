# 🎨 Design Studio — flyers, logos & banners at print resolution

The studio turns a one-line idea into a print-ready PNG in ~30 seconds:

1. **Art-director pass** — the fast model rewrites your idea into a dense design
   brief (exact headline text, layout hierarchy, palette). Toggle it off to use
   your words verbatim. Put exact text in `'quotes'` so spelling survives.
2. **Render** — the configured image model paints the design. On `gpt-image-*`
   models the studio requests the native canvas (`1024×1536` flyer,
   `1536×1024` banner, `1024×1024` logo) at `quality=high`, and logos can use
   a transparent background (falls back to flat+auto-retry if the provider
   rejects it). Any other provider still works — the canvas is normalized
   server-side.
3. **Print pass** — ffmpeg lanczos-upscales and tags **300 DPI** metadata:
   - Flyer: web `1024×1536` → print `2048×3072` (~A4 class)
   - Logo: web `1024×1024` → print `2048×2048` (transparent when supported)
   - Banner: web `1536×1024` → print `3072×2048` (3K hero)

| Endpoint | Notes |
|---|---|
| `POST /api/v1/media/designs` | `{idea, kind, style, palette, transparent, enhance}` → design row |
| `GET /api/v1/media/designs` | gallery (newest 50) |
| `GET /api/v1/media/designs/presets` | kinds/styles/palettes the UI renders from |
| `GET /api/v1/media/designs/{id}/download?tier=web\|print` | owner-gated PNG with friendly filename |
| `DELETE /api/v1/media/designs/{id}` | removes row **and** both PNG tiers |

**Retention:** unlike 24h-TTL muxed videos, design files *persist* until you
delete them — a logo is a keepsake. They are never publicly served.

**Limits:** free 5/day · pro 60/day (`design_day` plan cap), 4/min burst.

## 🧑‍💼 Brand Kit (v0.9.0)
`PUT/GET /media/brand` stores one identity per user (name, tagline, 3 colors,
font vibe, brand logo = one of your logo designs). With `use_brand: true`,
generation weaves the identity into the art-director brief **and** ffmpeg
composites your saved logo bottom-right (16% canvas width, padded) onto the
web tier — the 300-DPI print tier is then upscaled *from the branded frame*,
so both tiers carry your logo. Logo-kind generations skip compositing (they
*are* the logo) but still honor the colors/fonts.

## ✈️ Starter templates (v0.9.0)
`GET /media/designs/templates` — 10 Ghana-flavored briefs (chop bar, salon,
church program, waakye Friday, real estate, momo agent, thrift pop-up, gym,
DJ night, provisions logo). Each presets kind+style+palette; `[brackets]` mark
the fields to personalize.

## 📱 Mobile (v0.9.0)
The Flutter app ships the full studio (`design_screen.dart`): kind tabs,
chips, brand toggle, grid gallery with Share (WhatsApp sheet) for both tiers
(share_plus), delete, autosynced previews.

## 🖨 Print-shop & social exports (v1.0.0)
`GET /media/designs/{id}/export?preset=…` → cached 300-DPI PNGs, generated on demand:
- `a4_bleed` (2480×3508 trim + 3mm bleed, white canvas + 8 crop marks, 300 DPI tag)
- `a5_bleed` (1748×2480 trim + marks) — matches the Ghana print shops' staples
- `wa_status` 1080×1920 · `ig_post` 1080×1350 · `ig_square` 1080×1080 (exact crops)
Preset list: `GET /media/designs/exports`.

## ⭐ Brand app icon (v1.0.0)
`GET /media/brand/icon?size=192|512` renders a PWA-ready square tile from your Brand
Kit (primary-color canvas + brand initial in accent) — pure ffmpeg, no model call.

## 🤖 Design agent (v1.0.0)
The chat/plugin tool `design_create` is a **staged ✋ write action**: the model
drafts it, you approve it in the Plugin Store inbox, and only then does the
renderer run — the design lands in your Studio gallery with a how-to card.

## 🎞 Branded films (v1.0.0)
Storyboard films accept `use_brand: true`: identity colors/style are woven into
scene planning and your logo is stamped onto the hero-frame poster; the public
share card says "by *Your Brand* · Directed with Mood AI".

## 🛍 Client mode (v1.1.0)
`POST /media/design-orders` → magic link `/order/{token}`. Clients pick
kind+style, describe their design, submit — the order lands as a **✋ staged
`design_create`** action on your account. Approve in the Plugin Store inbox and
the order flips to **delivered**: the client downloads Web + Print-HD PNGs from
the very same link (`GET /media/public/orders/{token}/download`). Close links
with `POST /media/design-orders/{id}/close`.

## 📊 Studio analytics (v1.1.0)
Admin → Engagement gains a **🎨 Creative studio** widget: 30-day mix
(videos / i2v / designs / edits / exports / films), design-kind bars and a rough
est. spend (usage_events metering: `i2v`, `edit`, `design_export` kinds).
