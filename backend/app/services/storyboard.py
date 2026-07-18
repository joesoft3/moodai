"""🎬 Storyboard mode — one idea, N directed scenes, one continuous film.

The director model splits the idea into 2–4 scene shots, each with its own
voiceover line. We render every scene, stitch them with ffmpeg (normalized
scale/pad/fps → concat), record each scene's narration, lay the scenes'
voices back-to-back so the story flows across cuts, add the procedural
ambience bed + EBU R128 loudness polish, and can burn the narration in as
subtitle text. All repairs degrade gracefully (voice-only, no subtitles).
"""

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Callable

import httpx

from ..config import settings
from . import soundtrack
from .llm import llm
from .media import VideoOptions, video

log = logging.getLogger(__name__)

ASPECT_DIMS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (720, 720)}
MAX_SCENES = 4


@dataclass
class Scene:
    shot: str          # visual direction sent to the video provider
    narration: str     # voiceover line spoken over that scene
    voice: str = "a"   # "a" | "b" — which narrator speaks (dialogue films)


@dataclass
class StoryboardResult:
    filename: str
    scenes: list = field(default_factory=list)   # of Scene
    mode: str = "voice"                          # voice | voice+ambience | none
    subtitles: bool = False
    poster: str = ""                             # `<uuid>_p.jpg` hero frame in MEDIA_DIR


class StoryboardError(Exception):
    pass


# ------------------------------------------------------------------- planning
PLAN_PROMPT = """You are a film director planning a {n}-scene short (each scene ~{secs}s) from one idea.
Return STRICT JSON ONLY — an array of {n} objects:
[{{"shot": "...", "narration": "..."}}]
- shot: one dense cinematic video-generation prompt (subject, action, environment, camera move, light), ≤40 words, self-contained per scene.
- narration: ONE spoken line, ≤{words_per_scene} words, trailer-grade, present tense, no stage cues.
- The scenes must tell ONE continuous mini-story (setup → build → payoff), consistent style and subject."""


DIALOGUE_PROMPT = """You are a film director planning a {n}-scene short (each scene ~{secs}s) with TWO narrators
trading lines like a trailer conversation: "a" (warm, scene-setting) and "b" (edgy, punchy counters).
Return STRICT JSON ONLY — an array of {n} objects:
[{{"shot": "...", "narration": "...", "voice": "a"}}]
- shot: one dense cinematic video-generation prompt (subject, action, environment, camera move, light), ≤40 words, self-contained per scene.
- narration: ONE spoken line, ≤{words_per_scene} words, no stage cues.
- voice: "a" or "b" — alternate speakers so the film feels like a duet (open on "a").
- The scenes must tell ONE continuous mini-story (setup → build → payoff), consistent style and subject."""


