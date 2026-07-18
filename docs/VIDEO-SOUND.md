# 🎙 Cinema Sound — text-to-video with pure sound & voice

**Shipped in v0.3.0.** Mood's Video Studio can now finish every generated clip
with a studio-grade soundtrack: an AI-written, AI-performed voiceover mixed over
a soft procedural ambience — loudness-normalized ("pure sound") and muxed into a
single MP4 by a server-side ffmpeg pipeline.

```
your idea ──▶ director model ──▶ voiceover script (sized to clip length)
                 │                        │
                 │                        ▼
                 │                OpenAI-compatible TTS (10 voices)
                 │                        │
                 ▼                        ▼
          video provider ────▶  ffm─ voice: loudnorm (−16 LUFS, EBU R128)
           (silent clip)         peg─ original clip audio: ducked ×0.35 (if any)
                                 mix─ ambience: 108/162 Hz sines + tremolo,
                                      faded in/out, ~−28 dB under the voice
                                        │
                                        ▼
                           /api/v1/media/files/{uuid}.mp4  (≤24 h TTL)
```

## Using it (Video Studio → 🔊 Sound row)

| Sound mode | What you get |
|---|---|
| 🔇 **None** | The provider's original clip (unchanged behavior pre-v0.3.0). |
| 🎙 **AI voiceover** | Director model writes narration sized to the clip (~2.2 words/sec), TTS performs it, loudness-polished, trimmed to clip length. |
| 🎼 **Voice + ambience** | Everything above, plus a soft cinematic ambient bed and — when the provider clip already carries sound — the original audio, ducked under the voice. |

Options:

- **Voice** — 10 voices (Alloy, Nova, Shimmer, Echo, Onyx, Fable, Sage, Ash,
  Coral, Verse) with a **▶ Preview** button; unknown ids fall back to Alloy.
- **🎼 Music mood** (cinema mode) — `soft` (default), `epic` (55 Hz drone),
  `lofi` (pink-noise tape hiss), `tension` (2 Hz pulse). All are synthesized by
  ffmpeg on the fly — zero assets, zero licensing.
- **⏱ Tempo** — narration speed `0.7–1.3` (UI: Calm 0.85× / Natural / Punchy 1.15×).
- **Custom narration** — leave the box blank and AI writes the voiceover; write
  your own (≤600 chars) and the mixer performs exactly that.
- Result tiles carry a **🎙/🎼 chip** and the spoken script in italics.

## 🎬 Storyboard mode (v0.4.0) — one idea, N directed scenes, one film

Flip **🎬 Scenes** from *Single shot* to a 2/3/4-scene film:

1. **Plan** — the director model splits your idea into 2–4 scenes, each with a
   dense shot prompt + one voiceover line sized to the scene (setup → build → payoff).
   You can overrule it in *Advanced* with your own scenes:
   `shot description || optional narration line`, one per line.
2. **Render** — each scene clip is generated sequentially (provider-polite), then
   downloaded and normalized (scale/pad to the aspect, 24 fps).
3. **Stitch** — one ffmpeg graph concatenates the scenes, lays each scene's voice
   back-to-back so the story flows across the cuts, adds the ambience bed
   (cinema mode) and the R128 loudness polish.
4. **Subtitles** — optional: every scene's narration is burned in as a styled,
   correctly-timed subtitle cue (libass; graceful skip if unavailable).

Fair use: **each scene counts as one daily video** and the endpoint pre-checks
your remaining quota *before* spending anything (429 with the math if short).
Scenes render **2-wide in parallel** (≈2× faster films, still provider-polite),
and metering happens *at render time* — a mid-film failure only ever counts the
scenes actually rendered. Voice preflight: no `OPENAI_API_KEY` → films are shot
silent with a note. Stitch failure → you get scene 1 (a finished clip), never
an empty hand.

**Async by design (v0.5.0):** `POST /api/v1/media/videos/storyboard` answers
`202` in ~1s with `{ film }` — the render runs as a background task persisting
milestones to the `films` table, so the UI can poll and the 🎞 **Films** gallery
(`/films`) remembers everything:

| Endpoint | Purpose |
|---|---|
| `GET /media/films` | your newest 24 films + `jobs_running` counter |
| `GET /media/films/{id}` | one film (status/progress/url/script/scenes) — the poll target |
| `POST /media/films/{id}/resume` | relaunch a film stuck `rendering` (e.g. after a deploy restarted the worker mid-render) |
| `DELETE /media/films/{id}` | remove a film |

