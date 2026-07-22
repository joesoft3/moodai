"""🎨🎬 In-chat creation intent router (v1.9.7).

Decides — with pure heuristics, ZERO LLM calls (daily-quota economy) — whether a
chat message is really a request to create media, so /chat/stream can generate
images & videos inline, ChatGPT-style, without the user ever leaving the chat.

Contract:
    route_media_intent(message, last_media) -> CreateIntent | None

`last_media` is the previous assistant message's media meta (if any) — short
follow-ups like "make it night time" refine the last generation instead of
starting a fresh chat answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class CreateIntent:
    kind: str        # "image" | "video"
    prompt: str      # cleaned generation prompt
    refine: bool = False  # True = continuation/refinement of the last generation


# ---------------------------------------------------------------- vocabulary
_VERB = (
    r"(?:generate|creat\w+|make|draw|paint|design|render|imagine|visuali[sz]e|"
    r"produce|craft|depict|illustrate|sketch|show\s+me|give\s+me|whip\s+up|conjure)"
)
_IMG_NOUN = (
    r"(?:image|picture|photo(?:graph)?|pic|painting|drawing|art(?:work)?|illustration|"
    r"logo|wallpaper|poster|avatar|icon|banner|portrait|sketch|comic|sticker|thumbnail|"
    r"meme|flyer|mascot|cover\s+art)"
)
_VID_NOUN = (
    r"(?:video|clip|reel|animation|animated\s+\w+|film|movie|footage|trailer|"
    r"motion\s+graphic|cinematic|montage|timelapse|time-lapse|slideshow)"
)
_OBJ = r"(?:of|for|with|about|depicting|showing|featuring|about|like|:)\b"

# verb (+ optional article/noun) + object  → strongest signal ("make a logo for X", "draw a cat")
_RE_ACTION = re.compile(
    rf"\b{_VERB}\b[ \t]+(?:(?:an?|the|some|this|that|my|me\s+an?)\s+)?"
    rf"(?:(?:short|long|quick|nice|cool|beautiful|cute|funny|epic|little|"
    rf"vertical|horizontal|square|widescreen|anime|animated|realistic|hd|4k)\s+)?"
    rf"(?:(?:short|long|quick|epic|little|vertical|horizontal|square|anime|animated|realistic)\s+)?"
    rf"(?P<noun>{_IMG_NOUN}|{_VID_NOUN})?[ \t]*(?:{_OBJ})?[ \t]*",
    re.IGNORECASE,
)
# message IS the noun phrase: "a logo for a barbershop", "wallpaper of Accra at dusk"
_RE_NOUN_FIRST = re.compile(
    rf"^\s*(?:an?\s+|the\s+)?(?P<noun>{_IMG_NOUN}|{_VID_NOUN})\b[ \t]+{_OBJ}\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
# interrogative openers → it's a question, not a creation command
_RE_QUESTION = re.compile(
    r"^\s*(?:what(?:'s| is| are)?|how(?:\s+(?:do|can|to|much|many))?|why|where|when|which|who(?:'s| is)?|"
    r"whose|is\b|are\b|does\b|do\b|did\b|can\s+mood)\b",
    re.IGNORECASE,
)
# capability small-talk: "can you generate images?" (no actual subject matter)
_RE_CAPABILITY = re.compile(
    rf"^\s*(?:(?:can|could)\s+(?:you|u)|are\s+you\s+able|do\s+you\s+know\s+how)"
    rf"\s+(?:\w+\s+){{0,3}}(?:(?:{_IMG_NOUN}|{_VID_NOUN})s?|draw|paint|sketch|animate)\s*[?!.]*\s*$",
    re.IGNORECASE,
)
# refinement follow-ups ("make it darker", "now in the rain") — only valid with last_media
_REFINE_MARKERS = re.compile(
    r"^\s*(?:make\s+it|now\b|again\b|redo\b|another\b|variation|a\s+variation|more\b|less\b|"
    r"add\s+|remove\s+|change\s+|turn\s+it|turn\s+the|same\s+but|but\s+with|but\s+make|"
    r"in\s+the|at\s+night|at\s+sunset|at\s+sunrise|during\s+|with\s+more|with\s+less|"
    r"brighter|darker|colorful|colourful|different\s+(?:style|color|colour|mood|angle|background)|"
    r"try\s+(?:again|it)\b|regenerate\b)",
    re.IGNORECASE,
)

_SLASH = re.compile(r"^\s*/(image|img|video|vid)\s+(.+)$", re.IGNORECASE | re.DOTALL)
_PREFIX = re.compile(r"^\s*(image|video)\s*:\s*(.{3,})$", re.IGNORECASE | re.DOTALL)


def _kind_of(noun: str | None) -> str | None:
    if not noun:
        return None
    n = noun.lower()
    if re.fullmatch(_VID_NOUN, n):
        return "video"
    if re.fullmatch(_IMG_NOUN, n):
        return "image"
    return None


def route_media_intent(message: str, last_media: dict | None = None) -> CreateIntent | None:
    """Classify a chat message. Returns None → normal text chat path."""
    msg = (message or "").strip()
    if not msg or len(msg) > 1500:
        return None

    # 0) explicit shorthand: "/image a kente robot" / "video: accra coastline"
    m = _SLASH.match(msg) or _PREFIX.match(msg)
    if m:
        kind = "video" if m.group(1).lower().startswith(("vid",)) else m.group(1).lower()
        kind = {"img": "image", "vid": "video"}.get(kind, kind)
        prompt = m.group(2).strip()
        return CreateIntent(kind=kind, prompt=prompt) if prompt else None

    # 1) refinement of the immediately-previous generation
    if last_media and len(msg) <= 220 and _REFINE_MARKERS.match(msg):
        kind = last_media.get("kind")
        base = (last_media.get("prompt") or "").strip()
        if kind in ("image", "video") and base:
            tweak = re.sub(r"^\s*(?:make\s+it|same\s+but|but\s+make\s+it|turn\s+it|now)\s*[:,]?\s*", "", msg, flags=re.IGNORECASE).strip()
            tweak = tweak or msg
            return CreateIntent(kind=kind, prompt=f"{base}, {tweak}", refine=True)

    # 2) questions & capability chat are NOT creations
    if _RE_QUESTION.match(msg):
        return None
    if _RE_CAPABILITY.match(msg):
        return None

    # 3) verb-driven: "generate an image of …", "paint a sunset", "show me a video of …"
    m = _RE_ACTION.search(msg)
    if m:
        # must not look like a conditional/hypothetical buried late in a long sentence
        if m.start() <= 48:
            kind = _kind_of(m.group("noun"))
            verb_span = m.group(0)
            verb = re.match(rf"\s*{_VERB}", verb_span, re.IGNORECASE)
            vb = verb.group(0).strip().lower() if verb else ""
            if kind is None:
                # visual verbs carry the intent on their own: draw/paint/sketch/illustrate → image; animate → video
                if re.fullmatch(r"(draw|paint|sketch|illustrate|visuali[sz]e|imagine|depict)", vb):
                    kind = "image"
                elif re.fullmatch(r"(render)", vb):
                    kind = "image"
                if kind is None:
                    return None
            prompt = msg[m.end():].strip() if m.end() < len(msg) else ""
            if not prompt:
                # "draw a cat" → object sits right after the matched verb span
                rest = msg[m.end():].strip()
                prompt = rest
            prompt = re.sub(r"^(?:of|for|with|about|depicting|showing|featuring|like|:)\s+", "", prompt, flags=re.IGNORECASE).strip()
            # Show me the noun itself? (e.g. just "image of a cat" already captured)
            if len(prompt) < 3:
                return None
            # never treat "search/google for an image of X" as creation
            if re.search(r"\b(search|google|find|look\s+up|download)\b.{0,30}$", msg[: m.end()], re.IGNORECASE):
                return None
            return CreateIntent(kind=kind, prompt=prompt)

    # 4) noun-first: "logo for my barbershop", "a wallpaper of the Accra skyline"
    m = _RE_NOUN_FIRST.match(msg)
    if m and len(msg) <= 200:
        kind = _kind_of(m.group("noun"))
        rest = (m.group("rest") or "").strip()
        if kind and len(rest) >= 3:
            prompt = rest
            return CreateIntent(kind=kind, prompt=prompt)

    return None
