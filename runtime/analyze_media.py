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


def run(cmd):
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout, p.stderr


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
    scenes = [float(x) for x in re.findall(r"pts_time:([0-9.]+)", scene_err)]

    _, _, silence_err = run([ffmpeg, "-hide_banner", "-nostats", "-i", str(media), "-af", f"silencedetect=noise=-42dB:d={ns.min_silence}", "-vn", "-f", "null", "-"])
    sstarts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", silence_err)]
    sends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", silence_err)]
    silence = [{"start": a, "end": sends[i] if i < len(sends) else None} for i, a in enumerate(sstarts)]

    _, _, black_err = run([ffmpeg, "-hide_banner", "-nostats", "-i", str(media), "-vf", "blackdetect=d=0.15:pix_th=0.10", "-an", "-f", "null", "-"])
    black = [
        {"start": float(a), "end": float(b), "duration": float(d)}
        for a, b, d in re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+) black_duration:([0-9.]+)", black_err)
    ]

    _, _, loud_err = run([ffmpeg, "-hide_banner", "-nostats", "-i", str(media), "-af", "ebur128=peak=true", "-vn", "-f", "null", "-"])
    im = re.findall(r"I:\s*(-?[0-9.]+) LUFS", loud_err[-16000:])
    pm = re.findall(r"Peak:\s*(-?[0-9.]+) dBFS", loud_err[-16000:])

    payload = {
        "media": str(media), "probe": probe,
        "scene_threshold": ns.scene_threshold, "scene_changes": scenes,
        "silence_ranges": silence, "black_ranges": black,
        "audio": {"integrated_lufs": float(im[-1]) if im else None, "true_peak_dbfs": float(pm[-1]) if pm else None},
    }
    dst = Path(ns.out).resolve(); dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(dst)


if __name__ == "__main__":
    main()
