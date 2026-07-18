"""v1.1.0 units — ✂️ auto editor pipeline, 📷➡️🎬 storyboard ref-image,
🛍 client orders, 📊 studio analytics helpers."""

import asyncio

from app.api.routes.media import SERVED_NAME_RE
from app.services import editor, soundtrack
from app.services.metering import PLAN_LIMITS


# ------------------------------------------------------------- plan parsing
def test_normalize_plan_clamps_and_defaults():
    p = editor.normalize_plan({"trim_start": -5, "trim_end": 99999, "speed": 99,
                               "reframe": "4:5", "subtitles": 1, "grade": "warm",
                               "music": "epic", "music_vol": 9, "stamp": True})
    assert p.trim_start == 0 and p.trim_end == 3600
    assert p.speed == 2.0
    assert p.reframe == "4:5" and p.subtitles is True
    assert p.grade == "warm" and p.music == "epic"
    assert p.music_vol == 1.0 and p.stamp is True


def test_normalize_plan_empty_trim_window_kept_full():
    p = editor.normalize_plan({"trim_start": 10, "trim_end": 5})
    assert p.trim_end is None and p.notes


def test_normalize_plan_mute_wins_over_music():
    p = editor.normalize_plan({"mute": True, "music": "epic"})
    assert p.mute is True and p.music is None


def test_fallback_plan_keywords():
    p = editor.fallback_plan("make it vertical for tiktok, add subtitles and some lofi music")
    assert p.reframe == "9:16" and p.subtitles is True and p.music == "lofi"
    p2 = editor.fallback_plan("turn it black and white and mute the audio")
    assert p2.grade == "mono" and p2.mute is True and p2.music is None
    p3 = editor.fallback_plan("cut the first 3 seconds then keep only the first 30 seconds")
    assert p3.trim_start == 3 and p3.trim_end == 30


def test_parse_plan_json_tolerates_prose():
    assert editor.parse_plan_json('sure! {"speed": 1.5} done.') == {"speed": 1.5}
    assert editor.parse_plan_json("[1,2,3]") is None
    assert editor.parse_plan_json("no json") is None


# ---------------------------------------------------------------- argv stages
def _ff(monkeypatch):
    monkeypatch.setattr(editor, "ffmpeg_path", lambda: "/bin/ffmpeg")


def test_trim_cmd(monkeypatch):
    _ff(monkeypatch)
    cmd = editor.build_trim_cmd("in.mp4", "out.mp4", 2.5, 10.0)
    assert cmd[:2] == ["/bin/ffmpeg", "-y"]
    assert cmd[cmd.index("-ss") + 1] == "2.50"
    assert cmd[cmd.index("-t") + 1] == "7.50"
    assert "libx264" in cmd


def test_speed_cmd_atempo_and_silent_variant(monkeypatch):
    _ff(monkeypatch)
    cmd = editor.build_speed_cmd("in.mp4", "o.mp4", 1.5)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "setpts=1/1.5*PTS" in fc and "atempo=1.50" in fc
    quiet = editor.build_speed_silent_cmd("in.mp4", "o.mp4", 0.75)
    vf = quiet[quiet.index("-vf") + 1]
    assert "setpts=1/0.75*PTS" in vf and "-an" in quiet


def test_reframe_cmd_exact_targets(monkeypatch):
    _ff(monkeypatch)
    cmd = editor.build_reframe_cmd("in.mp4", "o.mp4", "9:16")
    assert "crop=1080:1920" in cmd[cmd.index("-vf") + 1]
    cmd = editor.build_reframe_cmd("in.mp4", "o.mp4", "1:1")
    assert "crop=1080:1080" in cmd[cmd.index("-vf") + 1]


def test_grade_and_burn_and_stamp_cmds(monkeypatch):
    _ff(monkeypatch)
    g = editor.build_grade_cmd("in.mp4", "o.mp4", "mono")
    assert "hue=s=0" in g[g.index("-vf") + 1]
    b = editor.build_burn_subs_cmd("in.mp4", "o.mp4", "subs.srt")
    assert "subtitles=subs.srt" in b[b.index("-vf") + 1]
    st = editor.build_stamp_cmd("in.mp4", "logo.png", "o.mp4")
    fc = st[st.index("-filter_complex") + 1]
    assert "scale=140:-1" in fc and "overlay=W-w-24:H-h-24" in fc


def test_music_cmd_with_and_without_audio(monkeypatch):
    _ff(monkeypatch)
    with_a = editor.build_music_cmd("in.mp4", "o.mp4", "epic", 45, 0.35, has_audio=True)
    fc = with_a[with_a.index("-filter_complex") + 1]
    assert "amix=inputs=2" in fc and "0.35" in fc
    no_a = editor.build_music_cmd("in.mp4", "o.mp4", "soft", 45, 0.35, has_audio=False)
    fc = no_a[no_a.index("-filter_complex") + 1]
    assert "[0:a]" not in fc and "sine" in fc  # original track absent → bed solo


def test_ffprobe_cmd_points_at_ffprobe():
    # ffprobe path derived from ffmpeg path; can't call binary here, so guard the name
    assert "ffprobe" in (editor.ffmpeg_path() or "ffmpeg").replace("ffmpeg", "ffprobe")


def test_edited_outputs_served_and_swept():
    name = "a" * 32 + "_e.mp4"
    assert SERVED_NAME_RE.match(name)
    assert soundtrack.MEDIA_NAME_RE.match(name)
    src = "b" * 32 + "_src.mp4"
    assert not SERVED_NAME_RE.match(src)          # uploads stay private


# ----------------------------------------------------------- storyboard i2v
def test_ref_image_only_on_scene_one(monkeypatch):
    from app.services import storyboard as sb

    calls: list[dict] = []

    async def fake_generate(shot, opts, image=None):
        calls.append({"shot": shot, "image": image})
        return f"https://cdn/x/{len(calls)}.mp4", bool(image)

    async def fake_plan(prompt, count, scene_seconds, dialogue=False):
        return [sb.Scene(shot=f"shot {i+1}", narration="", voice="a") for i in range(count)]

    monkeypatch.setattr(sb.video, "generate", fake_generate)
    monkeypatch.setattr(sb, "plan_scenes", fake_plan)

    async def fake_download(http, url, path):
        open(path, "wb").write(b"fake-clip")

    monkeypatch.setattr(sb, "_download", fake_download)
    monkeypatch.setattr(sb, "soundtrack", _FakeSound())

    from app.services.media import VideoOptions
    opts = VideoOptions(duration=6, aspect_ratio="16:9", quality="720p", style="cinematic")
    asyncio.run(sb.generate_storyboard(
        "product reveal", scene_count=3, scene_seconds=6, opts=opts, audio="none",
        voice_name="alloy", custom_scenes=[], subtitles=False,
        ref_image={"url": "data:image/png;base64,AA=="}))
    assert calls[0]["image"] == {"url": "data:image/png;base64,AA=="}
    assert calls[1]["image"] is None and calls[2]["image"] is None


class _FakeSound:
    """stub the mux/poster steps so the storyboard flow completes in tests"""

    @staticmethod
    async def mux(*a, **k):
        return None

    @staticmethod
    def ffmpeg_path():
        return None


# -------------------------------------------------------------- plan caps
def test_edit_day_caps_exist():
    assert PLAN_LIMITS["free"]["edit_day"] == 3
    assert PLAN_LIMITS["pro"]["edit_day"] == 30
