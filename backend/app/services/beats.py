"""🎵 Beat-sync analyzer — stdlib-only onset detection.

Decodes audio to 8 kHz mono PCM with ffmpeg, builds an RMS energy envelope,
and picks beats as onset peaks (sudden energy rises). No numpy/librosa — the
math is a few tight loops over an ``array('h')``, fast enough for 4‑min clips.

Pure pieces (``energy_env``, ``pick_beats``, ``bpm_estimate``,
``suggest_caption_marks``) are unit-testable on synthetic envelopes — no
binary, no network — matching the services/soundtrack.py philosophy.
"""

from __future__ import annotations

import subprocess
from array import array
from pathlib import Path
from typing import Any

from .soundtrack import ffmpeg_path


class BeatError(Exception):
    pass


SAMPLE_RATE = 8000          # enough temporal detail for onset detection
HOP = 256                   # envelope hop (samples) → 32 ms resolution
WIN = 512                   # RMS window (samples) → 64 ms
MIN_GAP_S = 0.25            # refractory period between beats
MAX_BEATS = 96              # cap for filtergraph size


# ------------------------------------------------------------------- decode
def decode_pcm(path: Path, seconds_cap: int = 240) -> array:
    """Mixed-down mono s16le PCM via ffmpeg → array('h')."""
    ff = ffmpeg_path() or "ffmpeg"
    cmd = [ff, "-v", "error", "-i", str(path),
           "-t", str(seconds_cap), "-vn", "-ac", "1",
           "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BeatError(f"audio decode failed: {e}")
    if out.returncode != 0 or not out.stdout:
        raise BeatError("no decodable audio stream")
    pcm = array("h")
    pcm.frombytes(out.stdout[: len(out.stdout) // 2 * 2])
    return pcm


# ----------------------------------------------------------------- envelope
def energy_env(pcm: array, win: int = WIN, hop: int = HOP) -> list[float]:
    """RMS energy per hop window, lightly smoothed (3-tap moving average)."""
    n = len(pcm)
    if n < win:
        return []
    raw: list[float] = []
    for start in range(0, n - win + 1, hop):
        acc = 0
        for i in range(start, start + win):
            v = pcm[i]
            acc += v * v
        raw.append((acc / win) ** 0.5)
    if len(raw) < 3:
        return raw
    sm = [raw[0]]
    for i in range(1, len(raw) - 1):
        sm.append((raw[i - 1] + raw[i] + raw[i + 1]) / 3.0)
    sm.append(raw[-1])
    return sm


def env_times(n_windows: int, hop: int = HOP, rate: int = SAMPLE_RATE) -> list[float]:
    return [round(i * hop / rate, 3) for i in range(n_windows)]


# -------------------------------------------------------------------- beats
def pick_beats(env: list[float], min_gap_s: float = MIN_GAP_S,
               max_beats: int = MAX_BEATS) -> list[float]:
    """Onset peaks in the energy envelope → beat times (seconds)."""
    if len(env) < 4:
        return []
    strength = [0.0] + [max(0.0, env[i] - env[i - 1]) for i in range(1, len(env))]
    peak = max(strength)
    if peak <= 0:
        return []
    mean = sum(strength) / len(strength)
    var = sum((s - mean) ** 2 for s in strength) / len(strength)
    thr = max(0.30 * peak, mean + 0.9 * (var ** 0.5))
    min_gap_win = max(1, round(min_gap_s * SAMPLE_RATE / HOP))

    beats: list[float] = []
    last = -min_gap_win
    for i in range(1, len(strength) - 1):
        s = strength[i]
        if s < thr or not (s >= strength[i - 1] and s >= strength[i + 1]):
            continue
        if i - last < min_gap_win:
            continue
        beats.append(round(i * HOP / SAMPLE_RATE, 3))
        last = i
        if len(beats) >= max_beats:
            break
    return beats


def bpm_estimate(beats: list[float]) -> int | None:
    """Median inter-beat interval → BPM, octave-folded into 70–180."""
    if len(beats) < 3:
        return None
    gaps = sorted(b2 - b1 for b1, b2 in zip(beats, beats[1:]) if b2 - b1 > 0.05)
    if not gaps:
        return None
    med = gaps[len(gaps) // 2]
    bpm = 60.0 / med
    while bpm < 70:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    return round(bpm)


def suggest_caption_marks(env: list[float], beats: list[float],
                          limit: int = 8) -> list[dict[str, Any]]:
    """Energy-aware caption hints — where a hook/drop line would land.

    Returns up to ``limit`` marks like {"time": 2.03, "kind": "drop"|"pulse"}:
    beats whose local energy outruns the rolling median get "drop" (great spot
    for a punchy caption); the rest are steady "pulse" markers.
    """
    if not env or not beats:
        return []
    half = max(2, round(1.0 * SAMPLE_RATE / HOP))    # ±1 s window

    def level_at(t: float) -> float:
        i = min(len(env) - 1, max(0, round(t * SAMPLE_RATE / HOP)))
        lo, hi = max(0, i - half), min(len(env), i + half)
        window = sorted(env[lo:hi])
        return window[len(window) // 2] if window else 0.0

    marks = []
    for b in beats:
        i = min(len(env) - 1, max(0, round(b * SAMPLE_RATE / HOP)))
        med = level_at(b)
        marks.append({"time": b, "kind": "drop" if med > 0 and env[i] > 1.6 * med else "pulse"})
    drops = [m for m in marks if m["kind"] == "drop"]
    keep = drops[: limit // 2] + [m for m in marks if m["kind"] != "drop"]
    keep.sort(key=lambda m: m["time"])
    return keep[:limit]


# ------------------------------------------------------------------ analysis
def analyze(path: Path) -> dict[str, Any]:
    """Full pass → {bpm, beats, count, marks, duration_s} (raises BeatError)."""
    pcm = decode_pcm(path)
    env = energy_env(pcm)
    beats = pick_beats(env)
    return {
        "bpm": bpm_estimate(beats),
        "beats": beats,
        "count": len(beats),
        "marks": suggest_caption_marks(env, beats),
        "duration_s": round(len(pcm) / SAMPLE_RATE, 2),
    }
