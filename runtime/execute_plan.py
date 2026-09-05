#!/usr/bin/env python3
"""Execute a machine-readable edit plan across Premiere, AE, desktop and QC.

Each action can carry bounded retries, verification actions, and explicit fallbacks.
This lets a job downgrade per operation (e.g. UXP -> UIA) without restarting the
whole orchestration cycle.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from websockets.asyncio.client import connect
from ae_rpc import compile_jsx, dispatch as ae_dispatch
from desktop_driver import run_steps


async def premiere_call(uri, secret, op, args, timeout=90):
    async with connect(uri, max_size=8 * 1024 * 1024) as ws:
        rid = str(uuid.uuid4())
        await ws.send(json.dumps({"id": rid, "secret": secret, "op": op, "args": args, "timeout": timeout}))
        return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout + 5))


class Executor:
    def __init__(self, job: Path, skill: Path, control_uri: str):
        self.job = job
        self.skill = skill
        self.control_uri = control_uri
        self.secret = (job / "runtime/bridge-secret.txt").read_text(encoding="utf-8").strip()
        self.env = json.loads((job / "analysis/environment.json").read_text(encoding="utf-8"))

    def primitive(self, a):
        engine = a["engine"]
        if engine == "premiere":
            return asyncio.run(premiere_call(self.control_uri, self.secret, a["op"], a.get("args", {}), float(a.get("timeout", 90))))

        if engine == "after_effects":
            payload = {"undoGroup": a.get("undoGroup", "Autonomous Editor"), "actions": a.get("actions", [a.get("action")])}
            if not all(payload["actions"]):
                return {"ok": False, "error": "After Effects action missing"}
            tmp = self.job / "temp"; tmp.mkdir(exist_ok=True)
            result = tmp / f"ae-exec-{uuid.uuid4().hex}.json"
            jsx = tmp / f"ae-exec-{uuid.uuid4().hex}.jsx"
            jsx.write_text(compile_jsx(payload, result), encoding="utf-8")
            afterfx = (self.env.get("tools") or {}).get("afterfx")
            if not afterfx:
                return {"ok": False, "error": "After Effects executable unavailable"}
            return ae_dispatch(afterfx, jsx, result, float(a.get("timeout", 120)))

        if engine == "desktop":
            rows = run_steps(a.get("steps", []))
            return {"ok": all(x.get("ok") for x in rows), "results": rows}

        if engine == "analysis":
            out = Path(a.get("out", self.job / "analysis" / (Path(a["media"]).stem + ".analysis.json")))
            cmd = [sys.executable, str(self.skill / "runtime/analyze_media.py"), a["media"], "--out", str(out)]
            if a.get("sceneThreshold") is not None:
                cmd += ["--scene-threshold", str(a["sceneThreshold"])]
            if a.get("minSilence") is not None:
                cmd += ["--min-silence", str(a["minSilence"])]
            p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=float(a.get("timeout", 1200)))
            return {"ok": p.returncode == 0, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr, "analysis": str(out)}

        if engine == "transcribe":
            out_dir = Path(a.get("outDir", self.job / "analysis" / (Path(a["media"]).stem + "-transcript")))
            cmd = [sys.executable, str(self.skill / "runtime/transcribe.py"), a["media"], "--out-dir", str(out_dir), "--model", str(a.get("model", "large-v3"))]
            for flag, key in [("--language", "language"), ("--device", "device"), ("--compute-type", "computeType"), ("--backend", "backend")]:
                if a.get(key) is not None:
                    cmd += [flag, str(a[key])]
            p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=float(a.get("timeout", 7200)))
            return {"ok": p.returncode == 0, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr, "outDir": str(out_dir)}

        if engine == "qc":
            out = Path(a.get("out", self.job / "qc" / (Path(a["media"]).name + ".json")))
            cmd = [sys.executable, str(self.skill / "scripts/qc.py"), a["media"], "--out", str(out)]
            if a.get("spec"):
                cmd += ["--spec", str(a["spec"])]
            if a.get("strict"):
                cmd += ["--strict"]
            p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=float(a.get("timeout", 600)))
            return {"ok": p.returncode == 0, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr, "report": str(out)}

        if engine == "review":
            out_dir = Path(a.get("outDir", self.job / "qc" / (Path(a["media"]).stem + "-review")))
            p = subprocess.run(
                [sys.executable, str(self.skill / "runtime/review_packet.py"), a["media"], "--out-dir", str(out_dir), "--frames", str(int(a.get("frames", 12)))],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=float(a.get("timeout", 600)),
            )
            return {"ok": p.returncode == 0, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr, "packet": str(out_dir / "review-packet.json")}

        if engine == "shell":
            p = subprocess.run(a["argv"], cwd=a.get("cwd"), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=float(a.get("timeout", 300)))
            return {"ok": p.returncode == 0, "returncode": p.returncode, "stdout": p.stdout[-16000:], "stderr": p.stderr[-16000:]}

        raise RuntimeError(f"Unknown engine: {engine}")

    def execute_action(self, a, depth=0):
        if depth > 4:
            return {"ok": False, "error": "fallback nesting limit exceeded", "attempts": []}
        attempts = []
        retries = max(0, int(a.get("retries", 0)))
        result = None
        for attempt in range(retries + 1):
            started = time.time()
            try:
                result = self.primitive(a)
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            attempts.append({"kind": "primary", "attempt": attempt + 1, "elapsed": time.time() - started, "result": result})
            if result.get("ok"):
                break
            if attempt < retries:
                time.sleep(float(a.get("retryDelay", min(5, 0.5 * (2 ** attempt)))))

        # A successful mutation isn't complete until its requested verification passes.
        if result and result.get("ok") and a.get("verify"):
            checks = a["verify"] if isinstance(a["verify"], list) else [a["verify"]]
            verification = []
            for check_action in checks:
                vr = self.execute_action(check_action, depth + 1)
                verification.append(vr)
                if not vr.get("ok"):
                    result = {"ok": False, "error": "verification failed", "primary": result, "verification": verification}
                    break
            if result.get("ok"):
                result = {**result, "verification": verification}

        if result and result.get("ok"):
            return {"ok": True, "selected": "primary", "result": result, "attempts": attempts}

        # Try deterministic per-operation fallbacks in declared order.
        fallback_results = []
        for idx, fallback in enumerate(a.get("fallbacks", [])):
            fr = self.execute_action(fallback, depth + 1)
            fallback_results.append({"index": idx, "action": fallback, "result": fr})
            if fr.get("ok"):
                return {"ok": True, "selected": f"fallback[{idx}]", "result": fr.get("result", fr), "attempts": attempts, "fallbacks": fallback_results}

        return {"ok": False, "selected": None, "result": result or {"ok": False, "error": "no result"}, "attempts": attempts, "fallbacks": fallback_results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--job-root", required=True)
    ap.add_argument("--skill-root", required=True)
    ap.add_argument("--control-uri", default="ws://127.0.0.1:8766")
    ns = ap.parse_args()

    plan = json.loads(Path(ns.plan).read_text(encoding="utf-8"))
    job = Path(ns.job_root).resolve(); skill = Path(ns.skill_root).resolve()
    ex = Executor(job, skill, ns.control_uri)
    results = []

    for i, action in enumerate(plan["actions"]):
        started = time.time()
        r = ex.execute_action(action)
        results.append({"index": i, "engine": action["engine"], "elapsed": time.time() - started, "result": r})
        if not r.get("ok") and not action.get("continueOnError", False):
            break

    out = Path(plan.get("report", job / "logs/execution-report.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ok": all(x["result"].get("ok") for x in results), "results": results}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(0 if payload["ok"] else 2)


if __name__ == "__main__":
    main()
