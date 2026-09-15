#!/usr/bin/env python3
"""Local resilience supervisor for the Autonomous Adobe Editor runtime.

It keeps the loopback broker alive, probes the Premiere bridge, optionally launches
Premiere when the bridge is absent, and records bounded recovery attempts. It does
not bypass UAC, Adobe authentication, licensing, or other security prompts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from broker_util import read_json, start_broker
from rpc_client import call


def append_event(path: Path, event: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def launch_premiere(exe: str | None):
    if not exe or not Path(exe).exists():
        return False, "Premiere executable unavailable"
    try:
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, None
    except Exception as exc:
        return False, str(exc)


async def probe(uri: str, secret: str):
    try:
        return await call(uri, secret, "broker.status", {}, 3)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def premiere_ping(uri: str, secret: str):
    try:
        return await call(uri, secret, "ping", {}, 4)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-root", required=True)
    ap.add_argument("--skill-root", required=True)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--max-restarts", type=int, default=3)
    ap.add_argument("--max-premiere-launches", type=int, default=2)
    ap.add_argument("--duration", type=float, default=0, help="0 = run until interrupted")
    ap.add_argument("--control-uri", default="ws://127.0.0.1:8766")
    ns = ap.parse_args()

    job = Path(ns.job_root).resolve()
    skill = Path(ns.skill_root).resolve()
    try:
        secret = (job / "runtime/bridge-secret.txt").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SystemExit(f"Cannot read bridge secret (run initialize first): {exc}")
    env = read_json(job / "analysis/environment.json", {})
    premiere = (env.get("tools") or {}).get("premiere")
    events = job / "logs/supervisor-events.jsonl"
    state_path = job / "runtime/supervisor-state.json"

    broker_restarts = 0
    premiere_launches = 0
    started = time.time()
    last_launch = 0.0
    last_event_sig = None

    def emit(event):
        # Repeating an identical terminal/warning event every tick would grow the
        # events file without bound; log transitions and retries, not steady state.
        nonlocal last_event_sig
        sig = (event.get("event"), event.get("error"), event.get("attempt"))
        if sig == last_event_sig:
            return
        append_event(events, event)
        last_event_sig = sig

    while True:
        now = time.time()
        if ns.duration > 0 and now - started >= ns.duration:
            break

        broker = asyncio.run(probe(ns.control_uri, secret))
        broker_ok = bool(broker.get("ok"))
        if not broker_ok:
            if broker_restarts < ns.max_restarts:
                proc = start_broker(skill, job)
                broker_restarts += 1
                emit({"ts": now, "event": "broker_restart", "pid": proc.pid, "attempt": broker_restarts})
                time.sleep(min(1.5, ns.interval))
                broker = asyncio.run(probe(ns.control_uri, secret))
                broker_ok = bool(broker.get("ok"))
            else:
                emit({"ts": now, "event": "broker_restart_limit", "error": broker.get("error")})

        ping = asyncio.run(premiere_ping(ns.control_uri, secret)) if broker_ok else {"ok": False, "error": "broker unavailable"}
        premiere_ok = bool(ping.get("ok"))
        # Bound app launches and avoid relaunch storms while Premiere is starting.
        if broker_ok and not premiere_ok and premiere_launches < ns.max_premiere_launches and now - last_launch >= 30:
            ok, err = launch_premiere(premiere)
            premiere_launches += 1
            last_launch = now
            if ok:
                emit({"ts": now, "event": "premiere_launch", "attempt": premiere_launches})
            else:
                emit({"ts": now, "event": "premiere_launch_failed", "attempt": premiere_launches, "error": err})
        elif broker_ok and not premiere_ok and premiere_launches >= ns.max_premiere_launches:
            emit({"ts": now, "event": "premiere_launch_limit", "error": ping.get("error")})

        state = {
            "timestamp": now,
            "broker_ok": broker_ok,
            "premiere_rpc_ok": premiere_ok,
            "broker_restarts": broker_restarts,
            "premiere_launches": premiere_launches,
            "last_broker": broker,
            "last_premiere_ping": ping,
        }
        tmp = state_path.with_name(state_path.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, state_path)
        time.sleep(max(1.0, ns.interval))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
