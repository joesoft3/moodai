# 🔁 Batch Studio + 🎵 Beat-Sync — v1.2.0

Two studio upgrades that cost **zero AI tokens** (100% local rendering).

---

## 🔁 Batch Studio — up to 10 matching flyers in one tap

Your shop has 10 product photos and one promotion. Instead of 10 separate
AI designs, you get **one headline → a matching flyer set** in seconds,
all print-ready (web 1024×1536 + print 2048×3072 @300 DPI, same as Design
Studio singles).

### Where
- **Web:** `/design` → **🔁 Batch studio** panel (below the generator)
- **API:** `POST /api/v1/media/designs/batch` · `POST /api/v1/media/designs/batch-csv`

### Photo flyers — `POST /media/designs/batch`
| form field | notes |
|---|---|
| `files` | 1–10 images (PNG/JPEG/WebP, ≤ 8 MB each) — one flyer per photo |
| `headline` | required, ≤ 90 chars (`%`, `:` etc. all safe) |
| `sub` / `cta` | optional sub-line + call-to-action pill |
| `accent` | `#RRGGBB` CTA pill color (default gold `#FFD54A`) |

Response: `{designs[], skipped[], trimmed, remaining_today}`
- each photo is cover-cropped to flyer size, your typography is overlaid
  with auto-fit font sizing + a readability scrim, both PNG tiers written
- `skipped` lists bad files (wrong type / >8 MB); `trimmed` counts photos
  beyond your daily design budget
- **counts against the normal `design_day` budget** (free 5/day, pro 60/day)

### CSV flyers — `POST /media/designs/batch-csv`
Upload a `.csv` (≤ 256 KB) → one **typographic card flyer per row** on a
soft two-tone theme.

```csv
headline,sub,cta,accent
Waakye Friday,Hot waakye + wele from GH¢20,Order 055-FOOD,#FFD54A
Braids Week,Knotless from GH¢150 — walk-ins welcome,Book 024-555,#FF73B3
Fufu Sunday,All you can eat GH¢50,024-CHOP-BAR,
```
- headers are tolerant: `headline|title|text|name`, `sub|subtitle|line|offer`,
  `cta|call|button|contact`, `accent|color|colour`
- `headline` required per row; empty rows are skipped; ≤ 10 rows per upload
- `theme` form field: `noir · sunset · ocean · forest · candy · gold`

Both endpoints return regular design rows → they appear in your gallery,
work with **🖨 print-shop exports** and **⭐ brand logo overlays**, and can
be delivered through 🛍 client order links.

Sample CSV: [`docs/samples/flyers.csv`](samples/flyers.csv)

---

## 🎵 Beat-sync edits — auto-cut to the rhythm

The ✂️ Auto-Edit learned rhythm. Say **"cut it to the beat"** in your
instruction (or just `{"beats": true}` in a plan) and the editor will:

1. **Analyze** the clip's audio locally — RMS energy envelope → onset peaks
   (no numpy, no network; stdlib `array` math on an 8 kHz mono decode)
2. **Pulse-cut** a 0.4 s window around every beat (max 96) and stitch them
3. **Report** the grid in the job notes: `🎵 11 beats @ ~117 BPM → pulse-cut
   to the rhythm` plus **drop moments** (energy spikes — the best spots for
   a caption line)
4. When the clip has no clear beat grid (silent clips), it falls back to
   even rhythm cuts and tells you.

Keywords that trigger it: *beat, tempo, to the beat/music, in sync, dance*.
Tune the window with `"beat_window": 0.15–0.9` (seconds kept per beat).

Chain it: `trim → beat-cut → reframe → subtitles → grade → music bed →
logo stamp` — e.g. *"cut it to the beat, make it vertical, warm colors, my
logo"* gives you a ready-to-post status clip in one upload.

Plan fields (LLM planner + heuristics): `beats: bool`, `beat_window: float`.
