"""Video file analysis: ffmpeg samples frames + audio track → Grok vision captions +
Whisper transcript → an LLM scene-by-scene summary. Needs ffmpeg on the backend
image (installed in backend/Dockerfile); degrades gracefully without it."""

import asyncio
import base64
import glob
import logging
import os
import shutil
import tempfile

from ..config import settings
from .llm import llm

log = logging.getLogger(__name__)

VIDEO_EXTS = {"mp4", "mov", "webm", "mkv", "m4v"}


class VideoAnalysisError(Exception):
    pass


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


async def _run(cmd: list[str], timeout: int = 120) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise VideoAnalysisError(f"ffmpeg timed out on: {' '.join(cmd[:3])}")
    if proc.returncode != 0:
        raise VideoAnalysisError(f"ffmpeg failed: {err.decode(errors='ignore')[:200]}")


async def _caption_frame(path: str) -> str | None:
    try:
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        text = await llm.complete(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Describe this video frame in 1-2 sentences: subjects, setting, action, any on-screen text.",
                        },
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            model=settings.MODEL_VISION,
            max_tokens=160,
        )
        return (text or "").strip() or None
    except Exception as e:
        log.warning("frame caption failed: %s", e)
        return None


async def analyze_video_file(data: bytes, ext: str) -> dict:
    """Extract + understand. Returns {frames, captions, audio_wav_bytes}."""
    if not have_ffmpeg():
        raise VideoAnalysisError("ffmpeg isn't installed on the backend image — video analysis unavailable")
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, f"input.{ext}")
        with open(src, "wb") as fh:
            fh.write(data)
        try:
            # one frame every ~5s, capped, small enough for fast vision tokens
            await _run(
                [
                    "ffmpeg", "-y", "-i", src,
                    "-vf", "fps=1/5,scale=768:-2",
                    "-frames:v", str(settings.VIDEO_ANALYSIS_FRAMES),
                    "-q:v", "4",
                    os.path.join(td, "frame%02d.jpg"),
                ],
                120,
            )
        except VideoAnalysisError as e:
            raise VideoAnalysisError(f"Could not read this video ({e})")
        frame_paths = sorted(glob.glob(os.path.join(td, "frame*.jpg")))

        wav = os.path.join(td, "audio.wav")
        audio_bytes = b""
        try:
            await _run(["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-t", "720", "-f", "wav", wav], 120)
            if os.path.getsize(wav) > 8000:
                audio_bytes = open(wav, "rb").read()
        except (VideoAnalysisError, OSError):
            audio_bytes = b""  # silent video — frames only

        captions = [c for c in [await _caption_frame(p) for p in frame_paths] if c]
        return {"frames": len(frame_paths), "captions": captions, "audio_wav_bytes": audio_bytes}


def video_ext(filename: str) -> str | None:
    ext = os.path.splitext((filename or "").lower())[1].lstrip(".")
    return ext if ext in VIDEO_EXTS else None
