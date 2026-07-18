"""Voice service: Whisper STT + TTS via any OpenAI-compatible endpoint.

Seam for swapping providers (ElevenLabs, Deepgram, faster-whisper + edge-tts)
without touching routes or the client.
"""

from openai import AsyncOpenAI

from ..config import settings


class VoiceNotConfigured(Exception):
    pass


class VoiceService:
    _client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            if not settings.OPENAI_API_KEY:
                raise VoiceNotConfigured(
                    "Voice provider not configured — set OPENAI_API_KEY (Whisper STT + TTS)."
                )
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
        return self._client

    async def transcribe(self, data: bytes, filename: str) -> str:
        transcript = await self.client.audio.transcriptions.create(
            model=settings.WHISPER_MODEL, file=(filename or "audio.webm", data)
        )
        return (transcript.text or "").strip()

    async def synthesize(self, text: str, voice_name: str | None = None) -> bytes:
        resp = await self.client.audio.speech.create(
            model=settings.TTS_MODEL, voice=voice_name or settings.TTS_VOICE, input=text[:4000]
        )
        return resp.content


voice = VoiceService()
