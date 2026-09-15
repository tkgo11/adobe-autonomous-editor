#!/usr/bin/env python3
"""Shared helpers for launching and inspecting the loopback orchestrator."""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def start_broker(skill: Path, job: Path, secret_file: Path | None = None) -> subprocess.Popen:
    secret_file = secret_file or (job / "runtime/bridge-secret.txt")
    state = job / "runtime/broker-state.json"
    log_path = job / "logs/broker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", encoding="utf-8")
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        [sys.executable, str(skill / "runtime/orchestrator.py"), "--secret-file", str(secret_file), "--state", str(state)],
        stdout=log,
        stderr=log,
        **kwargs,
    )
    log.close()
    (job / "runtime/broker.pid").write_text(str(proc.pid), encoding="utf-8")
    return proc
