"""Custom-domain helpers: Cloudflare DNS automation + apex verification fallbacks."""

import asyncio

from app.config import settings
from app.services import domains as dom


def test_zone_candidates_walk_suffixes():
    assert dom.zone_candidates("chat.example.com") == ["chat.example.com", "example.com"]
    assert dom.zone_candidates("a.b.example.co.uk") == [
        "a.b.example.co.uk",
        "b.example.co.uk",
        "example.co.uk",
        "co.uk",
    ]


def test_a_points_matches_platform_ip(monkeypatch):
    monkeypatch.setattr(dom, "_sync_a_records", lambda name: ["203.0.113.10", "198.51.100.5"])
    assert asyncio.run(dom.a_points("app.example.com", "203.0.113.10")) is True
    assert asyncio.run(dom.a_points("app.example.com", "192.0.2.44")) is False


def test_cloudflare_relative_name_handles_zone_apex_and_subdomain():
    assert dom.CloudflareClient._relative_name("example.com", "example.com") == "@"
    assert dom.CloudflareClient._relative_name("chat.example.com", "example.com") == "chat"
    assert dom.CloudflareClient._relative_name("_mood-verify.chat.example.com", "example.com") == "_mood-verify.chat"


def test_cloudflare_provision_subdomain_uses_txt_and_cname(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "cf-token")
    monkeypatch.setattr(settings, "PLATFORM_CNAME_TARGET", "edge.mood.test")
    monkeypatch.setattr(settings, "PLATFORM_A_RECORD_IP", "")

    calls: list[dict] = []
    cf = dom.CloudflareClient()

    async def _find_zone(domain: str):
        assert domain == "chat.example.com"
        return {"id": "zone-1", "name": "example.com"}

    async def _upsert(zone_id: str, *, type: str, name: str, content: str, proxied: bool = False, ttl: int = 300):
        calls.append({"zone_id": zone_id, "type": type, "name": name, "content": content, "proxied": proxied, "ttl": ttl})

    monkeypatch.setattr(cf, "find_zone", _find_zone)
    monkeypatch.setattr(cf, "upsert_record", _upsert)

    out = asyncio.run(cf.provision_connected_domain("chat.example.com", "verify-123"))

    assert out == {
        "zone": "example.com",
        "txt_name": "_mood-verify.chat.example.com",
        "record_type": "CNAME",
        "record_name": "chat.example.com",
        "record_value": "edge.mood.test",
    }
    assert calls == [
        {
            "zone_id": "zone-1",
            "type": "TXT",
            "name": "_mood-verify.chat",
            "content": "verify-123",
            "proxied": False,
            "ttl": 300,
        },
        {
            "zone_id": "zone-1",
            "type": "CNAME",
            "name": "chat",
            "content": "edge.mood.test",
            "proxied": False,
            "ttl": 300,
        },
    ]


def test_cloudflare_provision_apex_prefers_a_record_when_platform_ip_exists(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "cf-token")
    monkeypatch.setattr(settings, "PLATFORM_CNAME_TARGET", "edge.mood.test")
    monkeypatch.setattr(settings, "PLATFORM_A_RECORD_IP", "203.0.113.10")

    calls: list[dict] = []
    cf = dom.CloudflareClient()

    async def _find_zone(domain: str):
        assert domain == "example.com"
        return {"id": "zone-1", "name": "example.com"}

    async def _upsert(zone_id: str, *, type: str, name: str, content: str, proxied: bool = False, ttl: int = 300):
        calls.append({"zone_id": zone_id, "type": type, "name": name, "content": content, "proxied": proxied, "ttl": ttl})

    monkeypatch.setattr(cf, "find_zone", _find_zone)
    monkeypatch.setattr(cf, "upsert_record", _upsert)

    out = asyncio.run(cf.provision_connected_domain("example.com", "verify-123"))

    assert out == {
        "zone": "example.com",
        "txt_name": "_mood-verify.example.com",
        "record_type": "A",
        "record_name": "example.com",
        "record_value": "203.0.113.10",
    }
    assert calls[-1] == {
        "zone_id": "zone-1",
        "type": "A",
        "name": "@",
        "content": "203.0.113.10",
        "proxied": False,
        "ttl": 300,
    }
