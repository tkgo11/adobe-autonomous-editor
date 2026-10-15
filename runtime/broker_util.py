#!/usr/bin/env python3
"""Shared helpers for launching and inspecting the loopback orchestrator."""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def broker_command(skill: Path, secret_file: Path, state: Path, control_uri: str | None = None) -> list[str]:
    command = [sys.executable, str(skill / "runtime/orchestrator.py"), "--secret-file", str(secret_file), "--state", str(state)]
    if control_uri:
        parsed = urlparse(control_uri)
        if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.port:
            raise ValueError(f"control URI must be a loopback ws:// URI with an explicit port: {control_uri}")
        command.extend(["--host", "127.0.0.1", "--control-port", str(parsed.port)])
    return command


def start_broker(
    skill: Path,
    job: Path,
    secret_file: Path | None = None,
    control_uri: str | None = None,
) -> subprocess.Popen:
    secret_file = secret_file or (job / "runtime/bridge-secret.txt")
    state = job / "runtime/broker-state.json"
    log_path = job / "logs/broker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", encoding="utf-8")
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        broker_command(skill, secret_file, state, control_uri),
        stdout=log,
        stderr=log,
        **kwargs,
    )
    log.close()
    (job / "runtime/broker.pid").write_text(str(proc.pid), encoding="utf-8")
    return proc
