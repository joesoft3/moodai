"""Video generation behind a provider seam (VIDEO_PROVIDER).

Professional features:
- Options: duration / aspect ratio / quality / style / negative prompt
- A prompt compiler layers style presets + quality tags onto the user's idea
- Lean-retry: if the provider rejects extended params, we retry with the
  minimal payload instead of failing the user's generation.

Default "xai": async task pattern (POST → immediate URL or polled request id).
Other providers (Runway, Pika, Luma) plug in as one method + one env value.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

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

NEGATIVE_DEFAULT = "morphing, flicker, warped faces, distorted hands, text artifacts, watermark, jitter"


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


class VideoService:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0))

    async def generate(self, prompt: str, opts: VideoOptions,
                       image: dict | None = None) -> tuple[str, bool]:
        provider = settings.VIDEO_PROVIDER.lower()
        if provider == "xai":
            return await self._xai(prompt, opts, image=image)
        raise VideoNotConfigured(
            f"VIDEO_PROVIDER={provider} not available yet — supported today: xai. "
            "The seam is services/media.py (Runway/Pika/Luma = one method + one env value)."
        )

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