def _parse_scenes(raw: str, expected: int, dialogue: bool = False) -> list[Scene]:
    """Tolerantly pull a JSON scene array out of model output."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise StoryboardError("planner returned no JSON array")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise StoryboardError(f"planner JSON broken: {e}") from e
    if not isinstance(data, list) or not data:
        raise StoryboardError("planner returned an empty storyboard")
    scenes = []
    for item in data[:MAX_SCENES]:
        if not isinstance(item, dict):
            continue
        shot = str(item.get("shot", "")).strip()
        narration = str(item.get("narration", "")).strip()
        voice_tag = str(item.get("voice", "a")).strip().lower()
        if shot:
            scenes.append(Scene(shot=shot[:400], narration=narration[:200], voice="b" if (dialogue and voice_tag == "b") else "a"))
    if not scenes:
        raise StoryboardError("planner scenes had no shots")
    if expected and len(scenes) != expected:
        log.warning("storyboard planner gave %d scenes, asked %d — proceeding", len(scenes), expected)
    return scenes


async def plan_scenes(prompt: str, count: int, scene_seconds: int, dialogue: bool = False) -> list[Scene]:
    words_per_scene = soundtrack.estimate_word_budget(scene_seconds)
    template = DIALOGUE_PROMPT if dialogue else PLAN_PROMPT
    try:
        raw = await llm.complete(
            [
                {"role": "system", "content": template.format(n=count, secs=scene_seconds, words_per_scene=words_per_scene)},
                {"role": "user", "content": prompt.strip()},
            ],
            temperature=0.7,
            max_tokens=560,
        )
    except Exception as e:
        raise StoryboardError(f"storyboard planner unavailable ({type(e).__name__})") from e
    scenes = _parse_scenes(raw, count, dialogue)
    budget = soundtrack.estimate_word_budget(scene_seconds)
    for s in scenes:
        s.narration = soundtrack.fit_words(s.narration, budget)
    return scenes


def parse_custom_scenes(raw: list, budget_seconds: int) -> list[Scene]:
    """User scenes: 'shot text' / 'shot text || narration line' per entry, or
    persisted dicts {"shot", "narration", "voice"} (resume re-mix path)."""
    budget = soundtrack.estimate_word_budget(budget_seconds)
    scenes = []
    for line in raw:
        if isinstance(line, dict):
            shot = str(line.get("shot", "")).strip()
            narr = str(line.get("narration", "")).strip()
            if shot:
                scenes.append(Scene(shot=shot[:400], narration=soundtrack.fit_words(narr, budget) if narr else "",
                                    voice="b" if line.get("voice") == "b" else "a"))
            continue
        shot, _, narr = str(line).partition("||")
        shot = shot.strip()
        if shot:
            scenes.append(Scene(shot=shot[:400], narration=soundtrack.fit_words(narr.strip(), budget) if narr.strip() else ""))
    return scenes


# ------------------------------------------------------------------- subtitles
def _srt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(scenes: list[Scene], scene_seconds: int) -> str:
    """One subtitle cue per scene, timed to that scene's slot; empty narrations skipped."""
    cues = []
    idx = 1
    for i, scene in enumerate(scenes):
        if not scene.narration.strip():
            continue
        start = i * scene_seconds
        end = start + scene_seconds - 0.15
        cues.append(f"{idx}\n{_srt_ts(start)} --> {_srt_ts(end)}\n{scene.narration.strip()}\n")
        idx += 1
    return "\n".join(cues)


# ------------------------------------------------------------------- stitching
def build_stitch_cmd(
    ffbin: str,
    clips: list[str],
    voices: list[str] | None,
    out: str,
    *,
    scene_seconds: int,
    aspect: str,
    with_bed: bool,
    music: str = "soft",
) -> list[str]:
    """Pure argv: normalize every clip (scale/pad/fps), concat scene pairs, mix
    the per-scene voices back-to-back, add the ambience bed, loudness polish."""
    w, h = ASPECT_DIMS.get(aspect, ASPECT_DIMS["16:9"])
    n = len(clips)
    t = max(1, int(scene_seconds))
    total = t * n
    cmd = [ffbin, "-y"]
    for c in clips:
        cmd += ["-i", c]
    if voices:
        for v in voices:
            cmd += ["-i", v]
    filters = []
    pairs = []
    for i in range(n):
        filters.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24[v{i}]"
        )
        if voices:
            filters.append(
                f"[{n + i}:a]aresample=44100,apad=whole_dur={t},atrim=0:{t},"
                f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100,atrim=0:{t}[a{i}]"
            )
        pairs.append(f"[v{i}]" + (f"[a{i}]" if voices else ""))
    filters.append(f"{''.join(pairs)}concat=n={n}:v=1:a={1 if voices else 0}[v]" + ("[a0]" if voices else ""))
    audio_out = None
    if voices:
        if with_bed:
            filters.append(soundtrack.bed_filter(music, total))
            filters.append("[a0][bed]amix=inputs=2:duration=first:normalize=0[aout]")
            audio_out = "[aout]"
        else:
            audio_out = "[a0]"
    cmd += ["-filter_complex", ";".join(filters), "-map", "[v]"]
    if audio_out:
        cmd += ["-map", audio_out, "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-t", str(total), out]
    return cmd


