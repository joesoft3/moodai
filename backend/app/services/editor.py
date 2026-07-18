"""✂️ Auto video editor — upload a clip + a plain-English instruction.

The fast model turns the instruction into a normalized JSON edit plan; a chain
of pure ffmpeg argv builders executes it stage by stage (each builder is
unit-testable without the binary, matching services/soundtrack.py):

    trim → speed → reframe → subtitles (Whisper→libass burn) → grade
         → mute / music bed → brand logo stamp → <uuid>_e.mp4

Output joins the other ephemeral media files (public hex URL, 24h janitor).
"""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import settings
from .llm import llm
from .soundtrack import bed_filter, ffmpeg_path


class EditError(Exception):
    pass


# ------------------------------------------------------------------- plan
ASPECT_TARGETS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}
GRADE_FILTERS: dict[str, str] = {
    "warm": "eq=brightness=0.03:saturation=1.12,colorbalance=rs=0.08:gs=0.02:bs=-0.06",
    "cool": "eq=brightness=0.01:saturation=1.05,colorbalance=bs=0.08:rs=-0.05",
    "vivid": "eq=contrast=1.15:saturation=1.35",
    "mono": "hue=s=0,eq=contrast=1.06",
}
MUSIC_BEDS = ("soft", "epic", "lofi", "tension")


@dataclass
class EditPlan:
    trim_start: float = 0.0
    trim_end: float | None = None       # None → to the end
    speed: float = 1.0                  # 0.5 .. 2.0 (audio-safe range)
    reframe: str | None = None          # key into ASPECT_TARGETS
    subtitles: bool = False
    grade: str | None = None            # key into GRADE_FILTERS
    mute: bool = False
    music: str | None = None            # key into MUSIC_BEDS
    music_vol: float = 0.35             # bed loudness vs. original track
    stamp: bool = False                 # brand logo corner stamp
    notes: list[str] = field(default_factory=list)


EDIT_SYSTEM = """You are a professional video-editing planner.
Turn the user's plain-English instruction into ONE JSON object (no prose, no fences):
{"trim_start": 0, "trim_end": null, "speed": 1.0, "reframe": null,
 "subtitles": false, "grade": null, "mute": false, "music": null,
 "music_vol": 0.35, "stamp": false}
Rules: trim_* are seconds (null = keep to end); speed 0.5–2.0; reframe ∈ {16:9, 9:16, 1:1, 4:5} or null;
grade ∈ {warm, cool, vivid, mono} or null; music ∈ {soft, epic, lofi, tension} or null; booleans only.
"vertical/tiktok/status" → reframe 9:16 · "square" → 1:1 · "faster" → speed 1.5 ·
"black and white" → grade mono · "add music" → music soft unless a mood is named ·
"my logo" / "watermark" → stamp true · "silent/no audio" → mute true.
If nothing is requested, return the neutral object above."""


