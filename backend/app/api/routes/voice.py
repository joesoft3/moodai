"""Voice pipeline: STT, TTS, and full voice conversations (audio in → audio + text out)."""

import base64
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import Message, User
from ...db.session import get_db
from ...schemas import TTSRequest
from ...services.llm import friendly_ai_error, llm
from ...services.memory import extract_and_store
from ...services.metering import estimate_tokens, record_usage
from ...services.recall import update_conversation_summary
from ...services.voice import VoiceNotConfigured, voice
from ..deps import enforce_rate_limit, get_current_user
from .chat import build_messages, generate_title, get_or_create_conversation

router = APIRouter()
log = logging.getLogger(__name__)

MAX_VOICE_BYTES = 25 * 1024 * 1024


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    data = await file.read()
    if len(data) > MAX_VOICE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Audio too large (max 25 MB)")
    try:
        text = await voice.transcribe(data, file.filename or "audio.webm")
    except VoiceNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    return {"text": text}


@router.post("/tts")
async def tts(req: TTSRequest, user: User = Depends(get_current_user)):
    try:
        audio = await voice.synthesize(req.text)
    except VoiceNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    return Response(content=audio, media_type="audio/mpeg")


@router.post("/chat")
async def voice_chat(
    bg: BackgroundTasks,
    file: UploadFile = File(...),
    conversation_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await enforce_rate_limit(f"voice:{user.id}", settings.CHAT_RATE_LIMIT_PER_MIN)
    data = await file.read()
    if len(data) > MAX_VOICE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Audio too large (max 25 MB)")

    try:
        transcript = await voice.transcribe(data, file.filename or "voice.webm")
    except VoiceNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    if not transcript:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Could not transcribe audio")

    conv, created = await get_or_create_conversation(db, user, conversation_id, transcript)
    messages, model, _ = await build_messages(db, user, conv.id, transcript, [], False, created)

    usage: dict = {}
    try:
        reply = await llm.complete(messages, model=model, temperature=0.7, usage_out=usage)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, friendly_ai_error(e))
    tok = (
        {
            "tokens_in": int(usage.get("prompt_tokens", 0)),
            "tokens_out": int(usage.get("completion_tokens", 0)),
            "estimated": False,
        }
        if usage
        else estimate_tokens(transcript, reply)
    )
    await record_usage(user.id, "voice", model, **tok)

    db.add(Message(conversation_id=conv.id, role="user", content=transcript))
    db.add(Message(conversation_id=conv.id, role="assistant", content=reply))
    conv.updated_at = datetime.now(timezone.utc)
    await db.commit()

    audio = b""
    try:
        audio = await voice.synthesize(reply)
    except Exception as e:
        log.warning("TTS failed (returning text only): %s", e)

    bg.add_task(extract_and_store, user.id, transcript, reply, user.plan)
    bg.add_task(update_conversation_summary, user.id, conv.id)
    if created:
        bg.add_task(generate_title, conv.id, transcript)

    return {
        "conversation_id": conv.id,
        "transcript": transcript,
        "reply": reply,
        "audio_b64": base64.b64encode(audio).decode() if audio else "",
    }
