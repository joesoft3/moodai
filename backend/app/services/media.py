"""Video generation behind a provider seam (VIDEO_PROVIDER).

Professional features:
- Options: duration / aspect ratio / quality / style / negative prompt
- A prompt compiler layers style presets + quality tags onto the user's idea
- Lean-retry: if the provider rejects extended params, we retry with the
  minimal payload instead of failing the user's generation.

Provider cascade (VIDEO_PROVIDER is a comma-chain, first success wins):
- "reel"         🎬 Mood Reel — zero-key composer: FLUX scene stills (keyless
                 Pollinations) → ffmpeg Ken Burns mp4 with crossfades. Works
                 today; needs only ffmpeg (both deploy images ship it, and the
                 imageio-ffmpeg wheel covers serverless).
- "pollinations" gen.pollinations.ai video models (wan-fast etc.) — needs
                 POLLINATIONS_API_KEY (401 without one, verified live).
- "xai"          Grok video when the key carries credits (402 → cascades on).
"""

import asyncio
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

import httpx

from ..config import settings

log = logging.getLogger(__name__)


class VideoNotConfigured(Exception):
    pass


class VideoGenerationError(Exception):
    pass


# Professional style presets — layered onto the user's prompt by the compiler.
STYLE_PRESETS: dict[str, str] = {
    "cinematic": "cinematic film shot, anamorphic lens, shallow depth of field, film grain, dramatic motivated lighting, subtle camera movement",
    "photoreal": "photorealistic, 8K detail, natural skin and materials, correct physics, realistic lighting and shadows",
    "product_ad": "premium product commercial, studio lighting, glossy reflections, slow dolly shot, clean seamless background, macro detail",
    "anime": "high-end anime style, vibrant colors, detailed background art, smooth sakuga-quality motion",
    "documentary": "nature documentary footage, telephoto lens, natural light, National Geographic style, steady gimbal shot",
    "timelapse": "timelapse, smooth accelerated motion, dynamic clouds and light changes, locked-off tripod framing",
    "retro_film": "retro 16mm film look, warm faded colors, visible grain and gate weave, nostalgic atmosphere",
}

QUALITY_TAGS = {"720p": "high quality", "1080p": "high quality, sharp 1080p detail"}

NEGATIVE_DEFAULT = "morphing, flicker, warped faces, distorted hands, readable text, text overlays, captions, subtitles, logo overlays, watermark, jitter"

# 🎬 Mood Reel scene beats — deterministic camera-language variations wrapped
# around the user's idea (no LLM spent: daily-quota economy).
REEL_BEATS = [
    "wide establishing shot, full scene in frame",
    "slow push-in, rich mid-frame detail",
    "close-up detail shot, shallow depth of field",
    "dramatic angle, golden-hour light, layered background",
    "sweeping panoramic view, atmospheric haze",
]
REEL_FADE_S = 0.5

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_TTS_URL = "https://api.groq.com/openai/v1/audio/speech"
_GTTS_URL = "https://translate.google.com/translate_tts"


def _storyboard_prompt(prompt: str, scenes: int) -> str:
    return (
        f'You are a film director. Break this idea into exactly {scenes} cinematic still-frame '
        f'scene prompts (each < 28 words, purely visual, keep the subject consistent across '
        f'scenes, vary camera distance/angle), plus a one-breath voiceover line (14-24 words, '
        f'warm, no camera talk).\nIdea: "{prompt[:500]}"\n'
        f'Reply with STRICT JSON only: {{"scenes": ["...", ...], "narration": "..."}}'
    )


def _extract_json(text: str) -> dict | None:
    import json
    import re

    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


@dataclass
class VideoOptions:
    duration: int = 6               # seconds
    aspect_ratio: str = "16:9"      # 16:9 | 9:16 | 1:1
    quality: str = "720p"           # 720p | 1080p
    style: str = "cinematic"
    negative_prompt: str = ""