def _bounded(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def normalize_plan(raw: dict[str, Any]) -> EditPlan:
    p = EditPlan()
    p.trim_start = _bounded(raw.get("trim_start", 0), 0, 3600, 0)
    end = raw.get("trim_end")
    p.trim_end = None if end in (None, "", "null") else _bounded(end, 0.5, 3600, 0.5)
    if p.trim_end is not None and p.trim_end <= p.trim_start:
        p.trim_end = None
        p.notes.append("note: trim window was empty — kept full clip")
    p.speed = _bounded(raw.get("speed", 1.0), 0.5, 2.0, 1.0)
    r = str(raw.get("reframe") or "").strip()
    p.reframe = r if r in ASPECT_TARGETS else None
    p.subtitles = bool(raw.get("subtitles"))
    g = str(raw.get("grade") or "").strip()
    p.grade = g if g in GRADE_FILTERS else None
    p.mute = bool(raw.get("mute"))
    if p.mute:
        p.music = None  # silent wins
        p.music_vol = 0.0
    else:
        m = str(raw.get("music") or "").strip()
        p.music = m if m in MUSIC_BEDS else None
        p.music_vol = _bounded(raw.get("music_vol", 0.35), 0.05, 1.0, 0.35)
    p.stamp = bool(raw.get("stamp"))
    return p


def parse_plan_json(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


async def plan_edit(instruction: str) -> EditPlan:
    """LLM plan → normalized; heuristic fallback keeps the feature alive without an LLM."""
    try:
        out = await llm.complete(
            [{"role": "system", "content": EDIT_SYSTEM},
             {"role": "user", "content": instruction.strip()}],
            max_tokens=220, temperature=0.1,
        )
        raw = parse_plan_json(out or "")
        if raw is not None:
            return normalize_plan(raw)
    except Exception:
        pass
    plan = fallback_plan(instruction)
    plan.notes.append("LLM planner unavailable — used keyword heuristics")
    return plan


def fallback_plan(instruction: str) -> EditPlan:
    t = instruction.lower()
    p = EditPlan()
    if re.search(r"9:16|vertical|tiktok|status|story|reel", t):
        p.reframe = "9:16"
    elif re.search(r"square|1:1", t):
        p.reframe = "1:1"
    if "faster" in t or "speed up" in t:
        p.speed = 1.5
    if "slower" in t or "slow" in t and "slow-mo" in t:
        p.speed = 0.75
    if re.search(r"subtitle|caption", t):
        p.subtitles = True
    if "black and white" in t or "greyscale" in t or "grayscale" in t:
        p.grade = "mono"
    elif "warm" in t:
        p.grade = "warm"
    elif "cool" in t and "color" in t or "cinematic color" in t:
        p.grade = "cool"
    if re.search(r"music|soundtrack|bed", t) and "no music" not in t:
        p.music = next((b for b in MUSIC_BEDS if b in t), "soft")
    if re.search(r"mute|silent|no audio|remove (the )?(audio|sound)", t):
        p.mute, p.music = True, None
    if re.search(r"logo|watermark|brand(ing)?", t):
        p.stamp = True
    m = re.search(r"(?:cut|trim|remove)\s+(?:the )?(?:first|intro)\D*(\d+)", t)
    if m:
        p.trim_start = _bounded(m.group(1), 0, 3600, 0)
    m = re.search(r"(?:keep|use)\s+(?:only\s+)?(?:the\s+)?first\s+(\d+)\s*(?:s|sec|second)", t)
    if m:
        p.trim_end = _bounded(m.group(1), 0.5, 3600, 0.5)
    return p


# ------------------------------------------------------------- argv stages
def build_trim_cmd(src: str, dst: str, start: float, end: float | None) -> list[str]:
    cmd = [ffmpeg_path() or "ffmpeg", "-y"]
    if start > 0:
        cmd += ["-ss", f"{start:.2f}"]
    cmd += ["-i", src]
    if end is not None and end > start:
        cmd += ["-t", f"{end - start:.2f}"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", dst]
    return cmd


def build_speed_cmd(src: str, dst: str, factor: float) -> list[str]:
    f = max(0.5, min(2.0, factor))
    filt = f"[0:v]setpts={'1/' + str(f) if f != 1 else '1.0'}*PTS[v]"
    media: list[str] = ["-filter_complex", filt + f";[0:a]atempo={f:.2f}[a]",
                        "-map", "[v]", "-map", "[a]"]
    cmd = [ffmpeg_path() or "ffmpeg", "-y", "-i", src] + media + [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", dst]
    return cmd


def build_speed_silent_cmd(src: str, dst: str, factor: float) -> list[str]:
    f = max(0.5, min(2.0, factor))
    return [ffmpeg_path() or "ffmpeg", "-y", "-i", src,
            "-vf", f"setpts={'1/' + str(f) if f != 1 else '1.0'}*PTS",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", dst]


def build_reframe_cmd(src: str, dst: str, aspect: str) -> list[str]:
    w, h = ASPECT_TARGETS[aspect]
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}"
    return [ffmpeg_path() or "ffmpeg", "-y", "-i", src, "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "copy", dst]


def build_grade_cmd(src: str, dst: str, look: str) -> list[str]:
    return [ffmpeg_path() or "ffmpeg", "-y", "-i", src, "-vf", GRADE_FILTERS[look],
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "copy", dst]


def build_burn_subs_cmd(src: str, dst: str, srt_path: str) -> list[str]:
    style = "FontSize=15,Outline=2,BackColour=&H64000000,PrimaryColour=&H00FFFFFF"
    return [ffmpeg_path() or "ffmpeg", "-y", "-i", src,
            "-vf", f"subtitles={srt_path}:force_style='{style}'",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "copy", dst]


def build_mute_cmd(src: str, dst: str) -> list[str]:
    return [ffmpeg_path() or "ffmpeg", "-y", "-i", src, "-c:v", "copy", "-an", dst]


def build_music_cmd(src: str, dst: str, bed: str, seconds: int, vol: float,
                    has_audio: bool = True) -> list[str]:
    bedf = bed_filter(bed, seconds)
    if has_audio:
        graph = (f"{bedf.replace('[bed]', '[bg]')};"
                 f"[0:a][bg]amix=inputs=2:duration=first:weights='1 {vol:.2f}'[a]")
    else:
        graph = f"{bedf.replace('[bed]', '[bg]')};[bg]volume=1.0[a]"
    return [ffmpeg_path() or "ffmpeg", "-y", "-i", src,
            "-filter_complex", graph, "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", dst]


def build_stamp_cmd(src: str, logo: str, dst: str, stamp_w: int = 140, pad: int = 24) -> list[str]:
    graph = f"[1:v]scale={stamp_w}:-1[st];[0:v][st]overlay=W-w-{pad}:H-h-{pad}"
    return [ffmpeg_path() or "ffmpeg", "-y", "-i", src, "-i", logo,
            "-filter_complex", graph,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "copy", dst]


# ------------------------------------------------------------------ helpers
def _run(cmd: list[str], timeout: int = 600) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    dst = cmd[-1]
    if proc.returncode != 0 or (isinstance(dst, str) and dst.endswith((".mp4", ".wav")) and not Path(dst).exists()):
        raise EditError(f"edit stage failed: {(proc.stderr or '')[-400:]}")


def ffprobe_seconds(path: Path) -> float:
    ffprobe = (ffmpeg_path() or "ffmpeg").replace("ffmpeg", "ffprobe")
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30)
        return max(0.1, float(out.stdout.strip()))
    except Exception:
        return 60.0


def has_audio_stream(path: Path) -> bool:
    ffprobe = (ffmpeg_path() or "ffmpeg").replace("ffmpeg", "ffprobe")
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=codec_type", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30)
        return "audio" in out.stdout
    except Exception:
        return True  # assume yes → amix path


async def transcribe_srt(video_path: Path, work: Path) -> Path | None:
    """OpenAI Whisper → .srt (None when the provider isn't configured/fails)."""
    if not settings.OPENAI_API_KEY:
        return None
    wav = work / "voice.wav"
    _run([ffmpeg_path() or "ffmpeg", "-y", "-i", str(video_path),
          "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], timeout=180)
    if not wav.exists():
        return None
    try:
        with open(wav, "rb") as fh:
            res = await llm.client.audio.transcriptions.create(
                model="whisper-1", file=fh, response_format="srt")
        srt = work / "subs.srt"
        srt.write_text(str(res), encoding="utf-8")
        return srt
    except Exception:
        return None


# ---------------------------------------------------------------- pipeline
async def run_edit(src_path: Path, plan: EditPlan, brand_logo_file: str = "") -> tuple[str, list[str]]:
    """Execute the plan; returns (output filename in MEDIA_DIR, notes)."""
    if not ffmpeg_path():
        raise EditError("ffmpeg unavailable on this host")
    if not src_path.exists():
        raise EditError("source clip missing")
    work = Path(f"/tmp/mood-edit-{uuid.uuid4().hex}")
    work.mkdir(parents=True, exist_ok=True)
    cur = src_path
    stage = 0
    notes = list(plan.notes)

    def nxt() -> Path:
        nonlocal stage
        stage += 1
        return work / f"s{stage:02d}.mp4"

    try:
        if plan.trim_start > 0 or plan.trim_end is not None:
            out = nxt(); _run(build_trim_cmd(str(cur), str(out), plan.trim_start, plan.trim_end)); cur = out
        if abs(plan.speed - 1.0) > 0.01:
            out = nxt()
            if has_audio_stream(cur):
                _run(build_speed_cmd(str(cur), str(out), plan.speed))
            else:
                _run(build_speed_silent_cmd(str(cur), str(out), plan.speed))
            cur = out
        if plan.reframe:
            out = nxt(); _run(build_reframe_cmd(str(cur), str(out), plan.reframe)); cur = out
        if plan.subtitles:
            srt = await transcribe_srt(cur, work)
            if srt:
                out = nxt(); _run(build_burn_subs_cmd(str(cur), str(out), str(srt))); cur = out
            else:
                notes.append("subtitles skipped — voice provider not configured")
        if plan.grade:
            out = nxt(); _run(build_grade_cmd(str(cur), str(out), plan.grade)); cur = out
        if plan.mute:
            out = nxt(); _run(build_mute_cmd(str(cur), str(out))); cur = out
        elif plan.music:
            out = nxt()
            secs = int(ffprobe_seconds(cur)) + 1
            _run(build_music_cmd(str(cur), str(out), plan.music, secs, plan.music_vol,
                                 has_audio=has_audio_stream(cur)))
            cur = out
        if plan.stamp and brand_logo_file:
            logo = Path(settings.MEDIA_DIR) / brand_logo_file
            if logo.exists():
                out = nxt(); _run(build_stamp_cmd(str(cur), str(logo), str(out))); cur = out
            else:
                notes.append("logo stamp skipped — brand logo file missing")

        name = f"{uuid.uuid4().hex}_e.mp4"
        dst = Path(settings.MEDIA_DIR)
        dst.mkdir(parents=True, exist_ok=True)
        final = dst / name
        if cur is src_path and stage == 0:
            _run([ffmpeg_path() or "ffmpeg", "-y", "-i", str(cur), "-c:v", "libx264",
                  "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "128k", str(final)])
            notes.append("no ops matched — delivered a clean re-encode")
        else:
            final.write_bytes(cur.read_bytes())
        return name, notes
    finally:
        try:
            for f in work.glob("*"):
                f.unlink(missing_ok=True)
            work.rmdir()
        except OSError:
            pass
