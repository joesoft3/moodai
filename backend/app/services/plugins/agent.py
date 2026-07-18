"""Plugin tool-call loop: decide + execute calls against the user's connected
apps. Read-only tools (incl. the built-in code sandbox) execute immediately.
WRITE tools (send email, create event/issue) are converted into PendingActions
that must be approved by the user in the chat UI — human-in-the-loop by design.
Returns a compact context block the main chat pass answers from."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import PendingAction, PluginConnection, User
from ..llm import llm
from ..notify import notify_approval_needed
from .tools import PluginError, WRITE_TOOLS, execute_tool, tool_schemas_for

log = logging.getLogger(__name__)

RUNNER_PROMPT = (
    "You are Mood’s plugin runner. The user has connected external apps (Gmail, Calendar, GitHub) "
    "and a Python sandbox. Call tools ONLY when the request clearly needs data or actions from "
    "these apps (e.g. 'check my inbox', 'what's on my calendar', 'create a GitHub issue', "
    "'compute this'). If the request is a normal question, call no tools. "
    "Compose write actions exactly as the user wants them — they will review and approve before "
    "anything is sent or created."
)


async def connected_providers(db: AsyncSession, user_id: str) -> list[str]:
    rows = (
        await db.execute(select(PluginConnection.provider).where(PluginConnection.user_id == user_id))
    ).scalars().all()
    return [p for p in rows if p]


def _display_args(args: dict) -> dict:
    """Args as shown in the approval card (long values clipped)."""
    return {k: (str(v)[:160] + ("…" if len(str(v)) > 160 else "") if isinstance(v, str) else v) for k, v in args.items()}


async def resolve_plugins(
    db: AsyncSession, user: User, message: str, conversation_id: str | None = None
) -> tuple[str | None, list[dict], list[dict]]:
    """Run up to PLUGIN_MAX_CALLS tool rounds.
    Returns (context_block, executed_call_log, pending_actions)."""
    providers = await connected_providers(db, user.id)
    schemas = tool_schemas_for(providers)

    messages = [
        {"role": "system", "content": RUNNER_PROMPT},
        {
            "role": "user",
            "content": f"Current date/time (UTC): {datetime.now(timezone.utc).isoformat(timespec='minutes')}\n\nUSER REQUEST: {message}",
        },
    ]
    calls: list[dict] = []         # executed calls (ok/failed), for the 🧩 pills
    pending: list[dict] = []       # write actions awaiting approval, for the confirm cards
    results: list[str] = []

    for _ in range(settings.PLUGIN_MAX_CALLS):
        try:
            msg = await llm.complete_with_tools(messages, schemas)
        except Exception as e:
            log.warning("plugin tool round failed: %s", e)
            break
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            break
        messages.append(msg.model_dump(exclude_none=True))
        for tc in tool_calls[:6]:  # hard cap per round
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
                if not isinstance(args, dict):
                    args = {}
            except Exception:
                args = {}

            if name in WRITE_TOOLS:
                # human-in-the-loop: stage the action, do NOT execute
                action = PendingAction(
                    user_id=user.id, conversation_id=conversation_id, tool=name, args=args, status="pending"
                )
                db.add(action)
                await db.commit()
                notify_approval_needed(user.id, name)  # push: no-op unless FCM env set
                pending.append({"id": action.id, "name": name, "args": _display_args(args)})
                payload = json.dumps(
                    {"status": "awaiting_user_confirmation", "action": name, "note": "The user reviews and approves this in the app UI."}
                )
            else:
                try:
                    result = await execute_tool(db, user.id, name, args)
                    calls.append({"name": name, "ok": True})
                except PluginError as e:
                    result = {"error": str(e)}
                    calls.append({"name": name, "ok": False})
                payload = json.dumps(result, default=str)[:3500]
                if name == "run_python_code":
                    results.append(f"### {name}\n{payload}")

            results.append(f"### {name}\n{payload}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})

    if not calls and not pending:
        return None, [], []

    parts: list[str] = []
    if calls:
        parts.append(
            "Plugin results from the user's connected apps (fresh, real data — use them to answer):\n\n"
            + "\n\n".join(results)
        )
    if pending:
        staged = "\n".join(f"- {p['name']}({json.dumps(p['args'])[:240]})" for p in pending)
        parts.append(
            "The following WRITE actions were PREPARED but NOT executed — the user must approve "
            "them in the app UI (an approval card is shown under your reply). Tell the user to "
            "review and confirm. NEVER claim these were sent or created:\n" + staged
        )
    context = "\n\n".join(parts)
    return context, calls, pending
