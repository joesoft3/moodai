"""Media generation: professional text-to-video (plan-capped, metered)
plus a prompt enhancer powered by the fast model."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import User
from ...db.session import get_db
from ...schemas import VideoEnhanceRequest, VideoRequest
from ...services.llm import friendly_ai_error, llm
from ...services.media import STYLE_PRESETS, VideoGenerationError, VideoNotConfigured, VideoOptions, video
from ...services.metering import PLAN_LIMITS, count_today, record_usage
from ..deps import enforce_rate_limit, get_current_user

router = APIRouter()

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
    await record_usage(user.id, "video", settings.MODEL_VIDEO)
    return {
        "url": url,
        "prompt": req.prompt,
        "model": settings.MODEL_VIDEO,
        "meta": {"duration": opts.duration, "aspect_ratio": opts.aspect_ratio, "quality": opts.quality, "style": opts.style},
    }


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
