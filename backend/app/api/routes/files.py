import asyncio
import logging
import os
import re
import uuid

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import FileAsset, Message, User
from ...db.session import get_db
from ...services.file_extract import allowed_mime, detect_mime, extract_text
from ...services.llm import friendly_ai_error, llm
from ...services.metering import estimate_tokens, record_usage
from ...services.rag import delete_document_chunks, index_document
from ...services.video_analysis import analyze_video_file, have_ffmpeg, video_ext, VideoAnalysisError
from ...services.voice import VoiceNotConfigured, voice
from ..deps import enforce_rate_limit, get_current_user
from .chat import generate_title, get_or_create_conversation

router = APIRouter()
log = logging.getLogger(__name__)

AUDIO_EXT_BY_MIME = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mp4": "m4a",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/flac": "flac",
}
AUDIO_EXTS = {"mp3", "wav", "m4a", "webm", "ogg", "opus", "flac"}


def detect_audio_format(filename: str, content_type: str | None) -> str | None:
    """Canonical audio container from extension first, else declared MIME. None = not audio."""
    ext = os.path.splitext((filename or "").lower())[1].lstrip(".")
    if ext in AUDIO_EXTS:
        return ext
    return AUDIO_EXT_BY_MIME.get((content_type or "").split(";")[0].strip().lower())


