"""Realtime voice session over WebSocket (Voice Studio v2).

Protocol (JSON text frames + binary audio frames):
  client → server:  binary chunks (webm/opus while recording)
                    {type:"end_turn"}         finished speaking → process
                    {"type":"interrupt"}       barge-in: stop reasoning/TTS output
  server → client:  {type:"ready"}
                    {type:"transcript", text}
                    { "type":"delta", text }     reply tokens, live
                    {type":"audio", seq, audio_b64, final}   sentence-chunked TTS
                    {type":"turn_done", conversation_id}
                    {type":"error", message} · {type":"interrupted"}

Design: one WS per session keeps turns snappy (no re-negotiation); the reply
streams as it generates; TTS is synthesized per-sentence (bounded concurrency,
sent in order) so speech starts seconds before the full reply would finish.
"""

import asyncio
import base64
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError

from ...core.security import decode_token
from ...db.models import Message, User
from ...db.session import SessionLocal
from ...services.llm import friendly_ai_error, llm
from ...services.memory import extract_and_store
from ...services.metering import estimate_tokens, record_usage
from ...services.recall import update_conversation_summary
from ...services.voice import VoiceNotConfigured, voice
from .chat import build_messages, generate_title, get_or_create_conversation

router = APIRouter()
log = logging.getLogger(__name__)

MAX_TURN_BYTES = 25 * 1024 * 1024
MAX_TTS_SENTENCES = 14

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def sentences_of(text: str) -> list[str]:
    """Split a reply into speakable sentence-ish chunks."""
    parts = [p.strip() for p in _SENT_SPLIT.split(text.replace("\n", " ")) if p.strip()]
    out: list[str] = []
    for p in parts:
        while len(p) > 600:  # very long sentence → hard-chunk for TTS stability
            out.append(p[:600])
            p = p[600:]
        out.append(p)
    return out[:MAX_TTS_SENTENCES]


class VoiceSession:
    def __init__(self, ws: WebSocket, user_id: str):
        self.ws = ws
        self.user_id = user_id
        self.buf = bytearray()
        self.task: asyncio.Task | None = None  # current turn pipeline
        self.interrupted = asyncio.Event()

    async def send(self, obj: dict) -> None:
        try:
            await self.ws.send_text(json.dumps(obj, default=str))
        except Exception:
            self.interrupted.set()

    async def run_turn(self, conversation_id: str | None) -> None:
        data = bytes(self.buf)
        self.buf = bytearray()
        self.interrupted.clear()
        async with SessionLocal() as db:
            try:
                user = await db.get(User, self.user_id)
                if not user:
                    await self.send({"type": "error", "message": "User not found"})
                    return
                try:
                    transcript = await voice.transcribe(data, "voice.webm")
                except VoiceNotConfigured as e:
                    await self.send({"type": "error", "message": str(e)})
                    return
                if not transcript:
                    await self.send({"type": "error", "message": "Couldn't transcribe — try again"})
                    return
                await self.send({"type": "transcript", "text": transcript})

                conv, created = await get_or_create_conversation(db, user, conversation_id, transcript)
                messages, model, _ = await build_messages(db, user, conv.id, transcript, [], False, created)

                full: list[str] = []
                usage: dict = {}
                async for ev in llm.stream_chat(messages, model=model):
                    if self.interrupted.is_set():
                        await self.send({"type": "interrupted"})
                        return
                    if ev["type"] == "delta":
                        full.append(ev["text"])
                        await self.send({"type": "delta", "text": ev["text"]})
                    elif ev["type"] == "usage":
                        usage = ev.get("usage") or {}
                reply = ("".join(full) or "(no response)").strip()

                db.add(Message(conversation_id=conv.id, role="user", content=transcript))
                db.add(Message(conversation_id=conv.id, role="assistant", content=reply, meta={"mode": "voice_rt"}))
                conv.updated_at = datetime.now(timezone.utc)
                await db.commit()

                tok = (
                    {"tokens_in": int(usage.get("prompt_tokens", 0)), "tokens_out": int(usage.get("completion_tokens", 0)), "estimated": False}
                    if usage
                    else estimate_tokens(transcript, reply)
                )
                await record_usage(user.id, "voice", model, **tok)
                asyncio.create_task(extract_and_store(user.id, transcript, reply, user.plan))
                asyncio.create_task(update_conversation_summary(user.id, conv.id))
                if created:
                    asyncio.create_task(generate_title(conv.id, transcript))

                # Sentence-chunked TTS: synthesize with bounded concurrency, send in order
                sentences = sentences_of(reply)
                sem = asyncio.Semaphore(4)

                async def tts(i: int, s: str) -> bytes | None:
                    async with sem:
                        if self.interrupted.is_set():
                            return None
                        try:
                            return await voice.synthesize(s)
                        except Exception as e:
                            log.warning("TTS chunk %s failed: %s", i, e)
                            return None

                audios = await asyncio.gather(*(tts(i, s) for i, s in enumerate(sentences)))
                for i, audio in enumerate(audios):
                    if self.interrupted.is_set():
                        await self.send({"type": "interrupted"})
                        return
                    if audio:
                        await self.send(
                            {
                                "type": "audio",
                                "seq": i,
                                "final": i == len(audios) - 1,
                                "audio_b64": base64.b64encode(audio).decode(),
                            }
                        )
                await self.send({"type": "turn_done", "conversation_id": conv.id})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("voice ws turn failed")
                await self.send({"type": "error", "message": friendly_ai_error(e)})

    async def handle(self, obj: dict) -> None:
        t = obj.get("type")
        if t == "end_turn":
            if not self.buf:
                await self.send({"type": "error", "message": "No audio captured"})
                return
            if self.task and not self.task.done():
                self.interrupted.set()  # barge the old turn before starting the new one
                self.task.cancel()
            cid = obj.get("conversation_id")
            self.task = asyncio.create_task(self.run_turn(cid if isinstance(cid, str) else None))
        elif t == "interrupt":
            self.interrupted.set()
            if self.task and not self.task.done():
                self.task.cancel()


@router.websocket("/ws")
async def voice_ws(ws: WebSocket, token: str = Query(...)):
    try:
        uid = decode_token(token).get("sub")
    except JWTError:
        await ws.close(code=4401)
        return
    if not uid:
        await ws.close(code=4401)
        return
    await ws.accept()
    session = VoiceSession(ws, uid)
    await session.send({"type": "ready"})
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes"):
                if len(session.buf) < MAX_TURN_BYTES:
                    session.buf.extend(msg["bytes"])
            elif msg.get("text"):
                try:
                    await session.handle(json.loads(msg["text"]))
                except json.JSONDecodeError:
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        if session.task and not session.task.done():
            session.task.cancel()
