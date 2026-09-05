#!/usr/bin/env python3
"""Local speech-to-text for autonomous editing.

Preferred backend is faster-whisper. Output includes timestamped JSON, SRT and VTT.
No cloud upload is performed by this runtime.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def stamp(seconds: float, srt=True):
    ms = max(0, round(float(seconds) * 1000))
    h, rem = divmod(ms, 3600000); m, rem = divmod(rem, 60000); sec, milli = divmod(rem, 1000)
    sep = "," if srt else "."
    return f"{h:02d}:{m:02d}:{sec:02d}{sep}{milli:03d}"


def write_subs(segments, srt_path: Path, vtt_path: Path):
    srt = []
    vtt = ["WEBVTT", ""]
    for i, seg in enumerate(segments, 1):
        text = str(seg.get("text", "")).strip()
        srt += [str(i), f"{stamp(seg['start'])} --> {stamp(seg['end'])}", text, ""]
        vtt += [f"{stamp(seg['start'], False)} --> {stamp(seg['end'], False)}", text, ""]
    srt_path.write_text("\n".join(srt), encoding="utf-8")
    vtt_path.write_text("\n".join(vtt), encoding="utf-8")


def faster_whisper(media, model, device, compute_type, language):
    from faster_whisper import WhisperModel
    wm = WhisperModel(model, device=device, compute_type=compute_type)
    iterator, info = wm.transcribe(str(media), language=language or None, vad_filter=True, word_timestamps=True, beam_size=5)
    segments = []
    for seg in iterator:
        words = []
        for w in (seg.words or []):
            words.append({"start": w.start, "end": w.end, "word": w.word, "probability": getattr(w, "probability", None)})
        segments.append({"start": seg.start, "end": seg.end, "text": seg.text.strip(), "words": words})
    return {"backend": "faster-whisper", "language": info.language, "language_probability": info.language_probability, "segments": segments}


def whisper_cli(media, model, language):
    exe = shutil.which("whisper")
    if not exe:
        raise RuntimeError("whisper CLI not found")
    with tempfile.TemporaryDirectory() as td:
        cmd = [exe, str(media), "--model", model, "--output_dir", td, "--output_format", "json", "--word_timestamps", "True"]
        if language:
            cmd += ["--language", language]
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode:
            raise RuntimeError(p.stderr[-8000:])
        files = list(Path(td).glob("*.json"))
        if not files:
            raise RuntimeError("whisper CLI produced no JSON")
        raw = json.loads(files[0].read_text(encoding="utf-8"))
        return {"backend": "whisper-cli", "language": raw.get("language"), "segments": raw.get("segments", [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--language", default=None)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--compute-type", default="default")
    ap.add_argument("--backend", choices=["auto", "faster-whisper", "whisper-cli"], default="auto")
    ns = ap.parse_args()
    media = Path(ns.media).resolve(); out = Path(ns.out_dir).resolve(); out.mkdir(parents=True, exist_ok=True)

    errors = []
    data = None
    if ns.backend in {"auto", "faster-whisper"}:
        try:
            data = faster_whisper(media, ns.model, ns.device, ns.compute_type, ns.language)
        except Exception as exc:
            errors.append(f"faster-whisper: {exc}")
            if ns.backend == "faster-whisper":
                raise
    if data is None and ns.backend in {"auto", "whisper-cli"}:
        try:
            data = whisper_cli(media, ns.model, ns.language)
        except Exception as exc:
            errors.append(f"whisper-cli: {exc}")
            if ns.backend == "whisper-cli":
                raise
    if data is None:
        raise SystemExit("No local STT backend available. " + " | ".join(errors))

    data.update({"media": str(media), "model": ns.model, "errors_before_success": errors})
    json_path = out / "transcript.json"; srt_path = out / "transcript.srt"; vtt_path = out / "transcript.vtt"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    write_subs(data["segments"], srt_path, vtt_path)
    print(json.dumps({"ok": True, "json": str(json_path), "srt": str(srt_path), "vtt": str(vtt_path), "backend": data["backend"], "language": data.get("language")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