def compile_prompt(prompt: str, opts: VideoOptions) -> str:
    """Layer style preset + quality + motion/jurisdiction hints onto the raw idea."""
    preset = STYLE_PRESETS.get(opts.style, STYLE_PRESETS["cinematic"])
    qtag = QUALITY_TAGS.get(opts.quality, "high quality")
    negative = opts.negative_prompt.strip() or NEGATIVE_DEFAULT
    return f"{prompt.strip()}, {preset}, {qtag}. Avoid: {negative}."


def build_video_payload(model: str, compiled: str, opts: "VideoOptions",
                        image: dict | None = None) -> dict:
    """Full professional payload; `image={"url": ...}` turns it image-to-video."""
    p: dict = {
        "model": model,
        "prompt": compiled,
        "duration": opts.duration,
        "aspect_ratio": opts.aspect_ratio,
        "resolution": opts.quality,
    }
    if image:
        p["image"] = image
    return p


def _dig_url(data: Any) -> str | None:
    """Tolerantly find a video URL in common response shapes."""
    if not isinstance(data, dict):
        return None
    for key in ("url", "video_url", "output_url"):
        v = data.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v
    for key in ("data", "output", "videos", "result"):
        v = data.get(key)
        if isinstance(v, list) and v:
            found = _dig_url(v[0])
            if found:
                return found
        elif isinstance(v, dict):
            found = _dig_url(v)
            if found:
                return found
    return None


