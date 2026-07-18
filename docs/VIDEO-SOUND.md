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
  Coral, Verse). Unknown ids safely fall back to Alloy.
- **Custom narration** — leave the box blank and AI writes the voiceover; write
  your own (≤600 chars) and the mixer performs exactly that.
- Result tiles carry a **🎙/🎼 chip** and the spoken script in italics.

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
