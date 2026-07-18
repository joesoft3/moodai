"""Plugin tools: OpenAI-format function schemas + HTTP executors against the
user's connected apps. Tool results are injected into the chat context; side
effects (send email, create event/issue) only happen when the model calls them
after the user asked for it."""

import base64
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import PluginConnection
from .oauth import access_token
from .registry import get_provider

log = logging.getLogger(__name__)
_http = httpx.AsyncClient(timeout=20.0)


class PluginError(Exception):
    pass


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


def _s(v: str, desc: str) -> dict:
    return {"type": "string", "description": desc or v}


def _i(desc: str, default: int) -> dict:
    return {"type": "integer", "description": desc, "default": default}


TOOLS_BY_PROVIDER: dict[str, list[dict]] = {
    "gmail": [
        _tool(
            "gmail_list_messages",
            "Search the user's Gmail inbox. Returns From/Subject/Date/snippet for matching messages.",
            {
                "query": _s("query", "Gmail search query, e.g. 'is:unread' or 'from:boss@acme.com' (empty = latest)"),
                "max_results": _i("How many messages to return (1-10)", 5),
            },
        ),
        _tool(
            "gmail_send_message",
            "Send an email from the user's Gmail account. Only call when the user explicitly asked to send mail.",
            {
                "to": _s("to", "Recipient email address"),
                "subject": _s("subject", "Email subject line"),
                "body": _s("body", "Plain-text email body"),
            },
            ["to", "subject", "body"],
        ),
    ],
    "google_calendar": [
        _tool(
            "calendar_list_events",
            "List upcoming events on the user's primary Google Calendar.",
            {
                "days_ahead": _i("How many days ahead to look (1-30)", 7),
                "max_results": _i("Max events to return (1-20)", 10),
            },
        ),
        _tool(
            "calendar_create_event",
            "Create an event on the user's primary Google Calendar. Only call when the user explicitly asked to schedule something.",
            {
                "summary": _s("summary", "Event title"),
                "start": _s("start", "Start time as ISO 8601 (e.g. 2026-07-18T14:00:00Z)"),
                "end": _s("end", "End time as ISO 8601"),
                "description": _s("description", "Optional event description"),
            },
            ["summary", "start", "end"],
        ),
    ],
    "github": [
        _tool(
            "github_list_repos",
            "List the user's GitHub repositories, most recently updated first.",
            {"max_results": _i("Max repos to return (1-20)", 10)},
        ),
        _tool(
            "github_list_issues",
            "List issues on a GitHub repository ('owner/name' or just 'name' for the user's own repos).",
            {
                "repo": _s("repo", "Repository as 'owner/name' or 'name'"),
                "state": _s("state", "open | closed | all"),
                "max_results": _i("Max issues to return (1-20)", 10),
            },
            ["repo"],
        ),
        _tool(
            "github_create_issue",
            "Create a GitHub issue. Only call when the user explicitly asked to create one.",
            {
                "repo": _s("repo", "Repository as 'owner/name' or 'name'"),
                "title": _s("title", "Issue title"),
                "body": _s("body", "Issue body (markdown)"),
            },
            ["repo", "title"],
        ),
    ],
}

TOOL_PROVIDER: dict[str, str] = {t["function"]["name"]: p for p, tools in TOOLS_BY_PROVIDER.items() for t in tools}

# Write tools NEVER execute inside the chat loop — they become PendingActions the
# user must approve in the UI (human-in-the-loop).
WRITE_TOOLS: set[str] = {"gmail_send_message", "calendar_create_event", "github_create_issue"}

# Built-in tools: no OAuth connection needed, always offered in plugin mode.
BUILTIN_TOOLS: list[dict] = [
    _tool(
        "run_python_code",
        "Execute Python code in a sandboxed subprocess and return stdout/stderr. Use for "
        "calculations, data wrangling, verifying logic. 8s timeout, no network.",
        {"code": _s("code", "Complete Python 3 script to run (print results to stdout)")},
        ["code"],
    )
]


