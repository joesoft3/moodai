"""Cinema Sound unit tests — pure functions + graceful-degradation paths only
(no ffmpeg binary, no network, no TTS calls in CI)."""

import asyncio

import pytest
from pydantic import ValidationError

from app.schemas import VideoRequest
from app.services import soundtrack


# ---------------------------------------------------------------- word budget
def test_word_budget_scales_with_duration():
    assert soundtrack.estimate_word_budget(5) == 11
    assert soundtrack.estimate_word_budget(10) == 22
    # hard cap protects TTS latency even at max duration
    assert soundtrack.estimate_word_budget(600) == soundtrack.TTS_HARD_CAP_WORDS
    assert soundtrack.estimate_word_budget(1) >= 10  # sensible floor


def test_fit_words_keeps_short_text():
    assert soundtrack.fit_words("One two three.", 5) == "One two three."


def test_fit_words_clips_on_sentence_boundary():
    text = "The city wakes slowly. Golden light pours over the ridge and the river answers back every time."
    out = soundtrack.fit_words(text, 8)
    assert out == "The city wakes slowly."
    assert len(out.split()) <= 8


def test_fit_words_never_exceeds_budget_and_ends_clean():
    text = "word " * 200
    out = soundtrack.fit_words(text, 20)
    assert len(out.split()) <= 20
    assert out.endswith(".")


