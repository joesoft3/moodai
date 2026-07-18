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
