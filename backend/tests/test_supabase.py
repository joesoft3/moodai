"""🔌 Supabase/pooler compatibility — engine connect-args + template/brand units."""

from app.db.session import engine_connect_args
from app.services import designer as dzn


# ---------------------------------------------------------- pooler detection
def test_pooler_disables_statement_cache():
    url = ("postgresql+asyncpg://postgres.abc:pw@"
           "aws-0-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require")
    assert engine_connect_args(url) == {"statement_cache_size": 0}
    # port 6543 alone (self-hosted pgbouncer) is also pooled
    assert engine_connect_args("postgresql+asyncpg://u:p@db.local:6543/app") == {"statement_cache_size": 0}


def test_direct_connection_keeps_caching():
    assert engine_connect_args("postgresql+asyncpg://u:p@db.supabase.co:5432/postgres") == {}
    assert engine_connect_args("sqlite+aiosqlite:///./mood.db") == {}


# ---------------------------------------------------------------- templates
def test_templates_are_valid_and_ghana_flavored():
    ts = dzn.DESIGN_TEMPLATES
    assert len(ts) >= 10
    ids = set()
    for t in ts:
        assert t["kind"] in dzn.KIND_PRESETS, t["id"]
        assert t["style"] in dzn.STYLE_PRESETS, t["id"]
        assert t["palette"] in dzn.PALETTES, t["id"]
        assert t["idea"] and t["label"] and t["emoji"]
        assert "[" in t["idea"]  # personalization slots present
        ids.add(t["id"])
    assert len(ids) == len(ts)             # unique ids
    joined = " ".join(t["idea"] for t in ts).lower()
    for word in ("waakye", "mobile money", "chop bar"):
        assert word in joined


# ---------------------------------------------------------------- brand text
def test_brand_hint_text_full_and_empty():
    b = {"brand_name": "Akwaaba Coffee", "tagline": "Sip happiness",
         "color_primary": "#3B2A20", "color_secondary": "#D4AF37", "color_accent": "",
         "font_vibe": "classic"}
    h = dzn.brand_hint_text(b)
    assert "Akwaaba Coffee" in h and "#3B2A20" in h and "#D4AF37" in h
    assert "Sip happiness" in h and "classic" in h
    assert dzn.brand_hint_text(None) == ""
    assert dzn.brand_hint_text({}) == ""


def test_brand_overlay_cmd_places_logo_bottom_right(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_brand_overlay_cmd("bg.png", "logo.png", "out.png", "flyer")
    assert cmd[0] == "/bin/ffmpeg" and "-filter_complex" in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    # scale logo (16% of 1024 = 163px) then overlay at bottom-right with padding
    assert "scale=163:-1" in fc
    assert "overlay=W-w-26:H-h-26" in fc
    assert cmd[-1] == "out.png"


def test_overlay_cmd_scales_with_kind(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    flyer = dzn.build_brand_overlay_cmd("a", "b", "c", "flyer")
    banner = dzn.build_brand_overlay_cmd("a", "b", "c", "banner")
    f_fc = flyer[flyer.index("-filter_complex") + 1]
    b_fc = banner[banner.index("-filter_complex") + 1]
    assert "scale=163:-1" in f_fc      # 16% of 1024
    assert "scale=245:-1" in b_fc      # 16% of 1536
