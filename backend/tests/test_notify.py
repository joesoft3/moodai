"""Push notify service: pure builders + disabled semantics (no network, no FCM keys)."""

import base64
import importlib
import json

notify = importlib.import_module("app.services.notify")
from app.config import settings  # noqa: E402


def test_enabled_requires_both_keys(monkeypatch):
    monkeypatch.setattr(settings, "FCM_PROJECT_ID", "")
    monkeypatch.setattr(settings, "FCM_SERVICE_ACCOUNT_JSON", "")
    assert notify.enabled() is False
    monkeypatch.setattr(settings, "FCM_PROJECT_ID", "demo-project")
    assert notify.enabled() is False
    monkeypatch.setattr(settings, "FCM_SERVICE_ACCOUNT_JSON", "{}")
    assert notify.enabled() is True


def test_build_message_envelope_and_data_stringify():
    m = notify.build_message("tok123", "Hi", "Body", {"screen": "/plugins", "n": 3})
    assert m["message"]["token"] == "tok123"
    assert m["message"]["notification"] == {"title": "Hi", "body": "Body"}
    assert m["message"]["data"] == {"screen": "/plugins", "n": "3"}


def test_build_jwt_claims_shape():
    sa = {"client_email": "fc@mood.iam.gserviceaccount.com"}
    c = notify.build_jwt_claims(sa, now=1_700_000_000)
    assert c["iss"] == c["sub"] == sa["client_email"]
    assert c["aud"].endswith("/token")
    assert "firebase.messaging" in c["scope"]
    assert c["exp"] - c["iat"] == 3000


def test_signed_jwt_header_is_rs256():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    sa = {"client_email": "fc@mood.iam.gserviceaccount.com", "private_key": pem}
    parts = notify._signed_jwt(sa).split(".")
    assert len(parts) == 3
    header = json.loads(base64.urlsafe_b64decode(parts[0] + "=="))
    assert header["alg"] == "RS256"


def test_service_account_invalid_json_returns_empty(monkeypatch):
    monkeypatch.setattr(settings, "FCM_SERVICE_ACCOUNT_JSON", "{not json")
    assert notify.service_account() == {}
