"""v1.2.0 units — 🎵 beat analyzer + beat-cut stages, 🔁 batch studio
(photo flyers, CSV cards), layout planner guards."""

import shutil
import subprocess
from array import array
from pathlib import Path

import pytest

from app.services import beats, designer as dzn, editor

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg binary not available")


# ------------------------------------------------------------------ beats
def _pulse_pcm(rate: int, period: float = 0.5, seconds: float = 6.0) -> array:
    """Square-ish tone burst every `period` seconds → synthetic click track."""
    import math
    out = array("h")
    n = int(rate * seconds)
    for i in range(n):
        t = i / rate
        on = (t % period) < 0.15
        v = int(12000 * math.sin(2 * math.pi * 880 * t)) if on else 60
        out.append(v)
    return out


def test_energy_env_and_pick_beats_synthetic():
    pcm = _pulse_pcm(beats.SAMPLE_RATE)
    env = beats.energy_env(pcm)
    assert len(env) > 50
    found = beats.pick_beats(env)
    assert 9 <= len(found) <= 13
    gaps = [b2 - b1 for b1, b2 in zip(found, found[1:])]
    assert all(0.3 <= g <= 0.7 for g in gaps)


def test_bpm_estimate_octave_folding():
    bs = [i * 0.5 for i in range(12)]
    assert 114 <= beats.bpm_estimate(bs) <= 126
    assert beats.bpm_estimate([i * 0.25 for i in range(8)]) in range(60, 181)
    assert beats.bpm_estimate([0.5]) is None


def test_pick_beats_silence_is_empty():
    pcm = array("h", [10] * (beats.SAMPLE_RATE * 2))
    assert beats.pick_beats(beats.energy_env(pcm)) == []


def test_suggest_caption_marks_kinds():
    pcm = _pulse_pcm(beats.SAMPLE_RATE)
    env = beats.energy_env(pcm)
    found = beats.pick_beats(env)
    marks = beats.suggest_caption_marks(env, found, limit=6)
    assert marks and all(set(m) == {"time", "kind"} for m in marks)
    assert len(marks) <= 6
    assert any(m["kind"] == "drop" for m in marks)


