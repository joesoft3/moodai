"""Media generation: professional text-to-video (plan-capped, metered),
Cinema Sound (AI voiceover + ambience muxed via ffmpeg), a prompt enhancer
powered by the fast model, and public serving of the muxed files."""

import json
import os
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import Film, User
from ...db.session import get_db
from ...schemas import StoryboardRequest, VideoEnhanceRequest, VideoRequest
from ...services import film_jobs, soundtrack, storyboard
from ...services.llm import friendly_ai_error, llm
from ...services.media import STYLE_PRESETS, VideoGenerationError, VideoNotConfigured, VideoOptions, video
from ...services.metering import PLAN_LIMITS, count_today, record_usage
from ...services.voice import VoiceNotConfigured
from ..deps import enforce_rate_limit, get_current_user

router = APIRouter()

SERVED_NAME_RE = re.compile(r"^[a-f0-9]{32}(_p\.jpg|\.mp4)$")

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
                music=req.music,
                tempo=req.tempo,
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
    if audio_out != "none":
        await record_usage(user.id, "media_sound", settings.TTS_MODEL)  # Analytics v3: sound attach rate
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expired or unknown media (muxed files live 24h)")
    media_type = "image/jpeg" if name.endswith("_p.jpg") else "video/mp4"
    return FileResponse(path, media_type=media_type)


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


def _film_out(f: Film) -> dict:
    url = ""
    if f.filename:
        url = f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/api/v1/media/files/{f.filename}"
    elif f.fallback_url:
        url = f.fallback_url
    poster = f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/api/v1/media/files/{f.poster}" if f.poster else ""
    try:
        scenes = json.loads(f.scenes_json or "[]")
    except json.JSONDecodeError:
        scenes = []
    return {
        "id": f.id,
        "prompt": f.prompt,
        "status": f.status,
        "progress": f.progress,
        "scene_count": f.scene_count,
        "scene_seconds": f.scene_seconds,
        "aspect_ratio": f.aspect,
        "quality": f.quality,
        "style": f.style,
        "audio": f.audio,
        "voice": f.voice_id,
        "music": f.music,
        "tempo": f.tempo,
        "subtitles": bool(f.subtitles),
        "url": url,
        "poster": poster,
        "script": f.script or None,
        "note": f.note or None,
        "scenes": scenes,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }
    try:
        scenes = json.loads(f.scenes_json or "[]")
    except json.JSONDecodeError:
        scenes = []
    return {
        "id": f.id,
        "prompt": f.prompt,
        "status": f.status,
        "progress": f.progress,
        "scene_count": f.scene_count,
        "scene_seconds": f.scene_seconds,
        "aspect_ratio": f.aspect,
        "quality": f.quality,
        "style": f.style,
        "audio": f.audio,
        "voice": f.voice_id,
        "music": f.music,
        "tempo": f.tempo,
        "subtitles": bool(f.subtitles),
        "url": url,
        "script": f.script or None,
        "note": f.note or None,
        "scenes": scenes,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


def _film_kwargs(f: Film) -> dict:
    """Rebuild the launch payload from a persisted row (resume path)."""
    custom = []
    try:
        for sc in json.loads(f.scenes_json or "[]"):
            line = sc.get("shot", "")
            if sc.get("narration"):
                line += f" || {sc['narration']}"
            custom.append(line)
    except json.JSONDecodeError:
        pass
    return {
        "user_id": f.user_id,
        "prompt": f.prompt,
        "scene_count": f.scene_count,
        "scene_seconds": f.scene_seconds,
        "opts": {
            "duration": f.scene_seconds,
            "aspect_ratio": f.aspect,
            "quality": f.quality,
            "style": f.style,
            "negative_prompt": "",
        },
        "audio": f.audio,
        "voice_name": f.voice_id,
        "custom_scenes": custom or None,
        "subtitles": bool(f.subtitles),
        "music": f.music,
        "tempo": f.tempo,
    }


@router.post("/videos/storyboard", status_code=status.HTTP_202_ACCEPTED)
async def generate_storyboard_endpoint(
    req: StoryboardRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """🎬 Multi-scene film — ASYNC: answers in ~1s; poll GET /media/films/{id}.
    Quota pre-check blocks over-cap runs before anything is spent; scenes render
    2-wide in parallel; every milestone persists to the films row."""
    await enforce_rate_limit(f"video:{user.id}", 2)
    custom = storyboard.parse_custom_scenes(req.custom_scenes or [], req.scene_seconds) if req.custom_scenes else None
    scene_count = len(custom) if custom else req.scenes
    cap = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"])["video_day"]
    if cap:
        used = await count_today(db, user.id, "video")
        if used + scene_count > cap:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"This storyboard needs {scene_count} of your {cap} daily videos — only {max(cap - used, 0)} left "
                f"on the {user.plan} plan. Try fewer scenes or upgrade.",
            )
    # Preflight: don't burn N paid generations if the voice provider is absent.
    audio = req.audio
    note = None
    if audio != "none" and not settings.OPENAI_API_KEY:
        audio = "none"
        note = "Voice provider not configured (set OPENAI_API_KEY) — filming silent."

    film = Film(
        id=uuid.uuid4().hex,
        user_id=user.id,
        prompt=req.prompt.strip(),
        scenes_json=json.dumps(
            [{"shot": sc.shot, "narration": sc.narration} for sc in custom] if custom else []
        ),
        status="rendering",
        progress=0,
        scene_count=scene_count,
        scene_seconds=req.scene_seconds,
        aspect=req.aspect_ratio,
        quality=req.quality,
        style=req.style if req.style in STYLE_PRESETS else "cinematic",
        audio=audio,
        voice_id=req.voice,
        music=req.music,
        tempo=req.tempo,
        subtitles=req.subtitles,
        note=note or "",
    )
    db.add(film)
    await db.commit()

    film_jobs.launch(
        film.id,
        {
            "user_id": user.id,
            "prompt": film.prompt,
            "scene_count": scene_count,
            "scene_seconds": req.scene_seconds,
            "opts": {
                "duration": req.scene_seconds,
                "aspect_ratio": req.aspect_ratio,
                "quality": req.quality,
                "style": film.style,
                "negative_prompt": req.negative_prompt,
            },
            "audio": audio,
            "voice_name": req.voice,
            "custom_scenes": req.custom_scenes,
            "subtitles": req.subtitles,
            "music": req.music,
            "tempo": req.tempo,
        },
    )
    return {"job": "storyboard", "film": _film_out(film)}


@router.get("/films")
async def list_films(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(Film).where(Film.user_id == user.id).order_by(Film.created_at.desc()).limit(24)
        )
    ).scalars().all()
    return {"films": [_film_out(f) for f in rows], "jobs_running": film_jobs.running_count()}


