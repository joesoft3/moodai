"""OAuth provider registry: Gmail, Google Calendar, GitHub."""

from dataclasses import dataclass, field

from fastapi import HTTPException, status

from ...config import settings


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    name: str
    icon: str
    description: str
    auth_url: str
    token_url: str
    api_base: str
    scopes: str
    client_id: str
    client_secret: str
    extra_auth_params: dict = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


_google_base = dict(
    auth_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    extra_auth_params={"access_type": "offline", "prompt": "consent"},
)

PROVIDERS: dict[str, ProviderSpec] = {
    "gmail": ProviderSpec(
        key="gmail",
        name="Gmail",
        icon="📧",
        description="Read your inbox and send emails",
        api_base="https://gmail.googleapis.com/gmail/v1",
        scopes="https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        **_google_base,
    ),
    "google_calendar": ProviderSpec(
        key="google_calendar",
        name="Google Calendar",
        icon="📅",
        description="List upcoming events and create new ones",
        api_base="https://www.googleapis.com/calendar/v3",
        scopes="https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        **_google_base,
    ),
    "github": ProviderSpec(
        key="github",
        name="GitHub",
        icon="🐙",
        description="Browse repos & issues, create issues",
        auth_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        api_base="https://api.github.com",
        scopes="repo read:user",
        client_id=settings.GITHUB_CLIENT_ID,
        client_secret=settings.GITHUB_CLIENT_SECRET,
    ),
}


def get_provider(key: str) -> ProviderSpec:
    p = PROVIDERS.get(key)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown plugin provider: {key}")
    return p


def callback_url(provider_key: str) -> str:
    return f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/api/v1/plugins/{provider_key}/callback"