def _ffmpeg_exe() -> str | None:
    """System ffmpeg first; the imageio-ffmpeg wheel covers hosts (Vercel lambdas)
    where no apt binary exists."""
    exe = shutil.which(settings.FFMPEG_PATH or "ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _reel_dims(aspect: str) -> tuple[int, int]:
    return {"16:9": (1600, 900), "9:16": (900, 1600), "1:1": (1280, 1280)}.get(aspect, (1600, 900))


class VideoService:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=90.0))

    async def generate(self, prompt: str, opts: VideoOptions,
                       image: dict | None = None,
                       on_progress: Callable[[dict], None] | None = None) -> tuple[str, bool]:
        chain = [p.strip().lower() for p in (settings.VIDEO_PROVIDER or "reel").split(",") if p.strip()]
        if not chain:
            chain = ["reel"]
        last_err: Exception | None = None
        for name in chain:
            try:
                if name == "reel":
                    return await self._reel(prompt, opts, on_progress=on_progress)
                if name == "pollinations":
                    return await self._pollinations(prompt, opts)
                if name == "xai":
                    return await self._xai(prompt, opts, image=image)
                raise VideoNotConfigured(f"Unknown VIDEO_PROVIDER member '{name}'.")
            except (VideoNotConfigured, VideoGenerationError) as e:
                last_err = e
                if name != chain[-1]:
                    log.info("video provider '%s' unavailable (%s) — cascading", name, e)
                    continue
        if last_err:
            raise last_err
        raise VideoNotConfigured("VIDEO_PROVIDER chain is empty.")

    # ----------------------------------------------------- storyboard & voice
    async def _storyboard(self, prompt: str, scenes: int) -> tuple[list[str] | None, str | None]:
        """🎞️ LLM storyboard via the free Groq brain (fail-open → deterministic beats).
        Returns (scene_prompts, narration_text) or (None, None)."""
        key = (settings.EXTRA_BRAIN_API_KEY or "").strip()
        if not key:
            return None, None
        try:
            r = await self._http.post(
                _GROQ_CHAT_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": settings.EXTRA_BRAIN_MODEL or "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": _storyboard_prompt(prompt, scenes)}],
                    "temperature": 0.7,
                    "max_tokens": 500,
                    "response_format": {"type": "json_object"},
                },
                timeout=httpx.Timeout(15.0, read=35.0),
            )
            if r.status_code >= 400:
                log.info("storyboard brain hiccup (%s): %s", r.status_code, r.text[:120])
                return None, None
            data = _extract_json(r.json()["choices"][0]["message"]["content"])
            if not data:
                return None, None
            raw = data.get("scenes")
            out = [str(s).strip() for s in (raw or []) if str(s or "").strip()]
            if len(out) < 2:
                return None, None
            narration = str(data.get("narration") or "").strip() or None
            return out[: settings.REEL_MAX_SCENES], (narration[:300] if narration else None)
        except Exception as e:
            log.info("storyboard unavailable (%s) — deterministic beats", e)
            return None, None

    async def _narrate(self, script: str) -> tuple[bytes, str] | None:
        """🔊 TTS cascade, fail-open: Groq Orpheus → Cloudflare aura-1 (same
        WorkersAI token as the embeddings tier) → unofficial gTTS → None (silent).
        Returns (audio_bytes, mime) for ffmpeg to mux."""
        text = script.strip()[:600]
        if not text:
            return None
        key_g = (settings.EXTRA_BRAIN_API_KEY or "").strip()
        key_cf = (settings.EMBED_API_KEY or "").strip()
        # 1) Groq Orpheus (pending model-terms acceptance on the org — one tap)
        if key_g:
            try:
                r = await self._http.post(
                    _GROQ_TTS_URL,
                    headers={"Authorization": f"Bearer {key_g}", "Content-Type": "application/json"},
                    json={
                        "model": settings.GROQ_TTS_MODEL,
                        "voice": settings.GROQ_TTS_VOICE,
                        "input": text,
                        "response_format": "wav",
                    },
                    timeout=httpx.Timeout(15.0, read=settings.TTS_TIMEOUT_S),
                )
                if r.status_code == 200 and r.content[:4] == b"RIFF" and len(r.content) > 1024:
                    return r.content, "wav"
                log.info("orpheus tts unavailable (%s)", r.status_code)
            except Exception as e:
                log.info("orpheus tts hiccup: %s", e)
        # 2) Cloudflare Workers AI aura-1 (rides the embeddings token)
        if key_cf and (settings.EMBED_API_BASE_URL or "").startswith("https://api.cloudflare.com"):
            try:
                run_url = settings.EMBED_API_BASE_URL.rstrip("/").replace("/ai/v1", "/ai/run")
                r = await self._http.post(
                    f"{run_url}/@cf/deepgram/aura-1",
                    headers={"Authorization": f"Bearer {key_cf}", "Content-Type": "application/json"},
                    json={"text": text, "encoding": "mp3"},
                    timeout=httpx.Timeout(15.0, read=settings.TTS_TIMEOUT_S),
                )
                if r.status_code == 200 and len(r.content) > 1024 and r.content[:3] == b"ID3" or (
                    r.status_code == 200 and len(r.content) > 1024 and r.content[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
                ):
                    return r.content, "mp3"
                log.info("cf aura tts unavailable (%s)", r.status_code)
            except Exception as e:
                log.info("cf aura tts hiccup: %s", e)
        # 3) unofficial gTTS (robotic but works keyless today — probed live)
        try:
            r = await self._http.get(
                _GTTS_URL,
                params={"ie": "UTF-8", "tl": "en", "client": "tw-ob", "q": text[:200]},
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"},
                timeout=httpx.Timeout(15.0, read=settings.TTS_TIMEOUT_S),
            )
            if r.status_code == 200 and len(r.content) > 1024 and r.content[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
                return r.content, "mp3"
            log.info("gtts unavailable (%s)", r.status_code)
        except Exception as e:
            log.info("gtts hiccup: %s", e)
        return None

    # ------------------------------------------------------------- reel
    async def _reel(self, prompt: str, opts: VideoOptions,
                    on_progress: Callable[[dict], None] | None = None) -> tuple[str, bool]:
        """🎬 Mood Reel: N FLUX scene stills → ffmpeg Ken Burns mp4 (xfade chain).

        Returns a /media/files/{name} URL (the routine caller archives to R2 for
        keeps — the media dir itself is janitored after MEDIA_TTL_HOURS)."""
        if not settings.REEL_ENABLED:
            raise VideoNotConfigured("Mood Reel is disabled (REEL_ENABLED=false).")
        exe = _ffmpeg_exe()
        if not exe:
            raise VideoNotConfigured("No ffmpeg on this host — reel composer unavailable.")
        duration = max(4, min(int(opts.duration or 6), 15))
        scenes = max(2, min(round(duration / 2.4), settings.REEL_MAX_SCENES))
        aspect = opts.aspect_ratio if opts.aspect_ratio in ("16:9", "9:16", "1:1") else "16:9"
        W, H = _reel_dims(aspect)
        out_w, out_h = (1280, 720) if aspect == "16:9" else ((720, 1280) if aspect == "9:16" else (960, 960))
        # 🎞️ v1.9.8: LLM storyboard beats (free brain, fail-open to deterministic)
        beat_prompts: list[str] | None = None
        narration: str | None = None
        if settings.REEL_STORYBOARD:
            if on_progress:
                on_progress({"stage": "storyboard", "done": 0, "total": 1})
            sb_scenes, narration = await self._storyboard(prompt, scenes)
            if sb_scenes:
                beat_prompts = sb_scenes
                scenes = len(beat_prompts)
            if on_progress:
                on_progress({"stage": "storyboard", "done": 1, "total": 1})
        if not beat_prompts:
            beat_prompts = [
                f"{prompt.strip()}, {REEL_BEATS[i % len(REEL_BEATS)]}, {STYLE_PRESETS.get(opts.style, STYLE_PRESETS['cinematic'])}"
                for i in range(scenes)
            ]
        if on_progress:
            on_progress({"stage": "scenes", "done": 0, "total": scenes})

        async def _fetch(i: int, p: str) -> bytes | None:
            import secrets

            seed = secrets.randbelow(10**9)
            url = (
                f"{settings.POLLINATIONS_IMAGE_URL}/{quote(p[:700])}"
                f"?width={W}&height={H}&seed={seed}&model={settings.POLLINATIONS_MODEL}&nologo=true&enhance=true"
            )
            for attempt in range(3):  # provider hiccups/rate sheds are normal — backoff retry
                try:
                    r = await self._http.get(url, timeout=httpx.Timeout(20.0, read=75.0))
                    if r.status_code == 200 and (r.headers.get("content-type") or "").startswith("image/") and r.content:
                        return r.content
                except Exception as e:
                    log.info("reel scene %d fetch hiccup: %s", i, e)
                await asyncio.sleep(1.2 + attempt * 1.3)
            return None

        shots = await asyncio.gather(*(_fetch(i, p) for i, p in enumerate(beat_prompts)))
        got = [(i, b) for i, b in enumerate(shots) if b]
        if on_progress:
            on_progress({"stage": "scenes", "done": len(got), "total": scenes})
        if not got:
            raise VideoGenerationError("Scene renders all came back short — try again in a moment.")
        # 🛟 Solo-scene rescue: a single good frame still makes a reel — mirror it
        # (hflip + opposite zoom direction reads as a deliberate cut, not a bug).
        # Measured live on Vercel: pollinations shed 2/3 scene fetches under rate
        # pressure and the whole generation used to die.
        flipped = [False] * len(got)
        if len(got) == 1:
            got.append(got[0])
            flipped.append(True)

        # 🔊 AI voiceover (fail-open: silent reel is still a reel)
        voice: tuple[bytes, str] | None = None
        if settings.REEL_NARRATION and narration:
            if on_progress:
                on_progress({"stage": "voice", "done": 0, "total": 1})
            voice = await self._narrate(narration)
            if on_progress:
                on_progress({"stage": "voice", "done": 1 if voice else 0, "total": 1})

        os.makedirs(settings.MEDIA_DIR, exist_ok=True)
        fade = REEL_FADE_S
        total = float(duration)
        per = (total + fade * (len(got) - 1)) / len(got)  # xfade overlaps eat `fade` per joint

        import uuid as _uuid

        with tempfile.TemporaryDirectory(prefix="mood-reel-") as tmp:
            for n, (_i, blob) in enumerate(got):
                with open(os.path.join(tmp, f"s{n}.jpg"), "wb") as f:
                    f.write(blob)
            inputs: list[str] = []
            for n in range(len(got)):
                inputs += ["-loop", "1", "-framerate", "24", "-t", f"{per:.3f}", "-i", os.path.join(tmp, f"s{n}.jpg")]
            if voice:  # narration rides in as the last input (index len(got))
                v_ext = "wav" if voice[1] == "wav" else "mp3"
                v_path = os.path.join(tmp, f"voice.{v_ext}")
                with open(v_path, "wb") as f:
                    f.write(voice[0])
                inputs += ["-i", v_path]
            # Ken Burns: alternating push-in / pull-out zoompan per scene
            labels: list[str] = []
            for n in range(len(got)):
                # classic accumulate-zoom Ken Burns (d=1, zoom persists) — commas escaped for the graph parser
                z_in = "zoompan=z='min(zoom+0.0010\\,1.14)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:fps=24"
                z_out = "zoompan=z='if(eq(on\\,1)\\,1.14\\,max(zoom-0.0010\\,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:fps=24"
                zexpr = z_in if n % 2 == 0 else z_out
                labels.append(
                    f"[{n}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                    f"crop={W}:{H}{',hflip' if flipped[n] else ''},{zexpr}:s={out_w}x{out_h},setsar=1,format=yuv420p[v{n}]"
                )
            # xfade chain (offsets accumulate minus the overlap)
            xf = f"[v0][v1]xfade=transition=fade:duration={fade}:offset={per - fade:.3f}[x1]"
            for n in range(2, len(got)):
                xf += f";[x{n-1}][v{n}]xfade=transition=fade:duration={fade}:offset={(per * n) - (fade * n):.3f}[x{n}]"
            graph = ";".join(labels) + ";" + xf
            last = f"[x{len(got)-1}]"
            if voice:  # gentle in/out fades, AAC mux under the picture
                graph += (
                    f";[{len(got)}:a]aresample=48000,volume=0.92,"
                    f"afade=t=in:st=0:d=0.4,afade=t=out:st={max(total - 0.8, 0.5):.3f}:d=0.8[aout]"
                )
            out_name = f"reel-{_uuid.uuid4().hex}.mp4"
            out_path = os.path.join(settings.MEDIA_DIR, out_name)
            if on_progress:
                on_progress({"stage": "compositing", "done": 0, "total": 1})
            cmd = [
                exe, "-y", *inputs,
                "-filter_complex", graph,
                "-map", last,
            ]
            if voice:
                cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "96k"]
            cmd += [
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-t", f"{total:.3f}", out_path,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            try:
                _, err = await asyncio.wait_for(proc.communicate(), timeout=150)
            except asyncio.TimeoutError:
                proc.kill()
                raise VideoGenerationError("Reel compositing timed out.")
            if proc.returncode != 0 or not os.path.exists(out_path):
                log.warning("reel ffmpeg failed: %s", (err or b"")[-400:])
                raise VideoGenerationError("Reel compositing failed — ffmpeg rejected the graph.")
            if on_progress:
                on_progress({"stage": "compositing", "done": 1, "total": 1})
        base = settings.BACKEND_PUBLIC_URL.rstrip("/")
        return f"{base}/api/v1/media/files/{out_name}", False

    # ------------------------------------------------------- pollinations
    async def _pollinations(self, prompt: str, opts: VideoOptions) -> tuple[str, bool]:
        key = (settings.POLLINATIONS_API_KEY or "").strip()
        if not key:
            raise VideoNotConfigured("Set POLLINATIONS_API_KEY for pollinations video.")
        model = settings.POLLINATIONS_VIDEO_MODEL or "wan-fast"
        dur = max(2, min(int(opts.duration or 6), 15))
        aspect = opts.aspect_ratio if opts.aspect_ratio in ("16:9", "9:16") else "16:9"
        url = (
            f"{settings.POLLINATIONS_VIDEO_URL.rstrip('/')}/{quote(prompt[:900])}"
            f"?model={model}&duration={dur}&aspectRatio={aspect}"
        )
        headers = {"Authorization": f"Bearer {key}"}
        r = await self._http.get(url, headers=headers, timeout=httpx.Timeout(30.0, read=210.0))
        if r.status_code in (401, 403):
            raise VideoNotConfigured(f"Pollinations rejected the key ({r.status_code}).")
        if r.status_code in (402, 429):
            raise VideoGenerationError(f"Pollinations video quota/balance: {r.text[:160]}")
        if r.status_code >= 400:
            raise VideoGenerationError(f"Pollinations video failed ({r.status_code}): {r.text[:160]}")
        if (r.headers.get("content-type") or "").startswith("video/"):
            # serve bytes via the /media/files janitor so downstream (soundtrack,
            # archiving) always sees a plain URL
            os.makedirs(settings.MEDIA_DIR, exist_ok=True)
            import uuid as _uuid

            name = f"polli-{_uuid.uuid4().hex}.mp4"
            with open(os.path.join(settings.MEDIA_DIR, name), "wb") as f:
                f.write(r.content)
            return f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/api/v1/media/files/{name}", False
        data = r.json() if r.content else {}
        if u := _dig_url(data):
            return u, False
        raise VideoGenerationError(f"Unexpected pollinations video shape: {str(data)[:160]}")

    # --------------------------------------------------------------- xai
    async def _xai(self, prompt: str, opts: VideoOptions,
                   image: dict | None = None) -> tuple[str, bool]:
        if not settings.XAI_API_KEY:
            raise VideoNotConfigured("Set XAI_API_KEY for video generation.")
        base = settings.XAI_BASE_URL.rstrip("/")
        headers = {"Authorization": f"Bearer {settings.XAI_API_KEY}", "Content-Type": "application/json"}
        compiled = compile_prompt(prompt, opts)
        full_payload = build_video_payload(settings.MODEL_VIDEO, compiled, opts, image)
        # Send the full professional payload; if the provider rejects extended
        # params, retry lean rather than fail the user's generation.
        r = await self._http.post(f"{base}/videos/generations", headers=headers, json=full_payload)
        if image and r.status_code in (400, 422):
            # provider/build rejected the image frame — drop it and tell the caller
            log.info("video provider rejected image input — falling back to text-only")
            r = await self._http.post(f"{base}/videos/generations", headers=headers,
                                      json=build_video_payload(settings.MODEL_VIDEO, compiled, opts))
            image = None
        if r.status_code == 400 or r.status_code == 422:
            log.info("video provider rejected extended params — retrying lean payload")
            r = await self._http.post(
                f"{base}/videos/generations",
                headers=headers,
                json={"model": settings.MODEL_VIDEO, "prompt": compiled},
            )
        if r.status_code in (401, 403):
            raise VideoNotConfigured("xAI rejected the request — video access on your key/plan may be missing.")
        if r.status_code == 402:
            raise VideoNotConfigured("xAI key has no credits — funding it flips true Grok video on.")
        if r.status_code >= 400:
            raise VideoGenerationError(f"Video request failed ({r.status_code}): {r.text[:200]}")
        data = r.json()

        if url := _dig_url(data):
            return url, bool(image)

        # Async task pattern: poll the request id until the video is ready
        rid = data.get("request_id") or data.get("id") or (data.get("task") or {}).get("id")
        if not rid:
            raise VideoGenerationError(f"Unexpected video response shape: {str(data)[:200]}")
        waited = 0
        while waited < settings.VIDEO_MAX_WAIT_SECONDS:
            await asyncio.sleep(3)
            waited += 3
            g = await self._http.get(f"{base}/videos/generations/{rid}", headers=headers)
            if g.status_code >= 400:
                continue  # transient — keep polling until the deadline
            payload = g.json()
            if url := _dig_url(payload):
                return url, bool(image)
            status = str(payload.get("status", "")).lower()
            if status in ("failed", "error", "cancelled"):
                raise VideoGenerationError(f"Video generation {status}: {str(payload)[:200]}")
        raise VideoGenerationError(f"Video generation timed out after {settings.VIDEO_MAX_WAIT_SECONDS}s")


video = VideoService()
