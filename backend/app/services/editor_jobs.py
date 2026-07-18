"""✂️ Edit jobs — in-process task registry (same lightweight pattern as film_jobs):
submit → 202 → poll /media/edits/{id} until status leaves 'rendering'."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from ..config import settings
from ..db.models import Edit
from ..db.session import SessionLocal
from . import editor
from .metering import record_usage

log = logging.getLogger(__name__)
_TASKS: dict[str, asyncio.Task] = {}


def launch(edit_id: str, kwargs: dict[str, Any]) -> None:
    if edit_id in _TASKS and not _TASKS[edit_id].done():
        return
    task = asyncio.create_task(_run(edit_id, kwargs))
    _TASKS[edit_id] = task
    task.add_done_callback(lambda t: _TASKS.pop(edit_id, None))


async def _set(edit_id: str, **kv) -> None:
    async with SessionLocal() as s:
        row = await s.get(Edit, edit_id)
        if row:
            for k, v in kv.items():
                setattr(row, k, v)
            await s.commit()


async def _run(edit_id: str, kw: dict) -> None:
    try:
        plan = await editor.plan_edit(kw["instruction"])
        await _set(edit_id, plan_json=json.dumps(plan.__dict__, default=str))
        name, notes = await editor.run_edit(
            Path(settings.MEDIA_DIR) / kw["src_name"], plan, brand_logo_file=kw.get("brand_logo_file", "")
        )
        await _set(edit_id, status="done", out_name=name, note=" · ".join(notes))
        await record_usage(kw["user_id"], "edit", "ffmpeg+llm")
    except Exception as e:
        log.exception("edit %s failed", edit_id[:8])
        await _set(edit_id, status="failed", note=str(e)[:400])
