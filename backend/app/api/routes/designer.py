"""🎨 Design Studio routes — flyers, logos & banners at print resolution.

Unlike ephemeral muxed video files (24h janitor TTL), designs are keepsake
brand assets: files persist until the owner deletes the row (deletion also
unlinks both PNG tiers). Downloads are owner-gated; there is no public
serving of design files (logos/brand assets shouldn't leak by URL guessing)."""

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import BrandKit, Design, User
from ...db.session import get_db
from ...schemas import BrandKitRequest, DesignRequest
from ...services import designer as dzn
from ...services.llm import friendly_ai_error
from ...services.metering import PLAN_LIMITS, count_today, record_usage
from ..deps import enforce_rate_limit, get_current_user

router = APIRouter()


def _row(d: Design) -> dict:
    return {
        "id": d.id,
        "kind": d.kind,
        "idea": d.idea,
        "brief": d.brief,
        "prompt": d.prompt,
        "style": d.style,
        "palette": d.palette,
        "transparent": d.transparent,
        "width": d.width,
        "height": d.height,
        "note": d.note or None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.get("/designs/presets")
async def design_presets(user: User = Depends(get_current_user)):
    """Presets the studio UI renders from — always in sync with the service layer."""
    return {
        "kinds": [
            {
                "id": k,
                "label": p.label,
                "web": [p.web_w, p.web_h],
                "print": [p.print_w, p.print_h],
                "hint": p.hint,
            }
            for k, p in dzn.KIND_PRESETS.items()
        ],
        "styles": [{"id": k, "hint": v} for k, v in dzn.STYLE_PRESETS.items()],
        "palettes": [{"id": k, "hint": v} for k, v in dzn.PALETTES.items()],
    }


def _brand_row(b: BrandKit | None) -> dict:
    if not b:
        return {"brand_name": "", "tagline": "", "color_primary": "", "color_secondary": "",
                "color_accent": "", "font_vibe": "modern", "logo_design_id": "", "has_logo": False}
    return {
        "brand_name": b.brand_name, "tagline": b.tagline,
        "color_primary": b.color_primary, "color_secondary": b.color_secondary,
        "color_accent": b.color_accent, "font_vibe": b.font_vibe,
        "logo_design_id": b.logo_design_id, "has_logo": bool(b.logo_design_id),
    }


@router.get("/brand")
async def get_brand(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return _brand_row(await db.get(BrandKit, user.id))


@router.put("/brand")
async def put_brand(
    req: BrandKitRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    if req.logo_design_id:
        d = await db.get(Design, req.logo_design_id)
        if not d or d.user_id != user.id or d.kind != "logo":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "logo_design_id must reference one of YOUR logo designs")
    b = await db.get(BrandKit, user.id)
    if not b:
        b = BrandKit(user_id=user.id)
        db.add(b)
    b.brand_name = req.brand_name.strip()
    b.tagline = req.tagline.strip()
    b.color_primary, b.color_secondary, b.color_accent = req.color_primary, req.color_secondary, req.color_accent
    b.font_vibe = req.font_vibe
    b.logo_design_id = req.logo_design_id
    await db.commit()
    return _brand_row(b)


@router.get("/designs/templates")
async def design_templates(user: User = Depends(get_current_user)):
    """✈️ Ghana-flavored starter briefs — tap to load, edit the [brackets], generate."""
    return {"templates": dzn.DESIGN_TEMPLATES}


@router.post("/designs", status_code=status.HTTP_201_CREATED)
async def create_design(
    req: DesignRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await enforce_rate_limit(f"design:{user.id}", 4)
    cap = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"])["design_day"]
    if cap and await count_today(db, user.id, "design") >= cap:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Daily design limit reached for the {user.plan} plan ({cap}/day). Upgrade for more.",
        )
    if req.style not in dzn.STYLE_PRESETS:
        req.style = "minimal"
    if req.palette not in dzn.PALETTES:
        req.palette = "auto"
    if req.transparent and req.kind != "logo":
        req.transparent = False

    brand = None
    if req.use_brand:
        b = await db.get(BrandKit, user.id)
        if b:
            logo_file = ""
            if b.logo_design_id:
                lg = await db.get(Design, b.logo_design_id)
                if lg and lg.user_id == user.id and lg.kind == "logo":
                    logo_file = lg.file
            brand = {
                "brand_name": b.brand_name, "tagline": b.tagline,
                "color_primary": b.color_primary, "color_secondary": b.color_secondary,
                "color_accent": b.color_accent, "font_vibe": b.font_vibe,
                "logo_file": logo_file,
            }

    try:
        out = await dzn.generate_design(
            req.idea.strip(),
            req.kind,
            style=req.style,
            palette=req.palette,
            transparent=req.transparent,
            enhance=req.enhance,
            brand=brand,
        )
    except dzn.DesignError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, friendly_ai_error(e))

    d = Design(
        id=out["id"],
        user_id=user.id,
        kind=req.kind,
        idea=req.idea.strip(),
        brief=out["brief"],
        prompt=out["prompt"],
        style=req.style,
        palette=req.palette,
        transparent=req.transparent,
        width=out["width"],
        height=out["height"],
        file=out["file"],
        print_file=out["print_file"],
        note=out["note"] or "",
    )
    db.add(d)
    await db.commit()
    await record_usage(user.id, "design", settings.MODEL_IMAGE)
    return _row(d)


@router.get("/designs")
async def list_designs(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(Design).where(Design.user_id == user.id).order_by(Design.created_at.desc()).limit(50)
        )
    ).scalars().all()
    return {"designs": [_row(d) for d in rows]}