def tool_schemas_for(providers: list[str]) -> list[dict]:
    out: list[dict] = list(BUILTIN_TOOLS)
    for p in providers:
        out += TOOLS_BY_PROVIDER.get(p, [])
    return out


async def _token_for(db: AsyncSession, user_id: str, provider_key: str) -> tuple[str, PluginConnection]:
    spec = get_provider(provider_key)
    conn = await db.scalar(
        select(PluginConnection).where(
            PluginConnection.user_id == user_id, PluginConnection.provider == provider_key
        )
    )
    if not conn:
        raise PluginError(f"{spec.name} is not connected — connect it in Settings → Plugins.")
    return await access_token(db, spec, conn), conn


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _clip(value: int, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except Exception:
        return default


# ---------------------------------------------------------------- Gmail
async def _gmail_list(spec, token, args) -> dict:
    n = _clip(args.get("max_results", 5), 1, 10, 5)
    h = {"Authorization": f"Bearer {token}"}
    q = (args.get("query") or "").strip()
    r = await _http.get(
        f"{spec.api_base}/users/me/messages", headers=h, params={"maxResults": n, **({"q": q} if q else {})}
    )
    if r.status_code != 200:
        raise PluginError(f"Gmail list failed ({r.status_code}): {r.text[:160]}")
    out = []
    for ref in r.json().get("messages", [])[:n]:
        m = await _http.get(
            f"{spec.api_base}/users/me/messages/{ref['id']}",
            headers=h,
            params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
        )
        if m.status_code != 200:
            continue
        mj = m.json()
        hdrs = {x["name"]: x["value"] for x in (mj.get("payload", {}).get("headers") or [])}
        out.append({"from": hdrs.get("From"), "subject": hdrs.get("Subject"), "date": hdrs.get("Date"), "snippet": mj.get("snippet", "")[:220]})
    return {"messages": out, "count": len(out)}


async def _gmail_send(spec, token, args) -> dict:
    raw = f"To: {args['to']}\r\nSubject: {args['subject']}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{args.get('body', '')}"
    b64 = base64.urlsafe_b64encode(raw.encode()).decode()
    r = await _http.post(
        f"{spec.api_base}/users/me/messages/send",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"raw": b64},
    )
    if r.status_code not in (200, 202):
        raise PluginError(f"Gmail send failed ({r.status_code}): {r.text[:160]}")
    return {"sent": True, "to": args["to"], "subject": args["subject"], "id": r.json().get("id")}


# ---------------------------------------------------------------- Calendar
async def _cal_list(spec, token, args) -> dict:
    days = _clip(args.get("days_ahead", 7), 1, 30, 7)
    n = _clip(args.get("max_results", 10), 1, 20, 10)
    now = datetime.now(timezone.utc)
    r = await _http.get(
        f"{spec.api_base}/calendars/primary/events",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "timeMin": now.isoformat(),
            "timeMax": (now + timedelta(days=days)).isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": n,
        },
    )
    if r.status_code != 200:
        raise PluginError(f"Calendar list failed ({r.status_code}): {r.text[:160]}")
    events = [
        {
            "summary": e.get("summary"),
            "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"),
            "end": (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date"),
            "location": e.get("location"),
        }
        for e in r.json().get("items", [])
    ]
    return {"events": events, "count": len(events), "window_days": days}


async def _cal_create(spec, token, args) -> dict:
    body = {
        "summary": args["summary"],
        "start": {"dateTime": args["start"]},
        "end": {"dateTime": args["end"]},
    }
    if args.get("description"):
        body["description"] = args["description"]
    r = await _http.post(
        f"{spec.api_base}/calendars/primary/events",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
    )
    if r.status_code not in (200, 201):
        raise PluginError(f"Calendar create failed ({r.status_code}): {r.text[:160]}")
    j = r.json()
    return {"created": True, "summary": j.get("summary"), "link": j.get("htmlLink")}


# ---------------------------------------------------------------- GitHub
def _gh_repo(args: dict, conn: PluginConnection) -> str:
    repo = (args.get("repo") or "").strip().strip("/")
    if "/" not in repo:
        owner = conn.account or ""
        if not owner:
            raise PluginError("Repository must be given as 'owner/name'.")
        repo = f"{owner}/{repo}"
    return repo


