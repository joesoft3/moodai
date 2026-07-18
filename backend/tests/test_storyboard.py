"""Storyboard-mode unit tests — planner parsing, SRT timing, stitch argv builder,
custom scene parsing. No ffmpeg binary, no network, no provider calls."""

import pytest
from pydantic import ValidationError

from app.schemas import StoryboardRequest, TTSRequest
from app.services import storyboard


# ------------------------------------------------------------------- planning
def test_parse_scenes_from_fenced_json():
    raw = 'Here you go!\n```json\n[{"shot": "dawn over the city", "narration": "Every legend starts somewhere."},\n{"shot": "hero on rooftop", "narration": "But this one starts on a roof."}]\n```'
    scenes = storyboard._parse_scenes(raw, 2)
    assert len(scenes) == 2
    assert scenes[0].shot == "dawn over the city"
    assert scenes[1].narration == "But this one starts on a roof."


def test_parse_scenes_tolerates_prose_around_array():
    raw = 'Sure — [{  "shot": "a", "narration": "b" }] enjoy'
    scenes = storyboard._parse_scenes(raw, 1)
    assert len(scenes) == 1 and scenes[0].shot == "a"


def test_parse_scenes_rejects_junk_and_empty():
    with pytest.raises(storyboard.StoryboardError):
        storyboard._parse_scenes("no json here", 1)
    with pytest.raises(storyboard.StoryboardError):
        storyboard._parse_scenes("[]", 1)
    with pytest.raises(storyboard.StoryboardError):
        storyboard._parse_scenes('[{"narration": "no shot"}]', 1)


def test_parse_custom_scenes_with_optional_narration():
    scenes = storyboard.parse_custom_scenes(
        ["a lighthouse at dusk || The sea keeps its oldest secrets here.", "waves on black rocks", "  ", ""],
        6,
    )
    assert len(scenes) == 2
    assert scenes[0].narration.startswith("The sea keeps")
    assert scenes[1].narration == ""


# ------------------------------------------------------------------- subtitles
def test_srt_timestamps_and_scene_slots():
    sc = [storyboard.Scene(shot="a", narration="First line ever."), storyboard.Scene(shot="b", narration="Second line lands.")]
    srt = storyboard.build_srt(sc, 6)
    assert "00:00:00,000 --> 00:00:05,850" in srt   # scene-1 slot
    assert "00:00:06,000 --> 00:00:11,850" in srt   # scene-2 slot (no overlap)
    assert srt.count("First line") == 1 and srt.count("Second line") == 1


def test_srt_skips_empty_narration():
    sc = [storyboard.Scene(shot="a", narration=""), storyboard.Scene(shot="b", narration="Only one speaks.")]
    srt = storyboard.build_srt(sc, 5)
    assert srt.startswith("1\n00:00:05,000")  # renumbered, placed in scene-2 slot
    assert "Only one speaks." in srt


def test_srt_ts_format():
    assert storyboard._srt_ts(0) == "00:00:00,000"
    assert storyboard._srt_ts(65.5) == "00:01:05,500"