Status flow: `rendering` (progress N/scene_count per milestone) → `done`
(url + script + actual audio mode) | `failed` (why). The gallery's
**✏️ Edit & re-render** deep-links into the studio with the film's scenes
pre-loaded as custom scenes — the fastest "regenerate one scene" workflow:
edit that line, hit Generate (only billed for the new render's scenes).

**Professional extras (v0.6.0):**
- 🖼 **Film posters** — a hero frame (≈35% through the film, where trailers peak)
  is extracted server-side and served as `<uuid>_p.jpg`: gallery tiles and
  `<video poster>` placeholders use it, and it's the share page's OG image.
- 🌐 **Public share pages** — `GET /media/public/films/{id}` (unguessable-id,
  finished films only) + the web app's **`/f/{id}`** server-rendered page:
  OpenGraph video + poster previews in chats/socials, cinematic player card,
  "direct your own film" CTA, Terms/Privacy footer. Films → **Share** copies it.
- 🔔 **Completion push** — when a film lands `done`, a `film_ready` FCM
  notification deep-links into the gallery ("🎬 Your film is ready").
- 📲 **Mobile Films screen** — drawer → 🎞 Films: poster grid, live render
  progress, tap-to-play fullscreen, share/delete/resume (mirrors web).

## API

`POST /api/v1/media/videos` (auth, plan-capped, metered — one usage counted even
with sound on):

```jsonc
{
  "prompt": "A lighthouse at dusk, waves crashing",
  "duration": 8, "aspect_ratio": "16:9", "quality": "720p", "style": "cinematic",
  "audio": "cinema",            // none | narration | cinema   (default none)
  "voice": "onyx",              // 3-12 lowercase letters, whitelist in service
  "narration": ""               // empty → AI writes the voiceover
}
```

Response additions:

```jsonc
{
  "url": "https://<api>/api/v1/media/files/<32-hex>.mp4",  // muxed, when sound succeeded
  "audio": "voice+ambience",   // none | voice | voice+ambience (actual outcome)
  "script": "The sea keeps its oldest secrets here…",
  "note": null                  // set when sound degraded → original clip returned
}
```

`GET /api/v1/media/files/{name}` — **public** streaming endpoint (unguessable
128-bit uuid names; path-traversal names rejected; janitor purges files older
than `MEDIA_TTL_HOURS`). Public so `<video>` tags and mobile players need no
auth headers.

## Config (Railway variables)

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | **Required for sound** (TTS voice). Already used for Whisper/voice mode. |
| `BACKEND_PUBLIC_URL` | localhost | **Must be the API's public URL** (e.g. `https://<app>.up.railway.app`) so muxed file URLs resolve in browsers/players. |
| `FFMPEG_PATH` | `ffmpeg` | Binary location. The backend **Dockerfile already installs ffmpeg** — nothing to do on Railway. |
| `MEDIA_DIR` | `/tmp/mood-media` | Where muxed MP4s land (ephemeral is fine — 24 h TTL). |
| `MEDIA_TTL_HOURS` | `24` | Janitor purge horizon. |
| `VIDEO_MAX_DOWNLOAD_MB` | `256` | Cap when pulling the provider clip for muxing. |

## Graceful degradation (the user always gets a video)

| Failure | Result |
|---|---|
| `OPENAI_API_KEY` missing | Original clip + `note` telling the user to configure the voice provider. |
| ffmpeg missing | Original clip + `note`. (Dockerfile prevents this on Railway.) |
| Full mix fails | Auto-retry with a **voice-only** minimal filter graph. |
| Voice-only mix fails | Original clip + `note`. |
| Director model down | Voiceover falls back to a fitted version of the user's own prompt. |

## Tests

`backend/tests/test_soundtrack.py` (13 tests): word budgets, sentence-boundary
clipping, mux argv builder (voice-only + full mix + zero-length fade guard),
ffmpeg-missing degradation, explicit-path config, filename traversal guard,
schema validation. `backend/tests/test_boot.py` boot-imports the entire app and
asserts router wiring — it guards the class of bug that once silently broke
boot (`send_email` dropped during the Push rewrite).

## Cost notes

- One TTS call per sound-tracked video (~1–2 s audio per minute of narration).
- Muxing is CPU-bound in-request (~2–6 s for 15 s clips on Railway's small
  instances); the provider's generation still dominates wall-clock time.