@router.get("/designs/{design_id}/export")
async def export_design(
    design_id: str,
    preset: str = Query(default="wa_status"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """🖨 Print-shop / social export — generated on demand, cached next to the design."""
    if preset not in dzn.EXPORT_PRESETS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"unknown preset — choose one of {sorted(dzn.EXPORT_PRESETS)}")
    d = await db.get(Design, design_id)
    if not d or d.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Design not found")
    dst = Path(settings.MEDIA_DIR) / dzn.export_filename(design_id, preset)
    if not dst.exists():
        src = Path(settings.MEDIA_DIR) / (d.print_file or d.file)
        ok = await dzn.render_export(src, dst, preset)
        if not ok:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                "Export renderer unavailable on this host")
        if not dst.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Source file missing")
    return FileResponse(dst, media_type="image/png",
                        filename=f"mood-{d.kind}-{design_id[:8]}-{preset}.png")


@router.get("/brand/icon")
async def brand_icon(
    size: int = Query(default=512, pattern="^(192|512)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """⭐ Download a square app-icon tile from your Brand Kit (192/512)."""
    b = await db.get(BrandKit, user.id)
    if not b or not b.color_primary:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Save a Brand Kit with a primary color first")
    letter = (b.brand_name or "M").strip()[:1].upper() or "M"
    safe = re.sub(r"[^a-zA-Z0-9]", "", user.id)[:32] or "me"
    dst = Path(settings.MEDIA_DIR) / f"{safe}_icon{size}.png"
    # deterministic name → regenerates in place; fine if cached
    ok = await dzn.render_brand_icon(size, b.color_primary, letter, b.color_accent or "#ffffff", dst)
    if not ok:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Icon renderer unavailable on this host")
    return FileResponse(dst, media_type="image/png",
                        filename=f"mood-icon-{size}.png", background=None)


@router.get("/designs/exports")
async def export_presets(user: User = Depends(get_current_user)):
    return {"presets": [{"id": k, "label": p.label,
                         "trim": [p.trim_w, p.trim_h], "bleed_px": p.bleed_px}
                        for k, p in dzn.EXPORT_PRESETS.items()]}


@router.get("/designs/{design_id}/download")
async def download_design(
    design_id: str,
    tier: str = Query(default="web", pattern="^(web|print)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = await db.get(Design, design_id)
    if not d or d.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Design not found")
    name = d.print_file if tier == "print" else d.file
    path = Path(settings.MEDIA_DIR) / name
    if not name or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File expired or missing")
    suffix = "print-hd" if tier == "print" else "web"
    return FileResponse(path, media_type="image/png", filename=f"mood-{d.kind}-{design_id[:8]}-{suffix}.png")


@router.delete("/designs/{design_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_design(design_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    d = await db.get(Design, design_id)
    if not d or d.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Design not found")
    for name in (d.file, d.print_file):
        try:
            if name:
                (Path(settings.MEDIA_DIR) / name).unlink(missing_ok=True)
        except OSError:
            pass
    await db.execute(delete(Design).where(Design.id == design_id))
    await db.commit()
