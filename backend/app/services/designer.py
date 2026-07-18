"""🎨 Design Studio — flyers, logos & banners at print-grade resolution.

Pipeline (provider-agnostic):
  1. Art-director pass — the fast model rewrites the user's rough idea into a
     dense, layout-aware design brief (headline text, hierarchy, palette).
  2. Generate the base image with the configured image model. When the model
     is gpt-image-family we pass native size/quality/transparent options;
     anything else still works — we normalize server-side.
  3. ffmpeg post-process: exact-aspect normalize (scale+crop) → "web" tier,
     then a high-quality lanczos upscale tagged 300 DPI → "print" tier
     (A4-class flyers, 2048px logos, 3K banners).

Pure argv builders + preset tables keep every filtergraph unit-testable
without the ffmpeg binary (same pattern as services/soundtrack.py).
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from .llm import llm
from .soundtrack import ffmpeg_path  # reuse the tested locator


class DesignError(Exception):
    pass


# ------------------------------------------------------------------ presets
@dataclass(frozen=True)
class KindPreset:
    label: str
    web_w: int
    web_h: int
    print_w: int
    print_h: int
    gpt_image_size: str          # native canvas when provider supports it
    hint: str                    # layout guidance woven into the brief prompt


KIND_PRESETS: dict[str, KindPreset] = {
    "flyer": KindPreset(
        label="Flyer",
        web_w=1024, web_h=1536,
        print_w=2048, print_h=3072,
        gpt_image_size="1024x1536",
        hint="portrait poster layout, strong headline at top, supporting visual middle, call-to-action band at bottom",
    ),
    "logo": KindPreset(
        label="Logo",
        web_w=1024, web_h=1024,
        print_w=2048, print_h=2048,
        gpt_image_size="1024x1024",
        hint="centered emblem/icon mark, generous negative space, works at favicon and billboard sizes",
    ),
    "banner": KindPreset(
        label="Banner",
        web_w=1536, web_h=1024,
        print_w=3072, print_h=2048,
        gpt_image_size="1536x1024",
        hint="wide landscape composition, headline left or centered, breathing room at the edges for cropping",
    ),
}

STYLE_PRESETS: dict[str, str] = {
    "minimal":   "clean minimalism, lots of negative space, refined thin typography, 2-3 colors max",
    "bold":      "punchy bold colors, oversized confident typography, high contrast, street-poster energy",
    "luxury":    "premium luxury aesthetic, elegant serif type, gold or metallic accents on deep matte tones",
    "playful":   "playful and friendly, rounded shapes, bright saturated palette, fun illustrative feel",
    "corporate": "polished corporate design, trustworthy grid layout, professional sans-serif, brand blues/grays",
    "retro":     "authentic retro print style, halftone texture, faded ink palette, vintage typography",
    "neon":      "neon-glow nightlife look, electric accents on dark background, club-flyer energy",
}

PALETTES: dict[str, str] = {
    "auto":    "",
    "noir":    "black & white with a single accent color",
    "sunset":  "warm sunset gradient — coral, amber, magenta",
    "ocean":   "deep blues and teals with a seafoam accent",
    "forest":  "rich greens with cream and earthy brown",
    "gold":    "black and metallic gold, luxurious",
    "candy":   "pink, mint and lavender candy colors",
}

BRIEF_PROMPT = """You are an award-winning print art director.
Rewrite the client's rough idea into ONE dense, production-ready {kind} design brief covering:
exact headline text (quote it) & any sub-line/CTA text · layout & visual hierarchy ({hint}) ·
imagery & subject · color palette{palette_clause} · mood & style ({style}).
Rules: single paragraph, present tense, ≤90 words, no preamble. Text in the design must be
short (a headline plus at most one small line) and spelled exactly as quoted."""


def compile_design_prompt(
    brief: str, kind: str, style: str, palette: str, transparent: bool = False
) -> str:
    """Compose the final provider prompt from the (possibly AI-enhanced) brief.
    Pure string builder → unit-testable."""
    kp = KIND_PRESETS.get(kind, KIND_PRESETS["flyer"])
    style_txt = STYLE_PRESETS.get(style, STYLE_PRESETS["minimal"])
    palette_txt = PALETTES.get(palette, "")
    parts = [
        f"Professional print-ready {kp.label.lower()} graphic design.",
        f"Style: {style_txt}.",
        f"Layout: {kp.hint}.",
    ]
    if palette_txt:
        parts.append(f"Palette: {palette_txt}.")
    if transparent:
        parts.append("Isolated on a fully transparent background — no backdrop, no shadow card.")
    parts.append(f"Design brief: {brief.strip()}")
    parts.append("Crisp vector-clean edges, high detail, no watermark, no blurry text.")
    return " ".join(parts)


def supports_native_image_opts(model: str) -> bool:
    """Only gpt-image-family accepts size/quality/background kwargs natively;
    other providers (grok-2-image etc.) still work via server-side post-processing."""
    return model.startswith("gpt-image")


def provider_image_kwargs(model: str, kind: str, transparent: bool) -> dict[str, Any]:
    """kwargs for images.generate — empty dict when unsupported (pure, testable)."""
    if not supports_native_image_opts(model):
        return {}
    kp = KIND_PRESETS.get(kind, KIND_PRESETS["flyer"])
    kw: dict[str, Any] = {"size": kp.gpt_image_size, "quality": "high"}
    if transparent:
        kw["background"] = "transparent"
    return kw


# ------------------------------------------------------------------ ffmpeg
def build_normalize_cmd(src: str, dst: str, w: int, h: int) -> list[str]:
    """Exact-aspect normalize: cover-scale then center-crop (pure argv builder)."""
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}"
    return [ffmpeg_path() or "ffmpeg", "-y", "-i", src, "-vf", vf, "-frames:v", "1", dst]


def build_upscale_cmd(src: str, dst: str, w: int, h: int, dpi: int = 300) -> list[str]:
    """Print-quality lanczos upscale, tagged with DPI metadata (pure argv builder)."""
    vf = f"scale={w}:{h}:flags=lanczos"
    return [ffmpeg_path() or "ffmpeg", "-y", "-i", src, "-vf", vf, "-frames:v", "1", "-dpi", str(dpi), dst]


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or (cmd[-1] and not Path(cmd[-1]).exists()):
        raise DesignError(f"design post-process failed: {(proc.stderr or '')[-400:]}")


# ------------------------------------------------------------------ fetch
_DATA_URI_RE = re.compile(r"^data:image/([a-zA-Z0-9+]+);base64,(.+)$", re.S)


async def _fetch_image_bytes(url_or_data: str) -> bytes:
    m = _DATA_URI_RE.match(url_or_data)
    if m:
        return base64.b64decode(m.group(2))
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        r = await c.get(url_or_data)
        r.raise_for_status()
        if len(r.content) < 512:
            raise DesignError("image provider returned an empty payload")
        return r.content


# ------------------------------------------------------------------ flow
async def enhance_brief(idea: str, kind: str, style: str, palette: str) -> str:
    """Art-director rewrite of the rough idea; falls back to the raw idea."""
    kp = KIND_PRESETS.get(kind, KIND_PRESETS["flyer"])
    palette_clause = f" ({PALETTES[palette]})" if PALETTES.get(palette) else ""
    prompt = BRIEF_PROMPT.format(kind=kind, hint=kp.hint, style=style, palette_clause=palette_clause)
    try:
        out = await llm.complete(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Client idea: {idea.strip()}"},
            ],
            max_tokens=220,
        )
        text = (out or "").strip()
        return text if len(text) >= 20 else idea.strip()
    except Exception:
        return idea.strip()


async def generate_design(
    idea: str,
    kind: str,
    style: str = "minimal",
    palette: str = "auto",
    transparent: bool = False,
    enhance: bool = True,
) -> dict[str, Any]:
    """Full pipeline → {file, print_file, width, height, prompt} (paths relative to MEDIA_DIR)."""
    if kind not in KIND_PRESETS:
        raise DesignError(f"unknown design kind: {kind}")
    kp = KIND_PRESETS[kind]

    brief = await enhance_brief(idea, kind, style, palette) if enhance else idea.strip()
    prompt = compile_design_prompt(brief, kind, style, palette, transparent)

    kw = provider_image_kwargs(settings.MODEL_IMAGE, kind, transparent)
    url_or_data = await llm.generate_image(prompt, **kw)
    if not url_or_data and transparent and kw.get("background"):
        # transparent failed at provider → retry flat and warn via note
        kw.pop("background", None)
        url_or_data = await llm.generate_image(prompt, **kw)
    if not url_or_data:
        raise DesignError("image provider returned no image")

    raw = await _fetch_image_bytes(url_or_data)
    uid = uuid.uuid4().hex
    media = Path(settings.MEDIA_DIR)
    media.mkdir(parents=True, exist_ok=True)
    raw_path = media / f"{uid}_raw.png"
    web_path = media / f"{uid}_d.png"
    print_path = media / f"{uid}_dp.png"
    raw_path.write_bytes(raw)

    note = None
    if ffmpeg_path():
        _run(build_normalize_cmd(str(raw_path), str(web_path), kp.web_w, kp.web_h))
        _run(build_upscale_cmd(str(web_path), str(print_path), kp.print_w, kp.print_h))
        width, height = kp.web_w, kp.web_h
    else:
        # no ffmpeg (local pytest/dev): serve the raw generation for both tiers
        web_path.write_bytes(raw)
        print_path.write_bytes(raw)
        width, height = kp.web_w, kp.web_h
        note = "ffmpeg unavailable — delivered unnormalized base render."
    raw_path.unlink(missing_ok=True)

    return {
        "id": uid,
        "file": web_path.name,
        "print_file": print_path.name,
        "width": width,
        "height": height,
        "prompt": prompt,
        "brief": brief,
        "note": note,
        "native": bool(kw),
    }
