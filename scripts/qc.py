#!/usr/bin/env python3
"""Deterministic render QC for Autonomous Adobe Editor.

Checks decode integrity, stream/spec conformance, black/freeze/silence events and
basic loudness. Semantic/visual edit quality remains a multimodal-agent check via
runtime/review_packet.py.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path


def run(cmd):
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {"code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def require(name):
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"Required executable not found: {name}")
    return path


def ffprobe_json(ffprobe, media):
    r = run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(media)])
    if r["code"] != 0:
        return {"ok": False, "error": r["stderr"]}
    return {"ok": True, "data": json.loads(r["stdout"])}


def filter_scan(ffmpeg, media, vf=None, af=None):
    cmd = [ffmpeg, "-hide_banner", "-nostats", "-i", str(media)]
    if vf:
        cmd += ["-vf", vf]
    if af:
        cmd += ["-af", af]
    cmd += ["-f", "null", "-"]
    return run(cmd)


def first_stream(probe, kind):
    if not probe.get("ok"):
        return None
    for s in probe["data"].get("streams", []):
        if s.get("codec_type") == kind:
            return s
    return None


def parse_fps(s):
    value = (s or {}).get("avg_frame_rate") or (s or {}).get("r_frame_rate")
    try:
        if not value or value == "0/0":
            return None
        return float(Fraction(value))
    except Exception:
        return None


def fnum(value):
    try:
        return float(value)
    except Exception:
        return None


def load_spec(path):
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def add_check(checks, name, ok, actual=None, expected=None, severity="error", detail=None):
    checks.append({"name": name, "ok": bool(ok), "actual": actual, "expected": expected, "severity": severity, "detail": detail})


def spec_checks(probe, spec):
    checks = []
    v = first_stream(probe, "video")
    a = first_stream(probe, "audio")
    fmt = probe.get("data", {}).get("format", {}) if probe.get("ok") else {}
    duration = fnum(fmt.get("duration"))
    if spec.get("videoRequired", True):
        add_check(checks, "video_stream_present", v is not None, bool(v), True)
    if "audioRequired" in spec:
        add_check(checks, "audio_stream_present", (a is not None) == bool(spec["audioRequired"]), bool(a), bool(spec["audioRequired"]))
    if v:
        if "width" in spec:
            add_check(checks, "width", v.get("width") == int(spec["width"]), v.get("width"), int(spec["width"]))
        if "height" in spec:
            add_check(checks, "height", v.get("height") == int(spec["height"]), v.get("height"), int(spec["height"]))
        if "fps" in spec:
            actual = parse_fps(v)
            target = float(spec["fps"])
            tol = float(spec.get("fpsTolerance", 0.02))
            add_check(checks, "fps", actual is not None and abs(actual - target) <= tol, actual, target, detail=f"tolerance={tol}")
        if "videoCodec" in spec:
            add_check(checks, "video_codec", str(v.get("codec_name", "")).lower() == str(spec["videoCodec"]).lower(), v.get("codec_name"), spec["videoCodec"])
        if "pixelFormat" in spec:
            add_check(checks, "pixel_format", v.get("pix_fmt") == spec["pixelFormat"], v.get("pix_fmt"), spec["pixelFormat"])
    if a:
        if "audioCodec" in spec:
            add_check(checks, "audio_codec", str(a.get("codec_name", "")).lower() == str(spec["audioCodec"]).lower(), a.get("codec_name"), spec["audioCodec"])
        if "sampleRate" in spec:
            add_check(checks, "sample_rate", int(a.get("sample_rate") or 0) == int(spec["sampleRate"]), int(a.get("sample_rate") or 0), int(spec["sampleRate"]))
        if "audioChannels" in spec:
            add_check(checks, "audio_channels", int(a.get("channels") or 0) == int(spec["audioChannels"]), int(a.get("channels") or 0), int(spec["audioChannels"]))
    if "duration" in spec and duration is not None:
        target = float(spec["duration"])
        tol = float(spec.get("durationTolerance", 0.25))
        add_check(checks, "duration", abs(duration - target) <= tol, duration, target, detail=f"tolerance={tol}s")
    if "minDuration" in spec and duration is not None:
        add_check(checks, "min_duration", duration >= float(spec["minDuration"]), duration, float(spec["minDuration"]))
    if "maxDuration" in spec and duration is not None:
        add_check(checks, "max_duration", duration <= float(spec["maxDuration"]), duration, float(spec["maxDuration"]))
    return checks


def main():
    ap = argparse.ArgumentParser(description="Automated QC for rendered video")
    ap.add_argument("media")
    ap.add_argument("--out", default=None)
    ap.add_argument("--spec", help="JSON delivery spec")
    ap.add_argument("--strict", action="store_true", help="fail on detected black/freeze/silence policy violations too")
    args = ap.parse_args()

    media = Path(args.media).resolve()
    if not media.exists():
        raise SystemExit(f"File not found: {media}")
    spec = load_spec(args.spec)
    ffmpeg = require("ffmpeg")
    ffprobe = require("ffprobe")
    probe = ffprobe_json(ffprobe, media)

    report = {
        "media": str(media), "probe": probe, "spec": spec, "checks": spec_checks(probe, spec),
        "decode": {}, "blackdetect": {}, "freezedetect": {}, "silencedetect": {}, "ebur128": {}, "summary": {}
    }

    decode = run([ffmpeg, "-v", "error", "-i", str(media), "-f", "null", "-"])
    report["decode"] = {"ok": decode["code"] == 0, "returncode": decode["code"], "errors": decode["stderr"]}
    add_check(report["checks"], "decode_integrity", decode["code"] == 0, decode["code"], 0)

    black = filter_scan(ffmpeg, media, vf="blackdetect=d=0.20:pix_th=0.10")
    ranges = re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+) black_duration:([0-9.]+)", black["stderr"])
    report["blackdetect"] = {"returncode": black["code"], "events": ranges}

    freeze = filter_scan(ffmpeg, media, vf="freezedetect=n=-50dB:d=2")
    starts = re.findall(r"freeze_start: ([0-9.]+)", freeze["stderr"])
    durations = re.findall(r"freeze_duration: ([0-9.]+)", freeze["stderr"])
    report["freezedetect"] = {"returncode": freeze["code"], "starts": starts, "durations": durations}

    audio = first_stream(probe, "audio")
    if audio:
        silence = filter_scan(ffmpeg, media, af="silencedetect=noise=-45dB:d=1.0")
        report["silencedetect"] = {
            "returncode": silence["code"],
            "starts": re.findall(r"silence_start: ([0-9.]+)", silence["stderr"]),
            "ends": re.findall(r"silence_end: ([0-9.]+)", silence["stderr"]),
        }
        loud = filter_scan(ffmpeg, media, af="ebur128=peak=true")
        summary = loud["stderr"][-16000:]
        lufs_matches = re.findall(r"I:\s*(-?[0-9.]+) LUFS", summary)
        peak_matches = re.findall(r"Peak:\s*(-?[0-9.]+) dBFS", summary)
        lufs = float(lufs_matches[-1]) if lufs_matches else None
        peak = float(peak_matches[-1]) if peak_matches else None
        report["ebur128"] = {"returncode": loud["code"], "integrated_lufs": lufs, "true_peak_dbfs": peak}
        if "targetLufs" in spec and lufs is not None:
            target = float(spec["targetLufs"]); tol = float(spec.get("lufsTolerance", 1.0))
            add_check(report["checks"], "integrated_loudness", abs(lufs-target) <= tol, lufs, target, detail=f"tolerance={tol} LU")
        if "maxTruePeakDbfs" in spec and peak is not None:
            target = float(spec["maxTruePeakDbfs"])
            add_check(report["checks"], "true_peak", peak <= target, peak, f"<= {target}")
    else:
        report["silencedetect"] = {"skipped": True, "reason": "no audio stream"}
        report["ebur128"] = {"skipped": True, "reason": "no audio stream"}

    if args.strict or spec.get("forbidBlackFrames"):
        add_check(report["checks"], "black_events", len(ranges) == 0, len(ranges), 0)
    if args.strict or spec.get("forbidFreezeEvents"):
        add_check(report["checks"], "freeze_events", len(starts) == 0, len(starts), 0)
    if audio and (args.strict or spec.get("forbidSilenceEvents")):
        add_check(report["checks"], "silence_events", len(report["silencedetect"].get("starts", [])) == 0, len(report["silencedetect"].get("starts", [])), 0)

    failures = [c for c in report["checks"] if not c["ok"] and c.get("severity") == "error"]
    report["summary"] = {"ok": not failures, "checks": len(report["checks"]), "failures": len(failures), "failed_checks": [c["name"] for c in failures]}
    out = Path(args.out).resolve() if args.out else media.with_suffix(media.suffix + ".qc.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out)
    return 0 if report["summary"]["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