# ------------------------------------------------------------ beat-cut argv
def test_beat_cut_cmd_structure(monkeypatch):
    monkeypatch.setattr(editor, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = editor.build_beat_cut_cmd("in.mp4", "o.mp4", [0.5, 1.0, 1.5], 0.4, has_audio=True)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert fc.count("[0:v]trim=start=") == 3 and fc.count("[0:a]atrim=start=") == 3
    assert "concat=n=3:v=1:a=1" in fc
    assert cmd[cmd.index("-map") + 1] == "[vout]"
    assert "aac" in cmd


def test_beat_cut_cmd_silent_and_clamps(monkeypatch):
    monkeypatch.setattr(editor, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = editor.build_beat_cut_cmd("in.mp4", "o.mp4", [0.1, 0.6], 0.4, has_audio=False)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0" in fc and "-an" in cmd
    assert "trim=start=0.000" in fc            # window clamps at t=0
    with pytest.raises(editor.EditError):
        editor.build_beat_cut_cmd("in.mp4", "o.mp4", [], 0.4)


def test_even_cut_cmd_falls_back(monkeypatch):
    monkeypatch.setattr(editor, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = editor.build_even_cut_cmd("in.mp4", "o.mp4", 8.0, 0.4, 1.6)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert fc.count("trim=start=") >= 4


def test_plan_beats_normalize_and_fallback():
    p = editor.normalize_plan({"beats": 1, "beat_window": 99})
    assert p.beats is True and p.beat_window == 0.9
    assert editor.fallback_plan("cut it to the beat of the music").beats is True
    assert editor.fallback_plan("make it vertical").beats is False


# ----------------------------------------------------------- batch studio
def test_parse_flyer_csv_variants_and_caps():
    rows = dzn.parse_flyer_csv(b"headline,sub,cta\nGrand Sale,50% off,Call 055\n,skip,x\n")
    assert len(rows) == 1 and rows[0]["cta"] == "Call 055"
    rows = dzn.parse_flyer_csv("title,offer,contact,colour\nWaakye Day,GH¢20,0244,#00FF00".encode())
    assert rows[0]["headline"] == "Waakye Day" and rows[0]["accent"] == "#00FF00"
    with pytest.raises(dzn.DesignError):
        dzn.parse_flyer_csv(b"a,b\n,,\n")
    with pytest.raises(dzn.DesignError):
        dzn.parse_flyer_csv(b"x" * (dzn.BATCH_CSV_MAX_BYTES + 1))


def test_dt_text_escapes_and_keeps_percent_literal():
    assert dzn._dt_text("50% off: today, only") == "50% off\\: today\\, only"
    assert "\n" not in dzn._dt_text("a\nb")
    assert dzn._dt_text("it's lit") == "it\u2019s lit"


def test_valid_accent_normalization():
    assert dzn.valid_accent("#00ff00") == "0x00FF00"
    assert dzn.valid_accent("ff8800") == "0xFF8800"
    assert dzn.valid_accent("not-a-color") == "0xFFD54A"


def test_flyer_layout_never_collides():
    L = dzn.flyer_layout(1536, 2, 2, True, pill_y=0.84, top_frac=0.40, pad_frac=0.02)
    pill_top = round(1536 * 0.84)
    sub_bottom = L["sub_y"] + 2 * L["sub_step"]
    assert sub_bottom <= pill_top
    assert L["head_y"] >= 1536 * 0.40 or L["head_size"] <= round(1536 / 13)
    # tiny-card stress: sizes shrink instead of overlapping
    L2 = dzn.flyer_layout(1536, 3, 2, True, pill_y=0.78, top_frac=0.12, pad_frac=0.05)
    assert L2["head_size"] >= round(1536 / 26)


def test_fit_font_shrinks_long_lines():
    assert dzn.fit_font(["short"], 118, 900, 0.64) == 118
    small = dzn.fit_font(["a very very long headline line"], 118, 900, 0.64)
    assert small < 118 and small >= 118 * 0.42 * 0.9 - 2


def test_photo_flyer_cmd_uses_expansion_none_and_fit(monkeypatch):
    monkeypatch.setattr(dzn, "drawtext_available", lambda: True)
    monkeypatch.setattr(dzn, "brand_font", lambda: "/f.ttf")
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_photo_flyer_cmd("p.png", "o.png", 1024, 1536,
                                    "Grand Sale 50% Off", "all week", "Call", "#00C2FF")
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1024:1536" in vf and "crop=1024:1536" in vf
    assert "expansion=none" in vf and "drawbox" in vf
    assert "50%" in vf and "%%" not in vf


def test_text_card_cmd_lavfi_and_theme(monkeypatch):
    monkeypatch.setattr(dzn, "drawtext_available", lambda: True)
    monkeypatch.setattr(dzn, "brand_font", lambda: "/f.ttf")
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_text_card_cmd("o.png", 1024, 1536, "Hi", accent="#FFD54A", theme="ocean")
    assert "color=c=0x0E2A47" in cmd[cmd.index("-i") + 1]
    assert "gblur" in cmd[cmd.index("-vf") + 1]


# ------------------------------------------------ ffmpeg-honest runs
@needs_ffmpeg
def test_analyze_and_run_beat_edit(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MEDIA_DIR", str(tmp_path))
    clip = tmp_path / "click.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x224466:s=480x320:d=6:r=25",
         "-f", "lavfi", "-i", "aevalsrc=sin(880*2*PI*t)*lt(mod(t\\,0.5)\\,0.15):d=6",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)],
        check=True)
    info = beats.analyze(clip)
    assert 9 <= info["count"] <= 13 and info["bpm"] and 100 <= info["bpm"] <= 140

    import asyncio
    plan = editor.normalize_plan({"beats": True})
    name, notes = asyncio.run(editor.run_edit(clip, plan))
    out = Path(tmp_path) / name
    assert out.exists() and out.stat().st_size > 10_000
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True).stdout.strip())
    assert info["count"] * 0.28 <= dur <= info["count"] * 0.52
    assert any("🎵" in n for n in notes)


@needs_ffmpeg
def test_batch_render_photo_and_card(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MEDIA_DIR", str(tmp_path))
    src = tmp_path / "photo.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=800x600:duration=0.2", "-frames:v", "1", str(src)],
                   check=True)
    import asyncio
    out = asyncio.run(dzn.render_photo_flyer(src.read_bytes(), "Sale 50%", "one week", "Call", "#00C2FF"))
    web, prt = Path(tmp_path, out["file"]), Path(tmp_path, out["print_file"])
    assert web.exists() and prt.exists()
    assert out["width"] == 1024 and out["height"] == 1536
    card = asyncio.run(dzn.render_text_card("Waakye Friday", "from GH¢20", "Order", "#FFD54A", "sunset"))
    assert Path(tmp_path, card["file"]).exists()



def test_sqlite_date_trunc_semantics():
    from app.db.session import _sqlite_date_trunc as f
    assert f("day", "2026-07-19 13:45:22") == "2026-07-19 00:00:00"
    assert f("month", "2026-07-19 13:45:22").startswith("2026-07-01")
    assert f("hour", "2026-07-19T13:45:22") == "2026-07-19 13:00:00"
    assert f("week", "2026-07-19 13:45:22") == "2026-07-13 00:00:00"   # 19 Jul 2026 is a Sunday
    assert f("year", "2026-07-19 13:45:22").startswith("2026-01-01")
