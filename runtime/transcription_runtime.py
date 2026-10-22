"""Provision optional local speech dependencies in the job Python environment."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def ensure_transcription_runtime(skill: Path) -> dict:
    """Install faster-whisper only when a transcription backend needs it."""
    if importlib.util.find_spec("faster_whisper") is not None:
        return {"ok": True, "installed": False}
    requirements = skill / "runtime/requirements-ml.txt"
    if not requirements.is_file():
        return {"ok": False, "error": f"missing {requirements}"}
    try:
        run = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--requirement", str(requirements)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800,
        )
    except Exception as exc:
        return {"ok": False, "installed": False, "error": str(exc)}
    return {
        "ok": run.returncode == 0 and importlib.util.find_spec("faster_whisper") is not None,
        "installed": run.returncode == 0,
        "returncode": run.returncode,
        "stdout": run.stdout[-8000:],
        "stderr": run.stderr[-8000:],
    }
