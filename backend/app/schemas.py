from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = None
    app_password: str | None = None  # required only when the owner enabled the app access gate


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PreferencesUpdate(BaseModel):
    custom_instructions: str | None = Field(default=None, max_length=2000)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class ConversationCreate(BaseModel):
    title: str | None = None


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    workspace_id: str | None = None  # create/share this conversation in a team workspace
    message: str = ""
    files: list[str] = []
    search: bool = False
    plugins: bool = False  # allow tool calls against connected apps (Gmail/Calendar/GitHub)
    regenerate: bool = False
    depth: str = "deep"  # deepsearch: "deep" (2 rounds) or "deeper" (3 rounds)
    # premium model controls (web/mobile model picker)
    model: str | None = None          # grok-4 | auto | grok-4-fast | grok-3-mini | grok-code-fast-1
    think: bool = False               # 🧠 extended reasoning (grok-4 / grok-code-fast-1)
    arena: bool = False               # ⚔️ marker flag (mobile parity); routing uses the arena endpoint
    arena_extra: str | None = None    # extra arena panelist: gemini-2.5-flash | grok-code-fast-1
    rematch: bool = False             # ⚔️ rematch: drafters try to beat the previous arena winner


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class MemberAdd(BaseModel):
    email: EmailStr
    role: str = Field(default="member", pattern="^(member|owner)$")


class ConnectDomainRequest(BaseModel):
    domain: str = Field(min_length=4, max_length=253)
    workspace_id: str | None = None
    brand_name: str | None = Field(default=None, max_length=80)


class DomainContact(BaseModel):
    name_first: str = Field(min_length=1, max_length=60)
    name_last: str = Field(min_length=1, max_length=60)
    email: EmailStr
    phone: str = Field(min_length=5, max_length=30)      # e.g. +1.5551234567
    address1: str = Field(min_length=3, max_length=120)
    city: str = Field(min_length=2, max_length=60)
    state: str = Field(min_length=1, max_length=40)
    postal_code: str = Field(min_length=2, max_length=16)
    country: str = Field(min_length=2, max_length=2)     # ISO-2


class PurchaseDomainRequest(BaseModel):
    domain: str = Field(min_length=4, max_length=253)
    years: int = Field(default=1, ge=1, le=10)
    contact: DomainContact
    brand_name: str | None = Field(default=None, max_length=80)
    workspace_id: str | None = None


class DomainUpdateRequest(BaseModel):
    """PATCH semantics: field absent/None → unchanged; "" (brand/logo/workspace) → cleared."""

    brand_name: str | None = Field(default=None, max_length=80)
    accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    logo_data: str | None = Field(default=None)  # data:image/...;base64, ≤200k chars (validated in route)
    auto_renew: bool | None = None
    workspace_id: str | None = None  # bind domain → team workspace (gates invite links)
    # ⚔️ white-label arena (panel entries validated in the route)
    arena_enabled: bool | None = None
    arena_daily_cap: int | None = Field(default=None, ge=0, le=100_000)  # 0 = inherit the user's plan cap
    arena_brand: str | None = Field(default=None, max_length=80)  # "" clears
    arena_judge: str | None = Field(default=None, max_length=60)  # judge model id; "" clears
    arena_panel: list[dict] | None = None  # [{"provider","model","label"}]; [] clears


class WorkspaceJoinRequest(BaseModel):
    token: str = Field(min_length=8, max_length=64)


class DomainRenewRequest(BaseModel):
    years: int = Field(default=1, ge=1, le=10)


class InviteEmailRequest(BaseModel):
    emails: list[EmailStr] = Field(min_length=1, max_length=10)


# ---------------------------------------------------------------- admin (owner panel)
class AdminSettingsUpdate(BaseModel):
    signup_open: bool | None = None
    app_password: str | None = None  # "" clears the gate; a value rotates the app password


class AdminPlanUpdate(BaseModel):
    plan: str = Field(pattern="^(free|pro)$")


class AdminPasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class AdminFlagUpdate(BaseModel):
    is_admin: bool


class AdminPushTest(BaseModel):
    title: str = Field(default="🔔 Mood AI push test", max_length=80)
    body: str = Field(default="If you can read this, push is wired end-to-end. 🎉", max_length=240)


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)


class VideoRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    duration: int = Field(default=6, ge=5, le=15)          # seconds
    aspect_ratio: str = Field(default="16:9", pattern="^(16:9|9:16|1:1)$")
    quality: str = Field(default="720p", pattern="^(720p|1080p)$")
    style: str = Field(default="cinematic", max_length=40)
    negative_prompt: str = Field(default="", max_length=1000)
    # Cinema Sound: AI voiceover (+ optional procedural ambience), muxed server-side
    audio: str = Field(default="none", pattern="^(none|narration|cinema)$")
    voice: str = Field(default="alloy", pattern="^[a-z]{3,12}$")
    narration: str = Field(default="", max_length=600)     # empty → AI writes the voiceover
    music: str = Field(default="soft", pattern="^(soft|epic|lofi|tension)$")   # cinema bed
    tempo: float = Field(default=1.0, ge=0.7, le=1.3)      # narration speed


class VideoEnhanceRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)


class StoryboardRequest(BaseModel):
    """🎬 Multi-scene film: one idea → N directed scenes stitched + voiced."""
    prompt: str = Field(min_length=3, max_length=2000)
    scenes: int = Field(default=3, ge=2, le=4)
    scene_seconds: int = Field(default=6, ge=5, le=8)
    aspect_ratio: str = Field(default="16:9", pattern="^(16:9|9:16|1:1)$")
    quality: str = Field(default="720p", pattern="^(720p|1080p)$")
    style: str = Field(default="cinematic", max_length=40)
    negative_prompt: str = Field(default="", max_length=1000)
    audio: str = Field(default="cinema", pattern="^(none|narration|cinema)$")
    voice: str = Field(default="alloy", pattern="^[a-z]{3,12}$")
    dialogue: bool = False                                         # 👥 two-voice films
    voice_b: str = Field(default="onyx", pattern="^[a-z]{3,12}$")  # 2nd narrator in dialogue mode
    music: str = Field(default="soft", pattern="^(soft|epic|lofi|tension)$")
    tempo: float = Field(default=1.0, ge=0.7, le=1.3)
    subtitles: bool = False
    # User-supplied scenes: 'shot text' or 'shot text || narration line' per line (2-4 entries)
    custom_scenes: list[str] | None = Field(default=None, max_length=4)


class SocialDraftRequest(BaseModel):
    network: str = Field(default="x", pattern="^(x|threads|youtube_shorts)$")


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = Field(default=None, pattern="^[a-z]{3,12}$")
    speed: float | None = Field(default=None, ge=0.5, le=4.0)