SUBTITLE_STYLE = "FontSize=%d,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=%d,Alignment=2"


def _escape_sub_path(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build_subtitle_burn_cmd(ffbin: str, video_in: str, srt_path: str, out: str, aspect: str) -> list[str]:
    h = ASPECT_DIMS.get(aspect, (1280, 720))[1]
    fontsize = max(16, h // 26)
    style = SUBTITLE_STYLE % (fontsize, h // 22)
    return [
        ffbin, "-y", "-i", video_in,
        "-vf", f"subtitles='{_escape_sub_path(srt_path)}':force_style='{style}'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", out,
    ]


# ------------------------------------------------------------------- pipeline
async def _download(http: httpx.AsyncClient, url: str, path: str) -> None:
    cap = settings.VIDEO_MAX_DOWNLOAD_MB * 1024 * 1024
    async with http.stream("GET", url) as r:
        r.raise_for_status()
        written = 0
        with open(path, "wb") as fh:
            async for chunk in r.aiter_bytes(1 << 16):
                written += len(chunk)
                if written > cap:
                    raise ValueError("scene clip exceeds download cap")
                fh.write(chunk)


async def generate_storyboard(
    prompt: str,
    *,
    scene_count: int,
    scene_seconds: int,
    opts: VideoOptions,
    audio: str,
    voice_name: str,
    custom_scenes: list | None,
    subtitles: bool,
    music: str = "soft",
    tempo: float = 1.0,
    dialogue: bool = False,
    voice_b: str = "onyx",
    on_scene: Callable[[int, int], None] | None = None,
    on_plan: Callable[[list], None] | None = None,
) -> tuple[StoryboardResult | None, str | None, str | None]:
    """Returns (result, note, fallback_url). On stitch failure result is None and
    fallback_url is scene 1's provider URL — the user always gets a video back."""
    ffbin = soundtrack.ffmpeg_path()
    scenes = (
        parse_custom_scenes(custom_scenes, scene_seconds)
        if custom_scenes
        else await plan_scenes(prompt, scene_count, scene_seconds, dialogue)
    )
    scene_count = len(scenes)
    want_voice = audio != "none"
    notes: list[str] = []

    # 1) Render scene clips — parallel with a small window (≈2× faster films,
    #    still provider-polite): two renders in flight at once, order preserved.
    scene_opts = VideoOptions(
        duration=max(5, min(scene_seconds, 8)),  # provider clamps to 5..15
        aspect_ratio=opts.aspect_ratio,
        quality=opts.quality,
        style=opts.style,
        negative_prompt=opts.negative_prompt,
    )
    if on_plan:
        on_plan(scenes)
    import asyncio
    sem = asyncio.Semaphore(2)
    progress = {"done": 0}

    async def _render(i: int, shot: str) -> tuple[int, str]:
        async with sem:
            url, _i2v = await video.generate(shot, scene_opts)
            progress["done"] += 1
            if on_scene:
                on_scene(progress["done"], scene_count)
            return i, url

    results = await asyncio.gather(*(_render(i, sc.shot) for i, sc in enumerate(scenes)))
    urls = [u for _, u in sorted(results)]

    os.makedirs(settings.MEDIA_DIR, exist_ok=True)
    work = f"/tmp/mood-story-{uuid.uuid4().hex}"
    os.makedirs(work, exist_ok=True)
    try:
        # 2) Download scene clips
        clips = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0)) as http:
            for i, url in enumerate(urls):
                path = os.path.join(work, f"scene{i}.mp4")
                await _download(http, url, path)
                clips.append(path)

        # 3) Per-scene voiceovers (blank narration → 250ms of generated silence
        #    keeps the concat matrix symmetric). TTS hiccup mid-run → carry on silent.
        voices = None
        if want_voice:
            try:
                from .voice import voice as voice_svc

                voice_a = voice_name if voice_name in soundtrack.NARRATION_VOICES else "alloy"
                voice_b_id = voice_b if voice_b in soundtrack.NARRATION_VOICES else "onyx"
                voices = []
                for i, sc in enumerate(scenes):
                    path = os.path.join(work, f"voice{i}.mp3")
                    if sc.narration.strip():
                        scene_voice = voice_b_id if (dialogue and sc.voice == "b") else voice_a
                        audio_bytes = await voice_svc.synthesize(sc.narration, scene_voice, tempo)
                        with open(path, "wb") as fh:
                            fh.write(audio_bytes)
                    else:
                        silence = os.path.join(work, f"sil{i}.mp3")
                        await soundtrack._run(
                            [ffbin or "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                             "-t", "0.25", "-q:a", "9", silence], timeout=30)
                        path = silence
                    voices.append(path)
            except Exception as e:
                log.warning("storyboard voiceover failed (%s: %s) — stitching silent", type(e).__name__, e)
                voices = None
                notes.append("Voiceover recording failed — delivered your film silent.")

        # 4) Stitch (+mix) — full → voice-only → silent fallbacks
        if not ffbin:
            notes.append("ffmpeg unavailable on this server — delivering scene 1 of your storyboard.")
            return None, "; ".join(notes), urls[0]
        name = f"{uuid.uuid4().hex}.mp4"
        final = os.path.join(settings.MEDIA_DIR, name)
        mode = "none"
        attempts = []
        if voices:
            attempts.append((dict(with_bed=audio == "cinema"), "voice+ambience" if audio == "cinema" else "voice"))
            attempts.append((dict(with_bed=False), "voice"))
        attempts.append((None, "none"))
        ok = False
        for kwargs, attempt_mode in attempts:
            use_voices = voices if kwargs is not None else None
            if kwargs is not None and not voices:
                continue
            cmd = build_stitch_cmd(
                ffbin, clips, use_voices, final,
                scene_seconds=scene_seconds, aspect=opts.aspect_ratio,
                with_bed=(kwargs or {}).get("with_bed", False), music=music,
            )
            code, err = await soundtrack._run(cmd, timeout=600)
            if code == 0:
                mode = attempt_mode
                ok = True
                break
            log.warning("storyboard stitch attempt (%s) failed: %s", attempt_mode, err)
        if not ok:
            notes.append("Stitch failed on all fallbacks — delivering scene 1 of your storyboard.")
            return None, "; ".join(notes), urls[0]

        # 5) Optional subtitle burn-in (graceful: no subs if the pass fails)
        subs_ok = False
        if subtitles and mode != "none":
            srt = build_srt(scenes, scene_seconds)
            srt_path = os.path.join(work, "story.srt")
            with open(srt_path, "w") as fh:
                fh.write(srt)
            sub_out = os.path.join(settings.MEDIA_DIR, name)  # overwrite final
            tmp_sub = os.path.join(work, "subbed.mp4")
            code, err = await soundtrack._run(build_subtitle_burn_cmd(ffbin, final, srt_path, tmp_sub, opts.aspect_ratio), timeout=600)
            if code == 0 and os.path.exists(tmp_sub):
                os.replace(tmp_sub, sub_out)
                subs_ok = True
            else:
                log.warning("subtitle burn failed (libass?) — delivering clean captions: %s", err)

        # 6) Hero-frame poster for the gallery tile + share OG image
        poster = ""
        if ok:
            total_seconds = scene_seconds * scene_count
            poster = await soundtrack.extract_poster(ffbin, final, settings.MEDIA_DIR, name, total_seconds)

        soundtrack._janitor(settings.MEDIA_DIR)
        return StoryboardResult(filename=name, scenes=scenes, mode=mode, subtitles=subs_ok, poster=poster), "; ".join(notes) or None, None
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
