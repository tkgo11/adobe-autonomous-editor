#!/usr/bin/env python3
"""Executable initializer for Autonomous Adobe Editor.

Creates/resumes a job, inventories media, discovers Adobe/tooling capabilities,
packages/optionally installs the Premiere UXP bridge, starts/probes the local
broker, self-tests After Effects JSX control, and writes capability/init state.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from package_bridge import package as package_bridge


def find_adobe_exe(names):
    hits = []
    if platform.system() == "Windows":
        roots = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Adobe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Adobe",
        ]
        for root in roots:
            if root.exists():
                for name in names:
                    hits.extend(root.rglob(name))
    for name in names:
        path = shutil.which(name)
        if path:
            hits.append(Path(path))
    return str(sorted(hits, key=lambda p: str(p), reverse=True)[0]) if hits else None


def version_of(path):
    if not path:
        return None
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if platform.system() == "Windows" and ps:
        escaped = path.replace("'", "''")
        cmd = f"(Get-Item -LiteralPath '{escaped}').VersionInfo.ProductVersion"
        r = subprocess.run([ps, "-NoProfile", "-Command", cmd], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def ensure_dirs(job):
    for d in [
        "source", "proxies", "analysis", "plans", "projects/premiere", "projects/after-effects",
        "assets", "previews", "renders", "qc", "logs", "recovery/init-history", "temp", "runtime",
    ]:
        (job / d).mkdir(parents=True, exist_ok=True)


def find_upia():
    if platform.system() != "Windows":
        return None
    p = Path(os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files")) / (
        "Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/"
        "UnifiedPluginInstallerAgent.exe"
    )
    return str(p) if p.exists() else None


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def controller_call(secret, op, timeout=4):
    try:
        from websockets.asyncio.client import connect
        async with connect("ws://127.0.0.1:8766", open_timeout=2, close_timeout=1) as ws:
            rid = str(uuid.uuid4())
            await ws.send(json.dumps({"id": rid, "secret": secret, "op": op, "args": {}, "timeout": timeout}))
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout + 2)
            return json.loads(raw)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def start_broker(skill: Path, job: Path, secret_file: Path):
    state = job / "runtime/broker-state.json"
    log_path = job / "logs/broker.log"
    log = log_path.open("a", encoding="utf-8")
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        [sys.executable, str(skill / "runtime/orchestrator.py"), "--secret-file", str(secret_file), "--state", str(state)],
        stdout=log, stderr=log, **kwargs,
    )
    (job / "runtime/broker.pid").write_text(str(proc.pid), encoding="utf-8")
    return proc


def read_source_inventory(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"sources": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-root", required=True)
    ap.add_argument("--skill-root", required=True)
    ap.add_argument("--source", action="append", default=[])
    ap.add_argument("--brief", default="")
    ap.add_argument("--auto", action="store_true", help="install/update bridge if needed, start broker, and launch Premiere")
    ap.add_argument("--install-bridge", action="store_true")
    ap.add_argument("--force-install-bridge", action="store_true")
    ap.add_argument("--start-broker", action="store_true")
    ap.add_argument("--launch-premiere", action="store_true")
    ap.add_argument("--premiere-wait", type=float, default=45.0)
    ns = ap.parse_args()

    if ns.auto:
        ns.install_bridge = True
        ns.start_broker = True
        ns.launch_premiere = True

    job = Path(ns.job_root).resolve()
    skill = Path(ns.skill_root).resolve()
    ensure_dirs(job)
    (job / "plans/user_brief.txt").write_text(ns.brief, encoding="utf-8")

    # One machine-local secret permits the installed bridge to be reused across jobs.
    global_dir = Path.home() / ".adobe-autonomous-editor"
    global_dir.mkdir(parents=True, exist_ok=True)
    global_secret = global_dir / "bridge-secret.txt"
    if not global_secret.exists():
        global_secret.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    secret = global_secret.read_text(encoding="utf-8").strip()
    secret_file = job / "runtime/bridge-secret.txt"
    secret_file.write_text(secret, encoding="utf-8")

    inventory_path = job / "analysis/source_inventory.json"
    inventory_run = {"returncode": 2, "stderr": "no sources supplied"}
    if ns.source:
        inv_cmd = [sys.executable, str(skill / "runtime/source_inventory.py"), *ns.source, "--out", str(inventory_path)]
        p = subprocess.run(inv_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        inventory_run = {"returncode": p.returncode, "stdout": p.stdout[-8000:], "stderr": p.stderr[-8000:]}
    else:
        inventory_path.write_text(json.dumps({"sources": []}, indent=2), encoding="utf-8")

    tools = {
        "python": sys.executable,
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "powershell": shutil.which("powershell") or shutil.which("pwsh"),
        "premiere": find_adobe_exe(["Adobe Premiere Pro.exe"]),
        "afterfx": find_adobe_exe(["AfterFX.exe"]),
        "aerender": find_adobe_exe(["aerender.exe"]),
        "media_encoder": find_adobe_exe(["Adobe Media Encoder.exe"]),
        "upia": find_upia(),
    }
    versions = {k: version_of(v) for k, v in tools.items() if k in {"premiere", "afterfx", "aerender", "media_encoder"}}
    env = {"timestamp": time.time(), "platform": platform.platform(), "machine": platform.machine(), "tools": tools, "versions": versions}
    try:
        import psutil
        env["hardware"] = {
            "cpu_count": psutil.cpu_count(logical=True), "ram_bytes": psutil.virtual_memory().total,
            "disk_free_bytes": shutil.disk_usage(job).free,
        }
    except Exception:
        pass
    (job / "analysis/environment.json").write_text(json.dumps(env, indent=2, ensure_ascii=False), encoding="utf-8")

    _, ccx = package_bridge(skill / "templates/premiere-uxp", job / "runtime", secret)
    package_hash = sha256(ccx)
    marker = global_dir / "premiere-bridge-install.json"
    old_marker = {}
    try:
        old_marker = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        pass
    install = {
        "requested": bool(ns.install_bridge), "attempted": False, "ok": False, "reused_marker": False,
        "ccx": str(ccx), "package_sha256": package_hash, "error": None,
    }
    marker_matches = old_marker.get("package_sha256") == package_hash and old_marker.get("ok") is True
    if ns.install_bridge and marker_matches and not ns.force_install_bridge:
        install.update({"ok": True, "reused_marker": True, "note": "same bridge package was previously installed successfully"})
    elif ns.install_bridge and tools["upia"]:
        install["attempted"] = True
        try:
            r = subprocess.run([tools["upia"], "/install", str(ccx)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            install.update({"ok": r.returncode == 0, "returncode": r.returncode, "stdout": r.stdout[-8000:], "stderr": r.stderr[-8000:]})
            if install["ok"]:
                marker.write_text(json.dumps({"ok": True, "package_sha256": package_hash, "installed_at": time.time(), "ccx": str(ccx)}, indent=2), encoding="utf-8")
        except Exception as exc:
            install["error"] = str(exc)
    elif ns.install_bridge:
        install["error"] = "UPIA not found; bridge remains packaged for GUI/enterprise installation"

    broker = {"requested": bool(ns.start_broker), "started": False, "broker_reachable": False, "premiere_connected": False}
    existing = asyncio.run(controller_call(secret, "broker.status", 3))
    if existing.get("ok"):
        broker.update({"broker_reachable": True, "reused": True, "status": existing.get("result")})
    elif ns.start_broker:
        try:
            proc = start_broker(skill, job, secret_file)
            broker.update({"started": True, "pid": proc.pid, "state": str(job / "runtime/broker-state.json")})
            time.sleep(0.8)
            status = asyncio.run(controller_call(secret, "broker.status", 3))
            broker.update({"broker_reachable": bool(status.get("ok")), "status": status.get("result"), "broker_probe": status})
        except Exception as exc:
            broker["start_error"] = str(exc)

    ping = asyncio.run(controller_call(secret, "ping", 4)) if broker.get("broker_reachable") else {"ok": False, "error": "broker unavailable"}
    broker["premiere_connected"] = bool(ping.get("ok"))
    broker["rpc_probe"] = ping

    if ns.launch_premiere and tools["premiere"] and broker.get("broker_reachable") and not broker.get("premiere_connected"):
        try:
            subprocess.Popen([tools["premiere"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            broker["premiere_launch_attempted"] = True
            deadline = time.time() + max(1, ns.premiere_wait)
            while time.time() < deadline:
                ping = asyncio.run(controller_call(secret, "ping", 4))
                if ping.get("ok"):
                    broker["premiere_connected"] = True
                    broker["rpc_probe"] = ping
                    break
                time.sleep(1.0)
        except Exception as exc:
            broker["premiere_launch_error"] = str(exc)

    if broker.get("premiere_connected"):
        broker["host_info"] = asyncio.run(controller_call(secret, "hostInfo", 5))
        broker["api_capabilities"] = asyncio.run(controller_call(secret, "capabilities", 5))

    uia = {"available": False}
    if platform.system() == "Windows":
        try:
            import pywinauto, pyautogui  # noqa: F401
            uia = {"available": True, "pywinauto": getattr(pywinauto, "__version__", None)}
        except Exception as exc:
            uia = {"available": False, "error": str(exc)}

    ae_probe = {"available": bool(tools["afterfx"]), "script_rpc": False}
    if tools["afterfx"]:
        plan = job / "temp/ae-selftest.json"
        res = job / "temp/ae-selftest-result.json"
        plan.write_text(json.dumps({"actions": [{"op": "newProject"}, {"op": "createComp", "name": "__AutonomousEditorSelfTest__", "width": 64, "height": 64, "duration": 1, "fps": 24}]}), encoding="utf-8")
        try:
            r = subprocess.run(
                [sys.executable, str(skill / "runtime/ae_rpc.py"), str(plan), "--afterfx", tools["afterfx"], "--result", str(res), "--timeout", "30"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40,
            )
            ae_probe.update({"script_rpc": r.returncode == 0, "returncode": r.returncode, "stdout": r.stdout[-4000:], "stderr": r.stderr[-4000:]})
        except Exception as exc:
            ae_probe["error"] = str(exc)

    capabilities = {
        "premiere": {
            "installed": bool(tools["premiere"]), "version": versions.get("premiere"),
            "uxp_bridge_packaged": True, "uxp_install": install, "broker": broker,
            "uxp_rpc": bool(broker.get("premiere_connected")), "uia_fallback": uia["available"],
        },
        "after_effects": {
            "installed": bool(tools["afterfx"]), "version": versions.get("afterfx"),
            "jsx_rpc": ae_probe, "aerender": bool(tools["aerender"]), "uia_fallback": uia["available"],
        },
        "media": {"ffmpeg": bool(tools["ffmpeg"]), "ffprobe": bool(tools["ffprobe"])},
        "desktop": uia,
    }
    (job / "plans/capability_matrix.json").write_text(json.dumps(capabilities, indent=2, ensure_ascii=False), encoding="utf-8")

    inventory = read_source_inventory(inventory_path)
    existing_sources = [s for s in inventory.get("sources", []) if s.get("exists")]
    sources_ok = inventory_run.get("returncode") == 0 and bool(existing_sources)
    adobe_any = bool(tools["premiere"] or tools["afterfx"])
    premiere_control = not tools["premiere"] or bool(broker.get("premiere_connected")) or uia["available"]
    ae_control = not tools["afterfx"] or bool(ae_probe.get("script_rpc")) or uia["available"]
    media_qc = bool(tools["ffmpeg"] and tools["ffprobe"])

    if not sources_ok or not adobe_any:
        status = "BLOCKED"
    elif premiere_control and ae_control and media_qc and (not tools["premiere"] or broker.get("premiere_connected")) and (not tools["afterfx"] or ae_probe.get("script_rpc")):
        status = "READY"
    else:
        status = "DEGRADED"

    notes = []
    if tools["premiere"] and not broker.get("premiere_connected"):
        notes.append("Premiere explicit UXP RPC is not yet confirmed. Use bridge install/reload/restart recovery, then UIA/vision fallback if necessary.")
    if tools["afterfx"] and not ae_probe.get("script_rpc"):
        notes.append("After Effects JSX RPC self-test is not confirmed. Reinitialize the AE surface or use UIA/vision fallback.")
    if not media_qc:
        notes.append("ffmpeg/ffprobe deterministic QC is unavailable until installed; Adobe editing can continue but delivery verification is degraded.")
    if install.get("reused_marker") and not broker.get("premiere_connected"):
        notes.append("A prior bridge-install marker exists but the current host did not connect; do not trust the marker alone—perform targeted bridge recovery.")

    init = {
        "status": status, "timestamp": time.time(), "job_root": str(job), "source_inventory_ok": sources_ok,
        "source_files_found": len(existing_sources), "capability_matrix": str(job / "plans/capability_matrix.json"),
        "bridge_secret_file": str(secret_file), "notes": notes,
    }
    (job / "plans/init_state.json").write_text(json.dumps(init, indent=2, ensure_ascii=False), encoding="utf-8")
    history = job / "recovery/init-history" / f"init-{int(time.time())}.json"
    history.write_text(json.dumps({"init": init, "capabilities": capabilities}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(init, indent=2, ensure_ascii=False))
    raise SystemExit(0 if status != "BLOCKED" else 2)


if __name__ == "__main__":
    main()
