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


BLACK_RE = re.compile(r"black_start:(-?[0-9.]+) black_end:([0-9.]+) black_duration:([0-9.]+)")
FREEZE_START_RE = re.compile(r"freeze_start: (-?[0-9.]+)")
FREEZE_DURATION_RE = re.compile(r"freeze_duration: (-?[0-9.]+)")
SILENCE_START_RE = re.compile(r"silence_start: (-?[0-9.]+)")
SILENCE_END_RE = re.compile(r"silence_end: (-?[0-9.]+)")
LOUDNESS_I_RE = re.compile(r"I:\s*(-?[0-9.]+) LUFS")
PEAK_RE = re.compile(r"Peak:\s*(-?[0-9.]+) dBFS")


def run(cmd):
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {"code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def parse_black_events(stderr_text):
    return BLACK_RE.findall(stderr_text)


def parse_freeze(stderr_text):
    return FREEZE_START_RE.findall(stderr_text), FREEZE_DURATION_RE.findall(stderr_text)


def parse_silence(stderr_text):
    return SILENCE_START_RE.findall(stderr_text), SILENCE_END_RE.findall(stderr_text)


def parse_loudness(stderr_text):
    lufs_matches = LOUDNESS_I_RE.findall(stderr_text)
    peak_matches = PEAK_RE.findall(stderr_text)
    return (
        float(lufs_matches[-1]) if lufs_matches else None,
        float(peak_matches[-1]) if peak_matches else None,
    )


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
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Could not read delivery spec {path}: {exc}")


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
            expected = fnum(spec["width"])
            add_check(checks, "width", expected is not None and fnum(v.get("width")) == expected, v.get("width"), spec["width"])
        if "height" in spec:
            expected = fnum(spec["height"])
            add_check(checks, "height", expected is not None and fnum(v.get("height")) == expected, v.get("height"), spec["height"])
        if "fps" in spec:
            actual = parse_fps(v)
            target = fnum(spec["fps"])
            tol = fnum(spec.get("fpsTolerance", 0.02)) or 0.02
            add_check(checks, "fps", actual is not None and target is not None and abs(actual - target) <= tol, actual, spec["fps"], detail=f"tolerance={tol}")
        if "videoCodec" in spec:
            add_check(checks, "video_codec", str(v.get("codec_name", "")).lower() == str(spec["videoCodec"]).lower(), v.get("codec_name"), spec["videoCodec"])
        if "pixelFormat" in spec:
            add_check(checks, "pixel_format", v.get("pix_fmt") == spec["pixelFormat"], v.get("pix_fmt"), spec["pixelFormat"])
    if a:
        if "audioCodec" in spec:
            add_check(checks, "audio_codec", str(a.get("codec_name", "")).lower() == str(spec["audioCodec"]).lower(), a.get("codec_name"), spec["audioCodec"])
        if "sampleRate" in spec:
            expected = fnum(spec["sampleRate"])
            add_check(checks, "sample_rate", expected is not None and fnum(a.get("sample_rate") or 0) == expected, a.get("sample_rate"), spec["sampleRate"])
        if "audioChannels" in spec:
            expected = fnum(spec["audioChannels"])
            add_check(checks, "audio_channels", expected is not None and fnum(a.get("channels") or 0) == expected, a.get("channels"), spec["audioChannels"])
    if "duration" in spec and duration is not None:
        target = fnum(spec["duration"])
        tol = fnum(spec.get("durationTolerance", 0.25)) or 0.25
        add_check(checks, "duration", target is not None and abs(duration - target) <= tol, duration, spec["duration"], detail=f"tolerance={tol}s")
    if "minDuration" in spec and duration is not None:
        target = fnum(spec["minDuration"])
        add_check(checks, "min_duration", target is not None and duration >= target, duration, spec["minDuration"])
    if "maxDuration" in spec and duration is not None:
        target = fnum(spec["maxDuration"])
        add_check(checks, "max_duration", target is not None and duration <= target, duration, spec["maxDuration"])
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

    decode = run([ffmpeg, "-v", "error", "-xerror", "-i", str(media), "-f", "null", "-"])
    report["decode"] = {"ok": decode["code"] == 0, "returncode": decode["code"], "errors": decode["stderr"]}
    add_check(report["checks"], "decode_integrity", decode["code"] == 0, decode["code"], 0)

    black = filter_scan(ffmpeg, media, vf="blackdetect=d=0.20:pix_th=0.10")
    ranges = parse_black_events(black["stderr"])
    report["blackdetect"] = {"returncode": black["code"], "events": ranges}

    freeze = filter_scan(ffmpeg, media, vf="freezedetect=n=-50dB:d=2")
    starts, durations = parse_freeze(freeze["stderr"])
    report["freezedetect"] = {"returncode": freeze["code"], "starts": starts, "durations": durations}

    audio = first_stream(probe, "audio")
    if audio:
        silence = filter_scan(ffmpeg, media, af="silencedetect=noise=-45dB:d=1.0")
        sstarts, sends = parse_silence(silence["stderr"])
        report["silencedetect"] = {"returncode": silence["code"], "starts": sstarts, "ends": sends}
        loud = filter_scan(ffmpeg, media, af="ebur128=peak=true")
        lufs, peak = parse_loudness(loud["stderr"][-16000:])
        report["ebur128"] = {"returncode": loud["code"], "integrated_lufs": lufs, "true_peak_dbfs": peak}
        if "targetLufs" in spec and lufs is not None:
            target = fnum(spec["targetLufs"]); tol = fnum(spec.get("lufsTolerance", 1.0)) or 1.0
            add_check(report["checks"], "integrated_loudness", target is not None and abs(lufs-target) <= tol, lufs, spec["targetLufs"], detail=f"tolerance={tol} LU")
        if "maxTruePeakDbfs" in spec and peak is not None:
            target = fnum(spec["maxTruePeakDbfs"])
            add_check(report["checks"], "true_peak", target is not None and peak <= target, peak, f"<= {spec['maxTruePeakDbfs']}")
    else:
        report["silencedetect"] = {"skipped": True, "reason": "no audio stream"}
        report["ebur128"] = {"skipped": True, "reason": "no audio stream"}

    # "forbid" policies require a successful scan: a crashed scan cannot prove absence.
    if args.strict or spec.get("forbidBlackFrames"):
        add_check(report["checks"], "black_events", black["code"] == 0 and len(ranges) == 0, len(ranges), 0,
                  detail=None if black["code"] == 0 else "blackdetect scan failed")
    if args.strict or spec.get("forbidFreezeEvents"):
        add_check(report["checks"], "freeze_events", freeze["code"] == 0 and len(starts) == 0, len(starts), 0,
                  detail=None if freeze["code"] == 0 else "freezedetect scan failed")
    if audio and (args.strict or spec.get("forbidSilenceEvents")):
        silence_starts = report["silencedetect"].get("starts", [])
        add_check(report["checks"], "silence_events", report["silencedetect"].get("returncode") == 0 and len(silence_starts) == 0,
                  len(silence_starts), 0,
                  detail=None if report["silencedetect"].get("returncode") == 0 else "silencedetect scan failed")

    failures = [c for c in report["checks"] if not c["ok"] and c.get("severity") == "error"]
    report["summary"] = {"ok": not failures, "checks": len(report["checks"]), "failures": len(failures), "failed_checks": [c["name"] for c in failures]}
    out = Path(args.out).resolve() if args.out else media.with_suffix(media.suffix + ".qc.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out)
    return 0 if report["summary"]["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
