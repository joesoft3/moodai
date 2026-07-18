"""Async film jobs — storyboards render in the background; the API answers in
~1s and the client polls the Film row (survives page refresh, powers /films).

Design: one asyncio task per film, in-process (same uvicorn worker — no extra
Railway service needed). Progress lives in the Film row (`progress` scenes
done of `scene_count`); the task registry only guards against GC.
"""

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select

from ..config import settings
from ..db.models import Film
from ..db.session import SessionLocal
from . import storyboard
from .media import VideoOptions
from .metering import record_usage

log = logging.getLogger(__name__)

_TASKS: dict[str, asyncio.Task] = {}


def launch(film_id: str, kwargs: dict[str, Any]) -> None:
    """Start (or no-op if already running) the render for `film_id`."""
    if film_id in _TASKS and not _TASKS[film_id].done():
        return
    task = asyncio.create_task(_run(film_id, kwargs))
    _TASKS[film_id] = task
    task.add_done_callback(lambda t: _TASKS.pop(film_id, None))


async def _set(film_id: str, defaults: dict) -> None:
    async with SessionLocal() as s:
        film = await s.get(Film, film_id)
        if film:
            for k, v in defaults.items():
                setattr(film, k, v)
            await s.commit()


async def _run(film_id: str, kw: dict) -> None:
    """Full pipeline; every milestone persisted so polling just reads the row.

    Metering: scenes are paid *at render time* — on failure we meter exactly the
    number of scenes that actually rendered (progress), on success scene_count."""
    rendered = {"n": 0}
    outcome_audio = "none"
    try:
        def on_scene(done: int, total: int) -> None:
            rendered["n"] = max(rendered["n"], done)
            try:
                asyncio.get_running_loop().create_task(_set(film_id, {"progress": done}))
            except RuntimeError:
                pass

        def on_plan(scenes: list) -> None:
            payload = json.dumps([{"shot": sc.shot, "narration": sc.narration, "voice": sc.voice} for sc in scenes])
            try:
                asyncio.get_running_loop().create_task(_set(film_id, {"scenes_json": payload}))
            except RuntimeError:
                pass

        result, note, fallback_url = await storyboard.generate_storyboard(
            kw["prompt"],
            scene_count=kw["scene_count"],
            scene_seconds=kw["scene_seconds"],
            opts=VideoOptions(**kw["opts"]),
            audio=kw["audio"],
            voice_name=kw["voice_name"],
            custom_scenes=kw.get("custom_scenes"),
            subtitles=kw["subtitles"],
            music=kw["music"],
            tempo=kw["tempo"],
            dialogue=kw.get("dialogue", False),
            voice_b=kw.get("voice_b", "onyx"),
            on_scene=on_scene,
            on_plan=on_plan,
        )
        if result:
            outcome_audio = result.mode
            # ⭐ Brand Kit: stamp the saved logo onto the hero-frame poster
            if kw.get("brand_logo_file") and result.poster:
                try:
                    from pathlib import Path as _Path
                    from ..config import settings as _cfg
                    from . import designer as _dzn
                    branded = await _dzn.stamp_logo_on_image(
                        _Path(_cfg.MEDIA_DIR) / result.poster, kw["brand_logo_file"]
                    )
                    if branded:
                        log.info("film %s poster branded with kit logo", film_id[:8])
                except Exception as e:  # never fail a finished film over branding
                    log.info("poster brand stamp skipped: %s", e)
            await _set(
                film_id,
                {
                    "status": "done",
                    "filename": result.filename,
                    "poster": result.poster,
                    "audio": result.mode,
                    "subtitles": bool(result.subtitles),
                    "scenes_json": json.dumps([{"shot": s.shot, "narration": s.narration, "voice": s.voice} for s in result.scenes]),
                    "script": " / ".join(s.narration for s in result.scenes if s.narration.strip()),
                    "note": note or "",
                    "progress": kw["scene_count"],
                    "brand_name": kw.get("brand_name", "") or "",
                },
            )
        else:  # stitch failed → fall back to scene 1 (a finished clip)
            await _set(
                film_id,
                {
                    "status": "done",
                    "fallback_url": fallback_url or "",
                    "audio": "none",
                    "note": note or "Stitch failed — delivered scene 1.",
                    "progress": kw["scene_count"],
                },
            )
        # 🔔 completion push (best effort — never derails the job)
        try:
            from . import notify

            title = "🎬 Your film is ready" if result else "🎬 Film rendered (scene 1 kept)"
            body_txt = (kw["prompt"] or "Your storyboard").strip()[:90]
            await notify.notify_user(
                kw.get("user_id", ""), "film_ready", title, body_txt, {"kind": "film", "screen": "/films"}
            )
        except Exception:
            pass
    except Exception as e:  # noqa: BLE001 — a failed film must never kill the worker loop
        log.warning("film %s failed: %s: %s", film_id, type(e).__name__, e)
        await _set(film_id, {"status": "failed", "note": f"{type(e).__name__}: {str(e)[:300]}"})
    finally:
        for _ in range(rendered["n"]):
            await record_usage(kw.get("user_id", ""), "video", settings.MODEL_VIDEO)
        if outcome_audio != "none":
            await record_usage(kw.get("user_id", ""), "media_sound", settings.TTS_MODEL)


def running_count() -> int:
    return sum(1 for t in _TASKS.values() if not t.done())


async def resumable_orphans() -> list[Film]:
    """Films stuck 'rendering' (e.g. process restarted mid-render) — retryable."""
    async with SessionLocal() as s:
        rows = (
            await s.execute(select(Film).where(Film.status == "rendering").order_by(Film.created_at.desc()))
        ).scalars().all()
        return [f for f in rows if f.id not in _TASKS]
