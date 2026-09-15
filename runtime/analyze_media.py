#!/usr/bin/env python3
"""Fast deterministic content analysis for edit planning.

Uses ffprobe/ffmpeg only: stream metadata, scene-change timestamps, silence ranges,
black ranges and coarse loudness. The agent can combine this with transcript and
multimodal frame inspection for editorial decisions.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path


SCENE_RE = re.compile(r"pts_time:([0-9.]+)")
SILENCE_START_RE = re.compile(r"silence_start: (-?[0-9.]+)")
SILENCE_END_RE = re.compile(r"silence_end: (-?[0-9.]+)")
BLACK_RE = re.compile(r"black_start:([0-9.]+) black_end:([0-9.]+) black_duration:([0-9.]+)")
LOUDNESS_I_RE = re.compile(r"I:\s*(-?[0-9.]+) LUFS")
PEAK_RE = re.compile(r"Peak:\s*(-?[0-9.]+) dBFS")


def run(cmd):
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout, p.stderr


def parse_scenes(stderr_text):
    return [float(x) for x in SCENE_RE.findall(stderr_text)]


def parse_silence(stderr_text):
    # silencedetect may report a negative start when the media begins silent.
    starts = [float(x) for x in SILENCE_START_RE.findall(stderr_text)]
    ends = [float(x) for x in SILENCE_END_RE.findall(stderr_text)]
    return [{"start": a, "end": ends[i] if i < len(ends) else None} for i, a in enumerate(starts)]


def parse_black(stderr_text):
    return [
        {"start": float(a), "end": float(b), "duration": float(d)}
        for a, b, d in BLACK_RE.findall(stderr_text)
    ]


def parse_loudness(stderr_text):
    im = LOUDNESS_I_RE.findall(stderr_text)
    pm = PEAK_RE.findall(stderr_text)
    return {
        "integrated_lufs": float(im[-1]) if im else None,
        "true_peak_dbfs": float(pm[-1]) if pm else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("--out", required=True)
    ap.add_argument("--scene-threshold", type=float, default=0.35)
    ap.add_argument("--min-silence", type=float, default=0.5)
    ns = ap.parse_args()
    media = Path(ns.media).resolve()
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise SystemExit("ffmpeg and ffprobe are required")

    code, out, err = run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(media)])
    probe = json.loads(out) if code == 0 else {"error": err[-4000:]}

    scene_expr = f"select='gt(scene,{ns.scene_threshold})',showinfo"
    _, _, scene_err = run([ffmpeg, "-hide_banner", "-nostats", "-i", str(media), "-vf", scene_expr, "-an", "-f", "null", "-"])
    scenes = parse_scenes(scene_err)

    _, _, silence_err = run([ffmpeg, "-hide_banner", "-nostats", "-i", str(media), "-af", f"silencedetect=noise=-42dB:d={ns.min_silence}", "-vn", "-f", "null", "-"])
    silence = parse_silence(silence_err)

    _, _, black_err = run([ffmpeg, "-hide_banner", "-nostats", "-i", str(media), "-vf", "blackdetect=d=0.15:pix_th=0.10", "-an", "-f", "null", "-"])
    black = parse_black(black_err)

    _, _, loud_err = run([ffmpeg, "-hide_banner", "-nostats", "-i", str(media), "-af", "ebur128=peak=true", "-vn", "-f", "null", "-"])
    audio = parse_loudness(loud_err[-16000:])

    payload = {
        "media": str(media), "probe": probe,
        "scene_threshold": ns.scene_threshold, "scene_changes": scenes,
        "silence_ranges": silence, "black_ranges": black,
        "audio": audio,
    }
    dst = Path(ns.out).resolve(); dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(dst)


if __name__ == "__main__":
    main()
