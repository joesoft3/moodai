"""Media generation: professional text-to-video (plan-capped, metered),
Cinema Sound (AI voiceover + ambience muxed via ffmpeg), a prompt enhancer
powered by the fast model, and public serving of the muxed files."""

import os
import re

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import User
from ...db.session import get_db
from ...schemas import VideoEnhanceRequest, VideoRequest
from ...services import soundtrack
from ...services.llm import friendly_ai_error, llm
from ...services.media import STYLE_PRESETS, VideoGenerationError, VideoNotConfigured, VideoOptions, video
from ...services.metering import PLAN_LIMITS, count_today, record_usage
from ...services.voice import VoiceNotConfigured
from ..deps import enforce_rate_limit, get_current_user

router = APIRouter()

SERVED_NAME_RE = re.compile(r"^[a-f0-9]{32}\.mp4$")

ENHANCER_PROMPT = """You are a professional AI-video prompt engineer (Veo/Sora/Grok Video grade).
Rewrite the user's rough idea into ONE dense, production-ready video prompt covering:
subject & action · environment & set design · camera shot & movement · lighting & color grade ·
style & texture · motion dynamics. Single paragraph, present tense, no preamble, ≤120 words.
Include an aspect-agnostic description (framing handled separately)."""


@router.post("/videos")
async def generate_video(
    req: VideoRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await enforce_rate_limit(f"video:{user.id}", 2)
    cap = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"])["video_day"]
    if cap and await count_today(db, user.id, "video") >= cap:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Daily video limit reached for the {user.plan} plan ({cap}/day). Upgrade for more.",
        )
    opts = VideoOptions(
        duration=req.duration,
        aspect_ratio=req.aspect_ratio,
        quality=req.quality,
        style=req.style if req.style in STYLE_PRESETS else "cinematic",
        negative_prompt=req.negative_prompt,
    )
    try:
        url = await video.generate(req.prompt.strip(), opts)
    except VideoNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except VideoGenerationError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    # --------------------------------------------------------- Cinema Sound
    audio_out = "none"
    script = None
    note = None
    if req.audio != "none":
        try:
            result = await soundtrack.add_soundtrack(
                url,
                seconds=opts.duration,
                voice_name=req.voice,
                narration=req.narration,
                prompt=req.prompt.strip(),
                with_bed=req.audio == "cinema",
            )
        except VoiceNotConfigured:
            result = None
            note = "Voice provider not configured (set OPENAI_API_KEY) — delivered without sound."
        except Exception as e:  # download/probe hiccup — never fail the generation
            result = None
            note = f"Soundtrack mix failed ({type(e).__name__}) — delivered the original video."
        else:
            if result:
                url = f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/api/v1/media/files/{result.filename}"
                audio_out = result.mode
                script = result.script
            elif not note:
                note = "ffmpeg unavailable on this server — delivered without sound."
    await record_usage(user.id, "video", settings.MODEL_VIDEO)
    return {
        "url": url,
        "prompt": req.prompt,
        "model": settings.MODEL_VIDEO,
        "audio": audio_out,
        "script": script,
        "note": note,
        "meta": {"duration": opts.duration, "aspect_ratio": opts.aspect_ratio, "quality": opts.quality, "style": opts.style},
    }


@router.get("/files/{name}")
async def serve_muxed_video(name: str):
    """Public, unguessable-id serving of muxed videos (24h TTL janitor).

    Public so <video> tags and mobile players can stream without auth headers;
    filenames are 128-bit random hex, never enumerable."""
    if not SERVED_NAME_RE.match(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    path = os.path.join(settings.MEDIA_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expired or unknown video (muxed files live 24h)")
    return FileResponse(path, media_type="video/mp4")


@router.post("/videos/enhance")
async def enhance_prompt(req: VideoEnhanceRequest, user: User = Depends(get_current_user)):
    """✨ One-click professional rewrite of a rough video idea."""
    await enforce_rate_limit(f"videnh:{user.id}", 10)
    try:
        enhanced = await llm.complete(
            [
                {"role": "system", "content": ENHANCER_PROMPT},
                {"role": "user", "content": req.prompt.strip()},
            ],
            temperature=0.6,
            max_tokens=260,
        )
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, friendly_ai_error(e))
    enhanced = enhanced.strip().strip('"')
    if not enhanced:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Enhancer returned nothing")
    return {"enhanced": enhanced}
