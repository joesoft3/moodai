"""🎨 Design Studio routes — flyers, logos & banners at print resolution.

Unlike ephemeral muxed video files (24h janitor TTL), designs are keepsake
brand assets: files persist until the owner deletes the row (deletion also
unlinks both PNG tiers). Downloads are owner-gated; there is no public
serving of design files (logos/brand assets shouldn't leak by URL guessing)."""

import re
import secrets
import uuid
from pathlib import Path

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query,
                    Request, UploadFile, status)
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import BrandKit, Design, DesignOrder, PendingAction, User
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
        await record_usage(user.id, "design_export", "ffmpeg")
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


def _order_public(o: DesignOrder, brand_name: str) -> dict:
    return {
        "token": o.token,
        "status": o.status,
        "brand_name": brand_name,
        "customer_name": o.customer_name or None,
        "kind": o.kind,
        "style": o.style,
        "idea": o.idea or None,
        "note": o.note or None,
        "ready": o.status == "delivered" and bool(o.design_id),
    }


@router.post("/design-orders", status_code=status.HTTP_201_CREATED)
async def create_order_link(
    request: Request,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """🛍 Create a magic order link for clients — submissions arrive as ✋ approvals."""
    body = {}
    try:
        body = await request.json() or {}
    except Exception:
        pass
    note = str(body.get("note") or "")[:200]
    row = DesignOrder(owner_id=user.id, token=secrets.token_hex(12), note=note)
    db.add(row)
    await db.commit()
    return {"token": row.token, "path": f"/order/{row.token}", "status": row.status}


@router.get("/design-orders")
async def list_order_links(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (await db.execute(
        select(DesignOrder).where(DesignOrder.owner_id == user.id)
        .order_by(DesignOrder.created_at.desc()).limit(20)
    )).scalars().all()
    return {"orders": [
        {"id": o.id, "token": o.token, "path": f"/order/{o.token}", "status": o.status,
         "customer_name": o.customer_name or None, "kind": o.kind,
         "idea": (o.idea or "")[:80], "note": o.note or None,
         "created_at": o.created_at.isoformat() if o.created_at else None}
        for o in rows
    ]}


@router.post("/design-orders/{order_id}/close")
async def close_order_link(order_id: str, db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    o = await db.get(DesignOrder, order_id)
    if not o or o.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order link not found")
    o.status = "closed"
    await db.commit()
    return {"status": "closed"}


@router.get("/public/orders/{token}")
async def public_order_info(token: str, db: AsyncSession = Depends(get_db)):
    o = await db.scalar(select(DesignOrder).where(DesignOrder.token == token))
    if not o or o.status == "closed":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This order link is closed")
    owner = await db.get(User, o.owner_id)
    bk = await db.get(BrandKit, o.owner_id) if owner else None
    return _order_public(o, (bk.brand_name if bk else "") or (owner.email.split("@")[0] if owner else ""))


@router.post("/public/orders/{token}", status_code=status.HTTP_201_CREATED)
async def public_order_submit(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    o = await db.scalar(select(DesignOrder).where(DesignOrder.token == token))
    if not o or o.status == "closed":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This order link is closed")
    ip = request.client.host if request.client else "anon"
    await enforce_rate_limit(f"puborder:{ip}", 3)
    body = await request.json()
    name = str(body.get("customer_name") or "")[:80].strip()
    idea = str(body.get("idea") or "")[:1500].strip()
    kind = str(body.get("kind") or "flyer")
    style = str(body.get("style") or "minimal")
    if len(idea) < 5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Describe the design you need")
    if kind not in dzn.KIND_PRESETS:
        kind = "flyer"
    if style not in dzn.STYLE_PRESETS:
        style = "minimal"
    o.customer_name, o.idea, o.kind, o.style = name, idea, kind, style
    o.status = "staged"
    db.add(PendingAction(
        user_id=o.owner_id, conversation_id=None, tool="design_create",
        args={"idea": f"[Client order — {name or 'guest'}] {idea}", "kind": kind,
              "style": style, "order_token": o.token},
    ))
    await db.commit()
    return {"status": "staged", "how_to": "Order received! The designer reviews & renders it — refresh this link for your files."}


@router.get("/public/orders/{token}/download")
async def public_order_download(
    token: str, tier: str = Query(default="web", pattern="^(web|print)$"),
    db: AsyncSession = Depends(get_db),
):
    o = await db.scalar(select(DesignOrder).where(DesignOrder.token == token))
    if not o or o.status != "delivered" or not o.design_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not ready yet — check back soon")
    d = await db.get(Design, o.design_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Design missing")
    name = d.print_file if tier == "print" else d.file
    path = Path(settings.MEDIA_DIR) / name
    if not name or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File expired")
    suffix = "print-hd" if tier == "print" else "web"
    return FileResponse(path, media_type="image/png", filename=f"mood-{d.kind}-{suffix}.png")


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


# ------------------------------------------------------------ 🔁 batch studio
async def _batch_budget(db, user) -> int:
    """Remaining design slots today for this plan (raises when exhausted)."""
    await enforce_rate_limit(f"design:{user.id}", 8)
    cap = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"])["design_day"]
    used = await count_today(db, user.id, "design")
    remaining = (cap - used) if cap else dzn.BATCH_MAX
    if cap and remaining <= 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Daily design limit reached for the {user.plan} plan ({cap}/day). Upgrade for more.",
        )
    return remaining


def _batch_row(user_id: str, headline: str, out: dict, source: str) -> Design:
    return Design(
        id=out["id"], user_id=user_id, kind="flyer",
        idea=headline[:200], brief=f"🔁 batch {source} — {headline[:160]}",
        prompt=f"batch:{source}", style="batch", palette="auto",
        width=out["width"], height=out["height"],
        file=out["file"], print_file=out["print_file"],
    )


@router.post("/designs/batch", status_code=status.HTTP_201_CREATED)
async def batch_photo_flyers(
    files: list[UploadFile] = File(...),
    headline: str = Form(min_length=2, max_length=90),
    sub: str = Form(default="", max_length=120),
    cta: str = Form(default="", max_length=40),
    accent: str = Form(default="#FFD54A"),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """🔁 One headline + up to 10 photos → a matching flyer set (local render, no tokens)."""
    remaining = await _batch_budget(db, user)
    picked = files[: min(dzn.BATCH_MAX, remaining)]
    made, skipped = [], []
    for f in picked:
        mime = (f.content_type or "").lower()
        raw = await f.read()
        if mime not in dzn.BATCH_IMG_MIMES or not raw or len(raw) > dzn.BATCH_IMG_MAX_BYTES:
            skipped.append(f.filename or "?")
            continue
        try:
            out = await dzn.render_photo_flyer(raw, headline.strip(), sub.strip(), cta.strip(), accent)
        except dzn.DesignError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
        d = _batch_row(user.id, headline.strip(), out, "photo")
        db.add(d)
        await db.commit()
        await record_usage(user.id, "design", "batch-photo")
        made.append(_row(d))
    if not made:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            "No usable images — send PNG/JPEG/WebP ≤ 8 MB each.")
    return {"designs": made, "skipped": skipped,
            "trimmed": max(0, len(files) - len(picked)), "remaining_today": remaining - len(made)}


@router.post("/designs/batch-csv", status_code=status.HTTP_201_CREATED)
async def batch_csv_flyers(
    file: UploadFile = File(...),
    accent: str = Form(default="#FFD54A"),
    theme: str = Form(default="noir"),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """🔁 CSV (headline,sub,cta[,accent]) → one typographic card flyer per row."""
    remaining = await _batch_budget(db, user)
    raw = await file.read()
    if not raw or len(raw) > dzn.BATCH_CSV_MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"CSV must be ≤ {dzn.BATCH_CSV_MAX_BYTES // 1024} KB")
    try:
        rows = dzn.parse_flyer_csv(raw, limit=min(dzn.BATCH_MAX, remaining))
    except dzn.DesignError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    made = []
    for row in rows:
        try:
            out = await dzn.render_text_card(
                row["headline"], row["sub"], row["cta"],
                row["accent"] or accent, theme if theme in dzn.THEME_BGS else "noir",
            )
        except dzn.DesignError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
        d = _batch_row(user.id, row["headline"], out, "csv")
        db.add(d)
        await db.commit()
        await record_usage(user.id, "design", "batch-csv")
        made.append(_row(d))
    return {"designs": made, "rows": len(rows), "remaining_today": remaining - len(made)}