def _persist_upload(user_id: str, filename: str, data: bytes) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename or "upload")
    path = os.path.join(settings.UPLOAD_DIR, user_id, f"{uuid.uuid4().hex}_{safe}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


ANALYZE_SYSTEM_PROMPT = (
    "You analyze audio for the user from its transcription. Structure the answer:\n"
    "1. \U0001f4dd Transcript / Lyrics (verbatim, as complete as the source allows)\n"
    "2. \U0001f50e What it is (speech, song, podcast, notes\u2026) + language\n"
    "3. \U0001f3af Analysis: key themes, mood/energy, intent, anything notable\n"
    "4. \U0001f5c2 If it is a song: artist/title guess with confidence, genre, era-sound, musical traits\n"
    "Be honest about gaps \u2014 mark unintelligible spots with [inaudible]."
)


async def _audio_transcript_and_analysis(
    data: bytes, filename: str, fmt: str, user_prompt: str
) -> tuple[str, str, dict]:
    """Whisper transcript + structured LLM analysis. Raises HTTP errors for the route."""
    try:
        transcript = await voice.transcribe(data, filename)
    except VoiceNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    if not transcript:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Could not transcribe this audio — try a clearer recording.")
    usage: dict = {}
    try:
        analysis = await llm.complete(
            [
                {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Audio file: {filename} ({fmt})\n"
                        f"User request: {user_prompt or 'analyze'}\n\n"
                        f"TRANSCRIPTION:\n{transcript[:12000]}"
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=2000,
            usage_out=usage,
        )
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, friendly_ai_error(e))
    return transcript, analysis, usage


def asset_out(a: FileAsset) -> dict:
    return {
        "id": a.id,
        "filename": a.filename,
        "mime": a.mime,
        "size_bytes": a.size_bytes,
        "extracted": bool(a.extracted_text),
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.post("", status_code=201)
async def upload_file(
    bg: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    mime = detect_mime(file.filename or "file", file.content_type)
    if not allowed_mime(mime):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Unsupported file type: {mime or file.filename}")
    data = await file.read()
    # 🧰 Plan-aware cap — Pro uploads 2× larger files (free 25 MB → pro 50 MB)
    from ...services.metering import PLAN_LIMITS

    upload_cap = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"]).get("upload_mb", settings.MAX_UPLOAD_MB)
    if len(data) > upload_cap * 1024 * 1024:
        msg = f"File too large (max {upload_cap} MB on the {user.plan} plan)"
        if user.plan != "pro":
            msg += f" — Pro raises it to {PLAN_LIMITS['pro'].get('upload_mb', 50)} MB"
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, msg)

    safe = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "upload")
    path = os.path.join(settings.UPLOAD_DIR, user.id, f"{uuid.uuid4().hex}_{safe}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)

    text = None
    if not mime.startswith("image/"):
        text = await asyncio.to_thread(extract_text, path, mime)

    asset = FileAsset(
        user_id=user.id,
        filename=file.filename or safe,
        mime=mime,
        path=path,
        size_bytes=len(data),
        extracted_text=text,
    )
    db.add(asset)
    await db.commit()
    # Doc-RAG: chunk + embed in the background so it's searchable from any chat
    if text and not mime.startswith("image/"):
        bg.add_task(index_document, user.id, asset.id, asset.filename, text)
    return asset_out(asset)


@router.post("/analyze-audio")
async def analyze_audio_file(
    bg: BackgroundTasks,
    file: UploadFile = File(...),
    prompt: str = Form(
        "Transcribe this audio, then give a concise summary of what it contains."
    ),
    conversation_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """🎵 Upload an audio/music file → transcribed (music → lyrics) and analyzed by the
    LLM in one shot: full transcript/lyrics + analysis, optionally landed in a chat.
    Rate-limited and size-capped (MAX_AUDIO_UPLOAD_MB)."""
    await enforce_rate_limit(f"audiofile:{user.id}", 5)
    fmt = detect_audio_format(file.filename or "", file.content_type)
    if not fmt:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Upload an audio file — mp3, wav, m4a, webm, ogg, opus or flac.",
        )
    data = await file.read()
    if len(data) > settings.MAX_AUDIO_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Audio too large (max {settings.MAX_AUDIO_UPLOAD_MB} MB)"
        )
    if len(data) < 800:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That audio file looks empty or corrupt.")

    filename = file.filename or f"audio.{fmt}"
    user_prompt = (prompt or "").strip()[:500]
    transcript, analysis, usage = await _audio_transcript_and_analysis(data, filename, fmt, user_prompt)

    # persist so the Files manager can list / re-analyze / download it later
    asset = FileAsset(
        user_id=user.id,
        filename=filename,
        mime=f"audio/{fmt}",
        path=_persist_upload(user.id, filename, data),
        size_bytes=len(data),
        extracted_text=transcript[: settings.MAX_FILE_CHARS],
    )
    db.add(asset)

    tok = (
        {
            "tokens_in": int(usage.get("prompt_tokens", 0)),
            "tokens_out": int(usage.get("completion_tokens", 0)),
            "estimated": False,
        }
        if usage
        else estimate_tokens(transcript + user_prompt, analysis)
    )
    await record_usage(user.id, "voice", settings.MODEL_FAST, **tok)

    # Always land the analysis in a conversation (created on demand) so it's resumable
    conv, created = await get_or_create_conversation(db, user, conversation_id, f"🎵 {filename[:60]}")
    db.add(
        Message(
            conversation_id=conv.id,
            user_id=user.id,
            role="user",
            content=f"🎵 **{filename}** — {user_prompt or 'transcribe & analyze'}",
        )
    )
    db.add(
        Message(
            conversation_id=conv.id,
            role="assistant",
            content=analysis,
            meta={"mode": "audio_analysis", "filename": filename, "format": fmt},
        )
    )
    conv.updated_at = datetime.now(timezone.utc)
    await db.commit()
    conv_id = conv.id
    if created:
        bg.add_task(generate_title, conv.id, f"Audio analysis of {filename}")

    return {
        "file_id": asset.id,
        "filename": filename,
        "format": fmt,
        "size_bytes": len(data),
        "transcript": transcript,
        "analysis": analysis,
        "conversation_id": conv_id,
    }


@router.post("/analyze-video")
async def analyze_video_upload(
    bg: BackgroundTasks,
    file: UploadFile = File(...),
    prompt: str = Form("Summarize what happens in this video, scene by scene."),
    conversation_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """🎬 Upload a video (mp4/mov/webm/mkv) → ffmpeg samples frames + audio → Grok
    vision captions + Whisper transcript → scene-by-scene AI summary, landed in chat."""
    await enforce_rate_limit(f"videofile:{user.id}", 3)
    filename = file.filename or "video.mp4"
    ext = video_ext(filename)
    if not ext:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a video file — mp4, mov, webm, mkv or m4v."
        )
    data = await file.read()
    if len(data) > settings.MAX_VIDEO_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Video too large (max {settings.MAX_VIDEO_UPLOAD_MB} MB)"
        )
    if len(data) < 2048:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That video file looks empty or corrupt.")
    if not have_ffmpeg():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Video analysis unavailable — ffmpeg not installed on the backend image."
        )

    user_prompt = (prompt or "").strip()[:500]
    try:
        extracted = await analyze_video_file(data, ext)
    except VideoAnalysisError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    captions: list[str] = extracted["captions"]

    transcript = ""
    if extracted["audio_wav_bytes"]:
        try:
            transcript = await voice.transcribe(extracted["audio_wav_bytes"], "audio.wav")
        except VoiceNotConfigured:
            transcript = ""  # STT unconfigured — frames-only analysis still works

    usage: dict = {}
    try:
        analysis = await llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You summarize videos from sampled-frame captions and (optional) audio transcript. "
                        "Structure the answer:\n"
                        "1. \U0001f3ac Scene-by-scene (chronological, referencing what is visible)\n"
                        "2. \U0001f50e What this video is + setting/people\n"
                        "3. \U0001f4ac Speech highlights (if a transcript is present)\n"
                        "4. \U0001f3af Overall: purpose, mood, anything notable or anomalous\n"
                        "Note when sampling may have missed moments between frames."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Video: {filename} ({ext}, {extracted['frames']} frames sampled)\n"
                        f"User request: {user_prompt or 'summarize'}\n\n"
                        f"FRAME CAPTIONS:\n" + "\n".join(f"- {c}" for c in captions)[:4000] +
                        f"\n\nTRANSCRIPT (may be empty):\n{transcript[:8000]}"
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=2200,
            usage_out=usage,
        )
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, friendly_ai_error(e))

    tok = (
        {
            "tokens_in": int(usage.get("prompt_tokens", 0)),
            "tokens_out": int(usage.get("completion_tokens", 0)),
            "estimated": False,
        }
        if usage
        else estimate_tokens("\n".join(captions) + transcript + user_prompt, analysis)
    )
    await record_usage(user.id, "video", settings.MODEL_VISION, **tok)

    asset = FileAsset(
        user_id=user.id,
        filename=filename,
        mime=f"video/{ext}",
        path=_persist_upload(user.id, filename, data),
        size_bytes=len(data),
        extracted_text=(transcript or "\n".join(captions))[: settings.MAX_FILE_CHARS],
    )
    db.add(asset)

    conv, created = await get_or_create_conversation(db, user, conversation_id, f"\U0001f3ac {filename[:60]}")
    db.add(
        Message(
            conversation_id=conv.id,
            user_id=user.id,
            role="user",
            content=f"\U0001f3ac **{filename}** — {user_prompt or 'analyze this video'}",
        )
    )
    db.add(
        Message(
            conversation_id=conv.id,
            role="assistant",
            content=analysis,
            meta={"mode": "video_analysis", "filename": filename, "format": ext, "frames": extracted["frames"]},
        )
    )
    conv.updated_at = datetime.now(timezone.utc)
    await db.commit()
    if created:
        bg.add_task(generate_title, conv.id, f"Video analysis of {filename}")

    return {
        "file_id": asset.id,
        "filename": filename,
        "format": ext,
        "size_bytes": len(data),
        "frames": extracted["frames"],
        "captions": captions,
        "transcript": transcript,
        "analysis": analysis,
        "conversation_id": conv.id,
    }


