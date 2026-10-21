#!/usr/bin/env python3
"""Create an isolated runtime, install its dependencies, then initialize a job.

This file intentionally uses only the Python standard library.  It is the
supported Python entry point on a machine that has the skill but none of its
Python packages yet.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(command, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}")
    return result


def _venv_ready(python: Path) -> bool:
    """A partial venv can contain Python before pip is available."""
    if not python.is_file():
        return False
    # sys.prefix differs from sys.base_prefix even when the venv was created
    # with --system-site-packages. Require an explicit isolated configuration.
    venv_root = python.parents[1]
    try:
        config = (venv_root / "pyvenv.cfg").read_text(encoding="utf-8")
    except OSError:
        return False
    include_system = re.search(r"^\s*include-system-site-packages\s*=\s*(true|false)\s*$", config, re.I | re.M)
    if not include_system or include_system.group(1).lower() != "false":
        return False
    try:
        interpreter = subprocess.run(
            [str(python), "-c", "import sys; assert sys.prefix != sys.base_prefix"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
        if interpreter.returncode:
            return False
        pip = subprocess.run(
            [str(python), "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
        return pip.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def prepare_runtime(job: Path, skill: Path) -> tuple[Path, dict]:
    requirements = skill / "runtime/requirements.txt"
    if not requirements.is_file():
        raise RuntimeError(f"Missing runtime requirements: {requirements}")

    runtime_dir = job / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    venv = runtime_dir / "venv"
    python = _venv_python(venv)
    rebuilt = False
    if not _venv_ready(python):
        command = [sys.executable, "-m", "venv"]
        if venv.exists():
            command.append("--clear")
        _run([*command, str(venv)])
        rebuilt = True
    if not _venv_ready(python):
        raise RuntimeError(f"Virtual environment did not provide a pip-enabled Python: {python}")

    state_path = runtime_dir / "bootstrap-state.json"
    wanted = _digest(requirements)
    prior = {}
    try:
        prior = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    install_needed = rebuilt or prior.get("requirements_sha256") != wanted
    if not install_needed:
        probe = subprocess.run(
            [str(python), "-c", "import websockets,jsonschema,psutil"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        install_needed = probe.returncode != 0
    if install_needed:
        _run([
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--requirement", str(requirements),
        ])

    state = {
        "schema_version": 1,
        "python": str(python.absolute()),
        "base_python": sys.executable,
        "requirements": str(requirements.resolve()),
        "requirements_sha256": wanted,
        "installed_at": time.time(),
        "isolated": True,
    }
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return python, state


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision the job-local runtime and run initialize.py",
        add_help=False,
    )
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--skill-root", required=True)
    ns, _ = parser.parse_known_args()
    job = Path(ns.job_root).expanduser().resolve()
    skill = Path(ns.skill_root).expanduser().resolve()
    python, _ = prepare_runtime(job, skill)
    env = os.environ.copy()
    env["AAE_BOOTSTRAPPED"] = "1"
    command = [str(python), str(skill / "runtime/initialize.py"), *sys.argv[1:]]
    raise SystemExit(subprocess.call(command, env=env))


if __name__ == "__main__":
    main()