async def _gh_repos(spec, token, args, conn) -> dict:
    n = _clip(args.get("max_results", 10), 1, 20, 10)
    r = await _http.get(
        f"{spec.api_base}/user/repos", headers=_gh_headers(token), params={"sort": "updated", "per_page": n}
    )
    if r.status_code != 200:
        raise PluginError(f"GitHub repos failed ({r.status_code}): {r.text[:160]}")
    return {
        "repos": [
            {"name": x["full_name"], "private": x.get("private"), "language": x.get("language"), "stars": x.get("stargazers_count"), "updated": x.get("updated_at")}
            for x in r.json()
        ]
    }


async def _gh_issues(spec, token, args, conn) -> dict:
    repo = _gh_repo(args, conn)
    n = _clip(args.get("max_results", 10), 1, 20, 10)
    state = args.get("state") if args.get("state") in ("open", "closed", "all") else "open"
    r = await _http.get(
        f"{spec.api_base}/repos/{repo}/issues", headers=_gh_headers(token), params={"state": state, "per_page": n}
    )
    if r.status_code != 200:
        raise PluginError(f"GitHub issues failed ({r.status_code}): {r.text[:160]}")
    return {
        "repo": repo,
        "issues": [
            {"number": x["number"], "title": x["title"], "state": x["state"], "user": (x.get("user") or {}).get("login"), "url": x.get("html_url")}
            for x in r.json()
            if "pull_request" not in x
        ],
    }


async def _gh_create_issue(spec, token, args, conn) -> dict:
    repo = _gh_repo(args, conn)
    r = await _http.post(
        f"{spec.api_base}/repos/{repo}/issues",
        headers=_gh_headers(token),
        json={"title": args["title"], "body": args.get("body") or ""},
    )
    if r.status_code != 201:
        raise PluginError(f"GitHub create issue failed ({r.status_code}): {r.text[:160]}")
    j = r.json()
    return {"created": True, "repo": repo, "number": j.get("number"), "url": j.get("html_url")}


_EXEC = {
    "gmail_list_messages": lambda spec, tok, a, c: _gmail_list(spec, tok, a),
    "gmail_send_message": lambda spec, tok, a, c: _gmail_send(spec, tok, a),
    "calendar_list_events": lambda spec, tok, a, c: _cal_list(spec, tok, a),
    "calendar_create_event": lambda spec, tok, a, c: _cal_create(spec, tok, a),
    "github_list_repos": _gh_repos,
    "github_list_issues": lambda spec, tok, a, c: _gh_issues(spec, tok, a, c),
    "github_create_issue": lambda spec, tok, a, c: _gh_create_issue(spec, tok, a, c),
}


async def execute_tool(db: AsyncSession, user_id: str, name: str, args: dict) -> dict:
    # built-ins execute without any provider connection
    if name == "run_python_code":
        from ..sandbox import SandboxError, run_python

        try:
            return await run_python(str(args.get("code") or ""))
        except SandboxError as e:
            raise PluginError(str(e))
    if name == "social_post":
        # 📣 Social autopilot v1: approving hands back the drafted caption +
        # film link (X/YouTube connectors plug in later — same staged pipeline).
        network = str(args.get("network") or "x")
        caption = str(args.get("caption") or "")
        url = str(args.get("url") or "")
        if not caption or not url:
            raise PluginError("social_post needs caption + url")
        return {
            "posted": False,
            "network": network,
            "caption": caption,
            "url": url,
            "how_to": "Approved — copy the caption and post it with your film link. "
                      "Auto-posting lands when the X/YouTube connectors ship.",
        }
    provider = TOOL_PROVIDER.get(name)
    if not provider:
        raise PluginError(f"Unknown tool: {name}")
    spec = get_provider(provider)
    token, conn = await _token_for(db, user_id, provider)
    try:
        return await _EXEC[name](spec, token, args, conn)
    except PluginError:
        raise
    except Exception as e:
        raise PluginError(f"{name} failed: {str(e)[:200]}")
