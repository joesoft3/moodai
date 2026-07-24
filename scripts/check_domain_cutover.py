#!/usr/bin/env python3
"""Quick custom-domain cutover check.

Usage:
  python3 scripts/check_domain_cutover.py 5boost.me api.5boost.me
"""

from __future__ import annotations

import socket
import ssl
import sys
import urllib.error
import urllib.request


def resolve(host: str) -> tuple[bool, str]:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips = sorted({info[4][0] for info in infos})
        return True, ", ".join(ips)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def fetch(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "MoodAI-Domain-Check/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl.create_default_context()) as r:
            body = r.read(160).decode("utf-8", "ignore").replace("\n", " ")
            return True, f"HTTP {r.status} · {body[:120]}"
    except urllib.error.HTTPError as e:
        try:
            body = e.read(160).decode("utf-8", "ignore").replace("\n", " ")
        except Exception:
            body = ""
        return False, f"HTTP {e.code} · {body[:120]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/check_domain_cutover.py <app-domain> <api-domain>")
        return 2

    app_domain = sys.argv[1].strip()
    api_domain = sys.argv[2].strip()

    print(f"== DNS ==")
    for host in (app_domain, f"www.{app_domain}", api_domain):
        ok, msg = resolve(host)
        print(f"{host:24} {'OK' if ok else 'FAIL'}  {msg}")

    print("\n== HTTPS ==")
    checks = [
        (f"https://{app_domain}", "web root"),
        (f"https://{api_domain}/healthz", "api health"),
    ]
    for url, label in checks:
        ok, msg = fetch(url)
        print(f"{label:24} {'OK' if ok else 'FAIL'}  {url}  {msg}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