@router.get("/{fid}/download")
async def download_file(fid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    asset = await db.get(FileAsset, fid)
    if not asset or asset.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    if not os.path.exists(asset.path):
        raise HTTPException(status.HTTP_410_GONE, "File content is no longer on disk")
    return FileResponse(asset.path, filename=asset.filename, media_type=asset.mime or "application/octet-stream")


@router.post("/{fid}/reanalyze")
async def reanalyze_file(
    fid: str,
    prompt: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-run AI analysis on a stored audio/video asset from the Files manager."""
    asset = await db.get(FileAsset, fid)
    if not asset or asset.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    if not os.path.exists(asset.path):
        raise HTTPException(status.HTTP_410_GONE, "File content is no longer on disk")
    data = open(asset.path, "rb").read()
    user_prompt = (prompt or "").strip()[:500]

    fmt = detect_audio_format(asset.filename, asset.mime)
    vext = video_ext(asset.filename)
    if fmt:
        await enforce_rate_limit(f"audiofile:{user.id}", 5)
        transcript, analysis, usage = await _audio_transcript_and_analysis(data, asset.filename, fmt, user_prompt)
        kind, model = "voice", settings.MODEL_FAST
    elif vext:
        await enforce_rate_limit(f"videofile:{user.id}", 3)
        if not have_ffmpeg():
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Video analysis unavailable — ffmpeg missing")
        try:
            extracted = await analyze_video_file(data, vext)
        except VideoAnalysisError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
        transcript = ""
        if extracted["audio_wav_bytes"]:
            try:
                transcript = await voice.transcribe(extracted["audio_wav_bytes"], "audio.wav")
            except VoiceNotConfigured:
                transcript = ""
        usage2: dict = {}
        caps = "\n".join(f"- {c}" for c in extracted["captions"])
        try:
            analysis = await llm.complete(
                [
                    {"role": "system", "content": "Summarize this video scene-by-scene from frame captions + transcript, then overall takeaways."},
                    {"role": "user", "content": f"Video: {asset.filename}\nUser request: {user_prompt or 'summarize'}\n\nCAPTIONS:\n{caps[:4000]}\n\nTRANSCRIPT:\n{transcript[:8000]}"},
                ],
                temperature=0.3,
                max_tokens=2000,
                usage_out=usage2,
            )
        except Exception as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, friendly_ai_error(e))
        usage = usage2
        kind, model = "video", settings.MODEL_VISION
    else:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only audio/video files can be re-analyzed")

    tok = (
        {
            "tokens_in": int(usage.get("prompt_tokens", 0)),
            "tokens_out": int(usage.get("completion_tokens", 0)),
            "estimated": False,
        }
        if usage
        else estimate_tokens(transcript + user_prompt, analysis)
    )
    await record_usage(user.id, kind, model, **tok)
    asset.extracted_text = (transcript or analysis)[: settings.MAX_FILE_CHARS]
    await db.commit()
    return {"file_id": asset.id, "transcript": transcript, "analysis": analysis}


@router.get("")
async def list_files(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(select(FileAsset).where(FileAsset.user_id == user.id).order_by(FileAsset.created_at.desc()))
    ).scalars().all()
    return [asset_out(a) for a in rows]


@router.delete("/{fid}", status_code=204)
async def delete_file(fid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    asset = await db.get(FileAsset, fid)
    if not asset or asset.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    await db.delete(asset)
    await db.commit()
    await delete_document_chunks(fid)  # best-effort vector cleanup
    try:
        os.remove(asset.path)
    except OSError:
        pass
    return Response(status_code=204)
