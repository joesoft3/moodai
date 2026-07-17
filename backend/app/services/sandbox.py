"""Best-effort local code execution for the built-in `run_python_code` tool.

Safety posture (honest): the code runs in a short-lived child process of the
backend container, isolated mode (`python -I`), minimal environment, CPU and
address-space rlimits, hard wall-clock timeout. It is NOT a hardened security
boundary (no seccomp / no network isolation / no FS jailing). For production,
front this with gVisor / Firecracker / nsjail, or a remote sandbox service —
the seam is this one function.
"""

import asyncio
import logging
import os
import sys
import tempfile

from ..config import settings

log = logging.getLogger(__name__)


class SandboxError(Exception):
    pass


def _limits() -> None:  # runs in the child (preexec_fn) — POSIX only
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (settings.SANDBOX_TIMEOUT + 2, settings.SANDBOX_TIMEOUT + 2))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))  # 512 MB
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    except Exception:
        pass


def _clip(s: str) -> str:
    return s[: settings.SANDBOX_MAX_OUTPUT] + ("\n…[truncated]" if len(s) > settings.SANDBOX_MAX_OUTPUT else "")


async def run_python(code: str) -> dict:
    """Execute Python code, capturing stdout/stderr. Never raises on user-code failure."""
    if not settings.SANDBOX_ENABLED:
        raise SandboxError("Code sandbox is disabled (SANDBOX_ENABLED=false).")
    if len(code) > 20_000:
        return {"ok": False, "error": "Code too long (max 20,000 chars).", "stdout": "", "stderr": ""}

    tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
    try:
        tmp.write(code)
        tmp.close()
        kwargs: dict = {}
        if os.name == "posix":
            kwargs["preexec_fn"] = _limits
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",  # isolated: no user site-packages, no env PYTHONPATH
            "-u",
            tmp.name,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONHASHSEED": "0"},
            **kwargs,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=settings.SANDBOX_TIMEOUT)
            timed_out = False
        except asyncio.TimeoutError:
            proc.kill()
            out, err = await proc.communicate()
            timed_out = True
        return {
            "ok": proc.returncode == 0 and not timed_out,
            "exit_code": proc.returncode,
            "timed_out": timed_out,
            "stdout": _clip((out or b"").decode(errors="replace")),
            "stderr": _clip((err or b"").decode(errors="replace")),
        }
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