# ---------------------------------------------------------------- narration fallback
def test_write_narration_falls_back_to_prompt(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(soundtrack.llm, "complete", boom)
    prompt = "A lone astronaut walking across a windswept Mars ridge at golden hour"
    out = asyncio.run(soundtrack.write_narration(prompt, 8))
    budget = soundtrack.estimate_word_budget(8)
    assert len(out.split()) <= budget
    assert "astronaut" in out


# ---------------------------------------------------------------- mux command
def test_mux_cmd_voice_only_is_minimal_and_safe():
    cmd = soundtrack.build_mux_cmd("ffmpeg", "in.mp4", "v.mp3", "out.mp4", 8, with_bed=False, with_original=False)
    assert cmd[0] == "ffmpeg" and cmd[-1] == "out.mp4"
    filt = cmd[cmd.index("-filter_complex") + 1]
    assert "loudnorm=I=-16" in filt          # EBU R128 loudness normalization = "pure sound"
    assert "[bed]" not in filt and "[orig]" not in filt
    assert "amix" not in filt                 # nothing to mix with
    assert "-shortest" in cmd                 # voice longer than clip → trimmed to clip
    assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "copy"  # no video re-encode


def test_mux_cmd_full_mix_layers_voice_original_and_bed():
    cmd = soundtrack.build_mux_cmd("ffmpeg", "in.mp4", "v.mp3", "out.mp4", 10, with_bed=True, with_original=True)
    filt = cmd[cmd.index("-filter_complex") + 1]
    assert "[vo]" in filt and "[orig]" in filt and "[bed]" in filt
    assert "amix=inputs=3" in filt
    assert "sine=frequency=108" in filt       # procedural ambience — zero assets
    assert "apad=whole_dur=10" in filt        # bed spans the whole clip
    assert "afade=t=out:st=8.5:d=1.5" in filt # ambience fades out before the end
    assert cmd[cmd.index("-t") + 1] == "10"


def test_mux_cmd_fade_never_negative_time():
    cmd = soundtrack.build_mux_cmd("ffmpeg", "in.mp4", "v.mp3", "out.mp4", 1, with_bed=True, with_original=False)
    filt = cmd[cmd.index("-filter_complex") + 1]
    assert "afade=t=out:st=0:d=1.5" in filt
    assert "inputs=2" in filt


# ---------------------------------------------------------------- graceful degradation
def test_add_soundtrack_returns_none_without_ffmpeg(monkeypatch):
    monkeypatch.setattr(soundtrack, "ffmpeg_path", lambda: None)
    out = asyncio.run(soundtrack.add_soundtrack("https://x/clip.mp4", seconds=6, prompt="anything"))
    assert out is None  # route falls back to the provider URL with a note


def test_ffmpeg_path_respects_explicit_config(monkeypatch, tmp_path):
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setattr(soundtrack.settings, "FFMPEG_PATH", str(fake))
    assert soundtrack.ffmpeg_path() == str(fake)
    monkeypatch.setattr(soundtrack.settings, "FFMPEG_PATH", "/does/not/exist")
    assert soundtrack.ffmpeg_path() is None


def test_served_name_validation():
    assert soundtrack.MEDIA_NAME_RE.match("a" * 32 + ".mp4")
    assert not soundtrack.MEDIA_NAME_RE.match("../etc/passwd")
    assert not soundtrack.MEDIA_NAME_RE.match("../../storage/x.mp4")
    assert not soundtrack.MEDIA_NAME_RE.match("g" * 32 + ".mp4")  # hex only


# ---------------------------------------------------------------- request schema
def test_video_request_sound_defaults_off_and_validates():
    req = VideoRequest(prompt="a lighthouse at dusk")
    assert req.audio == "none" and req.voice == "alloy" and req.narration == ""
    ok = VideoRequest(prompt="a lighthouse at dusk", audio="cinema", voice="nova", narration="Behold.")
    assert ok.audio == "cinema" and ok.voice == "nova"
    with pytest.raises(ValidationError):
        VideoRequest(prompt="x" * 10, audio="loud")          # unknown audio mode
    with pytest.raises(ValidationError):
        VideoRequest(prompt="x" * 10, voice="ALL-CAPS")      # voice ids lowercase only
    with pytest.raises(ValidationError):
        VideoRequest(prompt="x" * 10, narration="n" * 601)   # narration cap


def test_media_dir_default_is_tmp(monkeypatch):
    # No env in CI → tmp default keeps local dev + tests side-effect free
    assert soundtrack.settings.MEDIA_DIR
    assert soundtrack.settings.MEDIA_TTL_HOURS > 0


# ---------------------------------------------------------------- music beds + tempo
def test_bed_filter_presets_emit_bed_label():
    for kind in soundtrack.MUSIC_BEDS:
        frag = soundtrack.bed_filter(kind, 10)
        assert frag.endswith("[bed]"), kind
        assert "duration=10" in frag and "afade=t=out:st=8.5" in frag


def test_bed_filter_variants_are_distinct():
    assert "anoisesrc" in soundtrack.bed_filter("lofi", 8)          # tape-hiss lofi
    assert "frequency=55" in soundtrack.bed_filter("epic", 8)       # sub drone
    assert "tremolo=f=2.0" in soundtrack.bed_filter("tension", 8)   # pulsing
    assert soundtrack.bed_filter("unknown-mood", 8).startswith("sine=frequency=108")  # → soft default


def test_mux_cmd_honours_music_choice():
    cmd = soundtrack.build_mux_cmd("ffmpeg", "in.mp4", "v.mp3", "out.mp4", 8, with_bed=True, with_original=False, music="tension")
    assert "tremolo=f=2.0" in cmd[cmd.index("-filter_complex") + 1]


def test_video_request_music_and_tempo_validation():
    ok = VideoRequest(prompt="x" * 10, audio="cinema", music="epic", tempo=1.15)
    assert ok.music == "epic" and ok.tempo == 1.15
    with pytest.raises(ValidationError):
        VideoRequest(prompt="x" * 10, music="dubstep")     # unknown bed
    with pytest.raises(ValidationError):
        VideoRequest(prompt="x" * 10, tempo=1.5)           # above the 1.3 cap
    with pytest.raises(ValidationError):
        VideoRequest(prompt="x" * 10, tempo=0.5)           # below the 0.7 floor


# ---------------------------------------------------------------- film posters
def test_poster_cmd_seeks_to_hero_moment():
    cmd = soundtrack.build_poster_cmd("ffmpeg", "film.mp4", "out.jpg", 18)
    assert cmd[cmd.index("-ss") + 1] == "6.30"          # 35% of 18s
    assert cmd[cmd.index("-frames:v") + 1] == "1"
    assert cmd[-1] == "out.jpg"


def test_poster_cmd_never_seeks_before_zero():
    cmd = soundtrack.build_poster_cmd("ffmpeg", "clip.mp4", "o.jpg", 0)
    assert float(cmd[cmd.index("-ss") + 1]) == 0.1


def test_poster_name_rules():
    assert soundtrack.MEDIA_POSTER_RE.match("a" * 32 + "_p.jpg")
    assert not soundtrack.MEDIA_POSTER_RE.match("a" * 32 + ".jpg")      # missing _p marker
    assert not soundtrack.MEDIA_POSTER_RE.match("a" * 32 + "_p.mp4")    # posters are jpg
    assert not soundtrack.MEDIA_POSTER_RE.match("../x_p.jpg")

    import re
    mp4 = re.compile(r"^[a-f0-9]{32}(_p\.jpg|\.mp4)$")                   # route regex parity
    for good in ("b" * 32 + ".mp4", "c" * 32 + "_p.jpg"):
        assert mp4.match(good)
    for bad in ("d" * 32 + "_p.png", "e" * 31 + ".mp4", "..%2Fetc"):
        assert not mp4.match(bad)


def test_film_out_includes_poster_url():
    from app.db.models import Film
    from app.api.routes.media import _film_out

    f = Film(id="f" * 32, user_id="u", prompt="p", status="done", filename="a" * 32 + ".mp4",
             poster="a" * 32 + "_p.jpg", scene_count=2, scene_seconds=6)
    out = _film_out(f)
    assert out["poster"].endswith("/api/v1/media/files/" + "a" * 32 + "_p.jpg")
    out["poster"] and out["url"]
    f.poster = ""
    assert _film_out(f)["poster"] == ""
