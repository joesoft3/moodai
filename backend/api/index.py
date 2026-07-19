"""Vercel serverless entry point.

Vercel's Python runtime auto-detects any file under `api/` that exposes an
ASGI app — every request is rewritten here by vercel.json, so the whole
FastAPI surface (chat, media, designer, plugins, admin…) runs as one
function. Importing from the repo's `app/` package works because Vercel
installs `requirements.txt` from the project root and puts the root on
sys.path; the path insert below is a belt-and-braces for the `vercel dev`
CLI and local smoke tests.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402  (path setup must precede the import)

__all__ = ["app"]