async def _own_film(db: AsyncSession, user: User, fid: str) -> Film:
    film = await db.get(Film, fid)
    if not film or film.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Film not found")
    return film


@router.get("/films/{fid}")
async def get_film(fid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return _film_out(await _own_film(db, user, fid))


@router.post("/films/{fid}/resume")
async def resume_film(fid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Relaunch a film stuck 'rendering' (e.g. server restarted mid-render)."""
    film = await _own_film(db, user, fid)
    if film.status != "rendering":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Film is {film.status} — nothing to resume")
    film_jobs.launch(film.id, _film_kwargs(film))
    return {"resumed": film.id}


@router.delete("/films/{fid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_film(fid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    film = await _own_film(db, user, fid)
    await db.delete(film)
    await db.commit()
    return None


@router.get("/public/films/{fid}")
async def public_film(fid: str, db: AsyncSession = Depends(get_db)):
    """Public read of a FINISHED film — powers the /f/{id} share page SEO + player.

    No auth (film ids are 128-bit unguessable, matching the public media files).
    Rendering/failed films stay private — a share link exists only when the film did."""
    film = await db.get(Film, fid)
    if not film or film.status != "done" or not (film.filename or film.fallback_url):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No shareable film with that id")
    full = _film_out(film)
    return {
        "id": film.id,
        "title": (film.prompt or "A Mood AI film").strip()[:90],
        "url": full["url"],
        "poster": full["poster"],
        "scenes": film.scene_count,
        "duration_seconds": film.scene_count * film.scene_seconds,
        "aspect_ratio": film.aspect,
        "audio": film.audio,
        "style": film.style,
        "created_at": full["created_at"],
    }
