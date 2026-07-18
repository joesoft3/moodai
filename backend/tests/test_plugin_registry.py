"""Plugin OAuth registry: providers, callback URLs, configured-flag semantics."""

import importlib

import pytest

reg = importlib.import_module("app.services.plugins.registry")


def test_plugins_init_chain_importable():
    # The package __init__ pulls agent/tools/oauth — catching import regressions here
    # prevents the whole /plugins router from going down silently.
    pkg = importlib.import_module("app.services.plugins")
    assert "gmail" in pkg.PROVIDERS


def test_expected_providers_present():
    assert {"gmail", "google_calendar", "github"} <= set(reg.PROVIDERS)


def test_callback_urls_shape():
    for key in reg.PROVIDERS:
        url = reg.callback_url(key)
        assert url.endswith(f"/api/v1/plugins/{key}/callback")
        assert url.startswith("http")


def test_callback_uses_backend_public_url(monkeypatch):
    reg.settings.BACKEND_PUBLIC_URL = "https://api.mood.example/"
    try:
        assert reg.callback_url("gmail") == "https://api.mood.example/api/v1/plugins/gmail/callback"
    finally:
        reg.settings.BACKEND_PUBLIC_URL = "http://localhost:8000"


def test_gmail_scopes_cover_read_and_send():
    scopes = reg.PROVIDERS["gmail"].scopes
    assert "gmail.readonly" in scopes and "gmail.send" in scopes


def test_calendar_scopes_cover_events():
    scopes = reg.PROVIDERS["google_calendar"].scopes
    assert "calendar.readonly" in scopes and "calendar.events" in scopes


def test_github_requests_repo_scope():
    assert "repo" in reg.PROVIDERS["github"].scopes


def test_configured_flag_defaults_false_without_secrets():
    # CI has no OAuth secrets — providers must report unconfigured, not crash.
    for p in reg.PROVIDERS.values():
        assert p.configured is False


def test_provider_spec_configured_when_keys_present():
    spec = reg.ProviderSpec(
        key="x", name="X", icon="🧩", description="", auth_url="", token_url="",
        api_base="", scopes="", client_id="cid", client_secret="sec",
    )
    assert spec.configured is True


def test_unknown_provider_raises_404():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        reg.get_provider("nope")
    assert ei.value.status_code == 404