# ------------------------------------------------------------------- stitching
def test_stitch_cmd_silent_two_scenes():
    cmd = storyboard.build_stitch_cmd("ffmpeg", ["s0.mp4", "s1.mp4"], None, "out.mp4",
                                      scene_seconds=6, aspect="9:16", with_bed=False)
    filt = cmd[cmd.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0[v]" in filt
    assert "scale=720:1280" in filt            # aspect dims picked up
    assert "fps=24" in filt and "-crf" in cmd  # normalized + re-encoded avc
    assert "-c:a" not in cmd                   # silent: no audio encoder


def test_stitch_cmd_three_scenes_voice_cinema():
    cmd = storyboard.build_stitch_cmd(
        "ffmpeg", ["s0.mp4", "s1.mp4", "s2.mp4"], ["v0.mp3", "v1.mp3", "v2.mp3"], "out.mp4",
        scene_seconds=6, aspect="16:9", with_bed=True)
    filt = cmd[cmd.index("-filter_complex") + 1]
    assert filt.count("loudnorm=I=-16") == 3                       # every scene voice polished
    assert "concat=n=3:v=1:a=1" in filt                            # voices stitched back-to-back
    assert "[a0][bed]amix=inputs=2" in filt                        # ambience under the story
    assert "apad=whole_dur=6" in filt and "atrim=0:6" in filt      # each voice pinned to its slot
    assert cmd[cmd.index("-t") + 1] == "18"                        # total = scenes × seconds
    assert "-map" in cmd and "[aout]" in cmd


def test_stitch_cmd_voice_only_no_bed():
    cmd = storyboard.build_stitch_cmd("ffmpeg", ["s0.mp4"], ["v0.mp3"], "out.mp4",
                                      scene_seconds=8, aspect="1:1", with_bed=False)
    filt = cmd[cmd.index("-filter_complex") + 1]
    assert "[bed]" not in filt and "amix=inputs=2" not in filt
    assert "scale=720:720" in filt


def test_subtitle_burn_cmd_escapes_and_styles():
    cmd = storyboard.build_subtitle_burn_cmd("ffmpeg", "in.mp4", "/tmp/weird:dir/story.srt", "out.mp4", "16:9")
    vf = cmd[cmd.index("-vf") + 1]
    assert "subtitles=" in vf and "force_style=" in vf
    assert "\\:" in vf                                   # windows/colon safety
    assert cmd[cmd.index("-c:a") + 1] == "copy"          # audio untouched


# ------------------------------------------------------------------- schema
def test_storyboard_request_validation():
    req = StoryboardRequest(prompt="a tiny epic about rain")
    assert req.scenes == 3 and req.audio == "cinema" and req.subtitles is False
    with pytest.raises(ValidationError):
        StoryboardRequest(prompt="x" * 10, scenes=5)          # 4 scenes max
    with pytest.raises(ValidationError):
        StoryboardRequest(prompt="x" * 10, scenes=1)          # 2 scenes min
    with pytest.raises(ValidationError):
        StoryboardRequest(prompt="x" * 10, scene_seconds=9)   # 8s max per scene
    ok = StoryboardRequest(prompt="x" * 10, custom_scenes=["shot a", "shot b || line"])
    assert ok.custom_scenes[1].endswith("line")


def test_tts_request_voice_optional():
    assert TTSRequest(text="hello").voice is None
    assert TTSRequest(text="hello", voice="onyx").voice == "onyx"
    with pytest.raises(ValidationError):
        TTSRequest(text="hello", voice="BROKEN VOICE")


# ---------------------------------------------------------------- music on the stitch graph + films rows
def test_stitch_cmd_honours_music_choice():
    cmd = storyboard.build_stitch_cmd("ffmpeg", ["s0.mp4"], ["v0.mp3"], "out.mp4",
                                      scene_seconds=6, aspect="16:9", with_bed=True, music="lofi")
    filt = cmd[cmd.index("-filter_complex") + 1]
    assert "anoisesrc" in filt and "[a0][bed]amix=inputs=2" in filt


def test_stitch_cmd_default_bed_is_soft():
    cmd = storyboard.build_stitch_cmd("ffmpeg", ["s0.mp4"], ["v0.mp3"], "out.mp4",
                                      scene_seconds=6, aspect="16:9", with_bed=True)
    assert "sine=frequency=108" in cmd[cmd.index("-filter_complex") + 1]


def test_storyboard_request_music_tempo_validation():
    ok = StoryboardRequest(prompt="x" * 10, music="lofi", tempo=1.2)
    assert ok.music == "lofi" and ok.tempo == 1.2
    with pytest.raises(ValidationError):
        StoryboardRequest(prompt="x" * 10, music="rock")
    with pytest.raises(ValidationError):
        StoryboardRequest(prompt="x" * 10, tempo=2.0)


def test_film_row_roundtrips_scenes_and_kwargs():
    """The async job contract: _film_kwargs rebuilds a launch payload from the row."""
    import json
    from app.db.models import Film
    from app.api.routes.media import _film_kwargs, _film_out

    film = Film(
        id="f" * 32, user_id="u1", prompt="tiny epic",
        scenes_json=json.dumps([{"shot": "dawn over the city", "narration": "It begins."}]),
        status="done", progress=2, scene_count=2, scene_seconds=6, aspect="16:9", quality="720p",
        style="cinematic", audio="voice", voice_id="onyx", music="epic", tempo=1.1,
        subtitles=True, filename="a" * 32 + ".mp4", script="It begins.", note="",
    )
    kw = _film_kwargs(film)
    assert kw["user_id"] == "u1" and kw["scene_count"] == 2
    assert kw["custom_scenes"] == [{"shot": "dawn over the city", "narration": "It begins.", "voice": "a"}]
    assert kw["opts"]["quality"] == "720p" and kw["music"] == "epic"
    out = _film_out(film)
    assert out["status"] == "done" and out["url"].endswith("/api/v1/media/files/" + "a" * 32 + ".mp4")
    assert out["scenes"][0]["shot"] == "dawn over the city" and out["subtitles"] is True



# ---------------------------------------------------------------- dialogue mode
def test_parse_scenes_dialogue_voice_tags():
    raw = '[{"shot": "opening wide", "narration": "Every city hides a pulse.", "voice": "a"},'           ' {"shot": "neon alley", "narration": "And tonight it beats louder.", "voice": "b"},'           ' {"shot": "rooftop", "narration": "You sure about that?", "voice": "B"},'           ' {"shot": "sunrise", "narration": "Positive.", "voice": "x"}]'
    scenes = storyboard._parse_scenes(raw, 4, dialogue=True)
    voices = [s.voice for s in scenes]
    assert voices == ["a", "b", "b", "a"]          # clamped: anything != "b" → "a"


def test_parse_scenes_voice_tags_ignored_without_dialogue():
    raw = '[{"shot": "a", "narration": "line", "voice": "b"}]'
    scenes = storyboard._parse_scenes(raw, 1, dialogue=False)
    assert scenes[0].voice == "a"


def test_custom_scene_dicts_roundtrip_voice_tags():
    scenes = storyboard.parse_custom_scenes(
        [{"shot": "wide", "narration": "line a", "voice": "a"}, {"shot": "close", "narration": "line b", "voice": "b"}],
        6,
    )
    assert [s.voice for s in scenes] == ["a", "b"] and scenes[1].narration == "line b"


def test_storyboard_request_dialogue_fields():
    ok = StoryboardRequest(prompt="x" * 10, dialogue=True, voice_b="nova")
    assert ok.dialogue is True and ok.voice_b == "nova"
    with pytest.raises(ValidationError):
        StoryboardRequest(prompt="x" * 10, voice_b="LOUD VOICE")


# ---------------------------------------------------------------- social autopilot
def test_social_post_builtin_returns_draft():
    import asyncio
    from app.services.plugins.tools import execute_tool

    out = asyncio.run(execute_tool(None, "u1", "social_post", {"network": "x", "caption": "My film!", "url": "https://app/f/1"}))
    assert out["posted"] is False and out["caption"] == "My film!" and out["network"] == "x"
    assert "connectors" in out["how_to"]


def test_social_post_requires_caption_and_url():
    import asyncio
    from app.services.plugins.tools import execute_tool, PluginError

    with pytest.raises(PluginError):
        asyncio.run(execute_tool(None, "u1", "social_post", {"caption": "no link"}))


def test_social_draft_request_validation():
    from app.schemas import SocialDraftRequest

    assert SocialDraftRequest(network="threads").network == "threads"
    with pytest.raises(ValidationError):
        SocialDraftRequest(network="tiktok")   # not staged until connector exists
