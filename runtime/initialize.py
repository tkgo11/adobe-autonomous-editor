#!/usr/bin/env python3
"""Executable initializer for the autonomous video editor.

Creates/resumes a job, inventories media, installs/probes the video-related
Crafting Apps CLIs when requested, discovers Adobe fallback capabilities,
and writes capability/init state.
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

from broker_util import read_json, start_broker
from crafting_apps import APPS as CRAFTING_APPS
from crafting_apps import discover as discover_crafting_app
from crafting_apps import install_video_clis, probe as probe_crafting_app
from package_bridge import package as package_bridge
from platform_support import desktop_probe, find_adobe_tool, find_upia, launch_application, product_version, upia_install_command
from toolchain import ensure_media_tools, probe_system_media_tools


def ensure_dirs(job):
    for d in [
        "source", "proxies", "analysis", "plans", "projects/filmcraft", "projects/effectcraft",
        "projects/premiere", "projects/after-effects",
        "assets", "previews", "renders", "qc", "logs", "recovery/init-history", "temp", "runtime",
    ]:
        (job / d).mkdir(parents=True, exist_ok=True)


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def controller_call(secret, op, timeout=4, uri="ws://127.0.0.1:8766"):
    try:
        from rpc_client import call as ws_call
        return await ws_call(uri, secret, op, {}, timeout, open_timeout=2, close_timeout=1)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def read_source_inventory(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"sources": []}


def should_prepare_adobe(editor_priority: str, auto: bool) -> bool:
    return bool(auto and editor_priority == "adobe-only")


def safe_ae_probe_plan() -> dict:
    return {"actions": []}


def preferred_editors(editor_priority: str, crafting: dict, tools: dict) -> list[str]:
    editors = []
    if editor_priority == "crafting-first":
        editors.extend(app for app in ("filmcraft", "effectcraft") if crafting[app].get("available"))
    if tools.get("premiere"):
        editors.append("premiere")
    if tools.get("afterfx"):
        editors.append("after_effects")
    return editors


def routing_rule(editor_priority: str) -> str:
    if editor_priority == "adobe-only":
        return "Use only installed Adobe Premiere Pro or After Effects capabilities; do not create FilmCraft or EffectCraft actions."
    return "Use the matching Crafting App CLI first; use Adobe only when the required feature is unavailable or a verified Crafting Apps attempt fails."


def verified_media_path(media_tools: dict, name: str) -> str | None:
    return media_tools.get(name) if media_tools.get("ok") else None


def initialization_status(
    editor_priority: str,
    sources_ok: bool,
    crafting_any: bool,
    crafting_ready: bool,
    adobe_any: bool,
    premiere_control: bool,
    ae_control: bool,
    media_qc: bool,
    premiere_installed: bool,
    premiere_rpc: bool,
    afterfx_installed: bool,
    afterfx_rpc: bool,
) -> str:
    if not sources_ok:
        return "BLOCKED"
    if editor_priority == "adobe-only" and not adobe_any:
        return "BLOCKED"
    if editor_priority == "crafting-first" and not (crafting_any or adobe_any):
        return "BLOCKED"
    if editor_priority == "crafting-first" and crafting_ready and media_qc:
        return "READY"
    if (
        editor_priority == "adobe-only" and adobe_any and premiere_control and ae_control and media_qc
        and (not premiere_installed or premiere_rpc)
        and (not afterfx_installed or afterfx_rpc)
    ):
        return "READY"
    return "DEGRADED"


def machine_state_dir(explicit_dir, job: Path):
    """Return a writable directory for state shared by jobs on this machine.

    Desktop installs normally use the user's home directory.  Some managed
    runners expose that directory as read-only, so fall back to the parent of
    the job root instead of failing before the initializer can report its
    capability state.  An explicit directory is never silently replaced.
    """
    if explicit_dir:
        candidates = [Path(explicit_dir).expanduser()]
    else:
        candidates = [
            Path.home() / ".adobe-autonomous-editor",
            job.parent / ".adobe-autonomous-editor",
        ]

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        if os.access(candidate, os.R_OK | os.W_OK | os.X_OK):
            return candidate.resolve()

    if explicit_dir:
        raise RuntimeError(f"State directory is not usable: {explicit_dir}")
    raise RuntimeError("Could not create a writable machine state directory")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-root", required=True)
    ap.add_argument("--skill-root", required=True)
    ap.add_argument("--source", action="append", default=[])
    ap.add_argument("--brief", default="")
    ap.add_argument("--auto", action="store_true", help="install/probe Crafting Apps first and activate Adobe only if no Crafting App is usable")
    ap.add_argument("--editor-priority", choices=["crafting-first", "adobe-only"], default="crafting-first")
    ap.add_argument("--install-crafting-apps", action="store_true", help="install missing FilmCraft/EffectCraft official CLI releases")
    ap.add_argument("--force-install-crafting-apps", action="store_true", help="redownload and reinstall FilmCraft/EffectCraft CLIs")
    ap.add_argument("--install-media-tools", action="store_true", help="install missing ffmpeg/ffprobe into machine-local state")
    ap.add_argument("--install-bridge", action="store_true")
    ap.add_argument("--force-install-bridge", action="store_true")
    ap.add_argument("--start-broker", action="store_true")
    ap.add_argument("--launch-premiere", action="store_true")
    ap.add_argument("--premiere-wait", type=float, default=45.0)
    ap.add_argument("--control-uri", default="ws://127.0.0.1:8766", help="controller WebSocket URI of the local broker")
    ap.add_argument("--state-dir", help="writable directory for machine-local bridge state")
    ns = ap.parse_args()

    if ns.auto:
        ns.install_crafting_apps = ns.editor_priority == "crafting-first"
        ns.install_media_tools = True

    job = Path(ns.job_root).resolve()
    skill = Path(ns.skill_root).resolve()
    ensure_dirs(job)
    (job / "plans/user_brief.txt").write_text(ns.brief, encoding="utf-8")

    # One machine-local secret permits the installed bridge to be reused across jobs.
    global_dir = machine_state_dir(ns.state_dir, job)
    global_secret = global_dir / "bridge-secret.txt"
    if not global_secret.exists() or not global_secret.read_text(encoding="utf-8", errors="replace").strip():
        global_secret.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    for p in (global_dir, global_secret):
        try:
            os.chmod(p, 0o700 if p.is_dir() else 0o600)
        except OSError:
            pass
    secret = global_secret.read_text(encoding="utf-8").strip()
    secret_file = job / "runtime/bridge-secret.txt"
    secret_file.write_text(secret, encoding="utf-8")
    try:
        os.chmod(secret_file, 0o600)
    except OSError:
        pass

    media_tools = ensure_media_tools(global_dir) if ns.install_media_tools else probe_system_media_tools()

    inventory_path = job / "analysis/source_inventory.json"
    inventory_run = {"returncode": 2, "stderr": "no sources supplied"}
    if ns.source:
        inv_cmd = [sys.executable, str(skill / "runtime/source_inventory.py"), *ns.source, "--out", str(inventory_path)]
        p = subprocess.run(inv_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        inventory_run = {"returncode": p.returncode, "stdout": p.stdout[-8000:], "stderr": p.stderr[-8000:]}
    else:
        inventory_path.write_text(json.dumps({"sources": []}, indent=2), encoding="utf-8")

    crafting_install = {
        "requested": bool(ns.install_crafting_apps or ns.force_install_crafting_apps),
        "ok": False,
        "apps": {},
    }
    if ns.editor_priority == "crafting-first" and crafting_install["requested"]:
        crafting_install = install_video_clis(global_dir, force=ns.force_install_crafting_apps)
        crafting_install["requested"] = True
    crafting = {}
    for app in CRAFTING_APPS:
        path = discover_crafting_app(app, global_dir)
        crafting[app] = probe_crafting_app(app, path)
    crafting_ready = all(crafting[app].get("available") for app in CRAFTING_APPS)
    crafting_any = any(crafting[app].get("available") for app in CRAFTING_APPS)
    # Crafting-first initialization records missing roles but does not start an
    # Adobe application preemptively. The selected operation activates its own
    # Adobe fallback only after the matching Crafting capability is required.
    adobe_required = ns.editor_priority == "adobe-only"
    auto_needs_adobe = should_prepare_adobe(ns.editor_priority, ns.auto)
    if auto_needs_adobe:
        ns.install_bridge = True
        ns.start_broker = True

    tools = {
        "python": sys.executable,
        "ffmpeg": verified_media_path(media_tools, "ffmpeg"),
        "ffprobe": verified_media_path(media_tools, "ffprobe"),
        "powershell": shutil.which("powershell") or shutil.which("pwsh"),
        "premiere": find_adobe_tool("premiere"),
        "afterfx": find_adobe_tool("afterfx"),
        "aerender": find_adobe_tool("aerender"),
        "media_encoder": find_adobe_tool("media_encoder"),
        "upia": find_upia(),
        "filmcraft_cli": crafting["filmcraft"].get("path"),
        "effectcraft_cli": crafting["effectcraft"].get("path"),
    }
    versions = {k: product_version(v) for k, v in tools.items() if k in {"premiere", "afterfx", "aerender", "media_encoder"}}
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
            r = subprocess.run(upia_install_command(tools["upia"], ccx), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            install.update({"ok": r.returncode == 0, "returncode": r.returncode, "stdout": r.stdout[-8000:], "stderr": r.stderr[-8000:]})
            if install["ok"]:
                marker.write_text(json.dumps({"ok": True, "package_sha256": package_hash, "installed_at": time.time(), "ccx": str(ccx)}, indent=2), encoding="utf-8")
        except Exception as exc:
            install["error"] = str(exc)
    elif ns.install_bridge:
        install["error"] = "UPIA not found; bridge remains packaged for GUI/enterprise installation"

    broker = {"requested": bool(ns.start_broker), "started": False, "broker_reachable": False, "premiere_connected": False, "control_uri": ns.control_uri}
    existing = asyncio.run(controller_call(secret, "broker.status", 3, ns.control_uri))
    if existing.get("ok"):
        broker.update({"broker_reachable": True, "reused": True, "status": existing.get("result")})
    elif ns.start_broker:
        try:
            proc = start_broker(skill, job, secret_file, ns.control_uri)
            broker.update({"started": True, "pid": proc.pid, "state": str(job / "runtime/broker-state.json")})
            time.sleep(0.8)
            status = asyncio.run(controller_call(secret, "broker.status", 3, ns.control_uri))
            broker.update({"broker_reachable": bool(status.get("ok")), "status": status.get("result"), "broker_probe": status})
        except Exception as exc:
            broker["start_error"] = str(exc)

    ping = asyncio.run(controller_call(secret, "ping", 4, ns.control_uri)) if broker.get("broker_reachable") else {"ok": False, "error": "broker unavailable"}
    broker["premiere_connected"] = bool(ping.get("ok"))
    broker["rpc_probe"] = ping

    if (ns.launch_premiere or auto_needs_adobe) and tools["premiere"] and broker.get("broker_reachable") and not broker.get("premiere_connected"):
        try:
            launch_application(tools["premiere"])
            broker["premiere_launch_attempted"] = True
            deadline = time.time() + max(1, ns.premiere_wait)
            while time.time() < deadline:
                ping = asyncio.run(controller_call(secret, "ping", 4, ns.control_uri))
                if ping.get("ok"):
                    broker["premiere_connected"] = True
                    broker["rpc_probe"] = ping
                    break
                time.sleep(1.0)
        except Exception as exc:
            broker["premiere_launch_error"] = str(exc)

    if broker.get("premiere_connected"):
        broker["host_info"] = asyncio.run(controller_call(secret, "hostInfo", 5, ns.control_uri))
        broker["api_capabilities"] = asyncio.run(controller_call(secret, "capabilities", 5, ns.control_uri))

    desktop = desktop_probe()
    desktop_available = bool(desktop.get("available"))
    desktop_backend = desktop.get("backend")

    ae_probe = {"available": bool(tools["afterfx"]), "script_rpc": False}
    if tools["afterfx"] and not adobe_required:
        ae_probe.update({"skipped": True, "reason": "Crafting Apps are healthy; probe Adobe only on targeted fallback refresh"})
    if tools["afterfx"] and adobe_required:
        plan = job / "temp/ae-selftest.json"
        res = job / "temp/ae-selftest-result.json"
        # An empty action list still exercises AfterFX -r and the result-file
        # round trip without opening, closing, saving, or mutating a project.
        plan.write_text(json.dumps(safe_ae_probe_plan()), encoding="utf-8")
        try:
            r = subprocess.run(
                [sys.executable, str(skill / "runtime/ae_rpc.py"), str(plan), "--afterfx", tools["afterfx"], "--result", str(res), "--timeout", "30"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40,
            )
            ae_probe.update({"script_rpc": r.returncode == 0, "returncode": r.returncode, "stdout": r.stdout[-4000:], "stderr": r.stderr[-4000:]})
        except Exception as exc:
            ae_probe["error"] = str(exc)

    capabilities = {
        "routing": {
            "policy": ns.editor_priority,
            "priority_order": ["filmcraft", "effectcraft", "premiere", "after_effects"] if ns.editor_priority == "crafting-first" else ["premiere", "after_effects"],
            "rule": routing_rule(ns.editor_priority),
        },
        "crafting_apps": {
            "scope": ["filmcraft", "effectcraft"],
            "install": crafting_install,
            **crafting,
        },
        "premiere": {
            "installed": bool(tools["premiere"]), "version": versions.get("premiere"),
            "uxp_bridge_packaged": True, "uxp_install": install, "broker": broker,
            "uxp_rpc": bool(broker.get("premiere_connected")),
            "desktop_fallback": desktop_available,
            "uia_fallback": desktop_available and desktop_backend == "windows-uia",
        },
        "after_effects": {
            "installed": bool(tools["afterfx"]), "version": versions.get("afterfx"),
            "jsx_rpc": ae_probe, "aerender": bool(tools["aerender"]),
            "desktop_fallback": desktop_available,
            "uia_fallback": desktop_available and desktop_backend == "windows-uia",
        },
        "media": {"ffmpeg": bool(tools["ffmpeg"]), "ffprobe": bool(tools["ffprobe"]), "bootstrap": media_tools},
        "desktop": desktop,
    }
    (job / "plans/capability_matrix.json").write_text(json.dumps(capabilities, indent=2, ensure_ascii=False), encoding="utf-8")

    inventory = read_source_inventory(inventory_path)
    existing_sources = [s for s in inventory.get("sources", []) if s.get("exists")]
    sources_ok = inventory_run.get("returncode") == 0 and bool(existing_sources)
    adobe_any = bool(tools["premiere"] or tools["afterfx"])
    premiere_control = not tools["premiere"] or bool(broker.get("premiere_connected")) or desktop_available
    ae_control = not tools["afterfx"] or bool(ae_probe.get("script_rpc")) or desktop_available
    media_qc = bool(tools["ffmpeg"] and tools["ffprobe"])

    status = initialization_status(
        ns.editor_priority, sources_ok, crafting_any, crafting_ready, adobe_any,
        premiere_control, ae_control, media_qc, bool(tools["premiere"]),
        bool(broker.get("premiere_connected")), bool(tools["afterfx"]),
        bool(ae_probe.get("script_rpc")),
    )

    notes = []
    if ns.editor_priority == "crafting-first":
        for app in CRAFTING_APPS:
            if not crafting[app].get("available"):
                notes.append(f"{CRAFTING_APPS[app]['cli']} is unavailable; activate and test the matching Adobe fallback only if the job requires that capability.")
    if adobe_required and tools["premiere"] and not broker.get("premiere_connected"):
        notes.append("Premiere explicit UXP RPC is not yet confirmed. Use bridge install/reload/restart recovery, then the platform desktop-accessibility/vision fallback if necessary.")
    if adobe_required and tools["afterfx"] and not ae_probe.get("script_rpc"):
        notes.append("After Effects JSX RPC self-test is not confirmed. Reinitialize the AE surface or use the platform desktop-accessibility/vision fallback.")
    if not media_qc:
        detail = media_tools.get("error")
        notes.append(
            "ffmpeg/ffprobe automatic provisioning failed"
            + (f": {detail}" if detail else "")
            + "; editing can continue but delivery verification is degraded."
        )
    if install.get("reused_marker") and not broker.get("premiere_connected"):
        notes.append("A prior bridge-install marker exists but the current host did not connect; do not trust the marker alone—perform targeted bridge recovery.")

    degraded_capabilities = []
    if ns.editor_priority == "crafting-first":
        for app in CRAFTING_APPS:
            if not crafting[app].get("available"):
                degraded_capabilities.append(f"crafting_apps.{app}.cli")
    if adobe_required and tools["premiere"] and not broker.get("premiere_connected"):
        degraded_capabilities.append("premiere.uxp_rpc")
    if adobe_required and tools["afterfx"] and not ae_probe.get("script_rpc"):
        degraded_capabilities.append("after_effects.jsx_rpc")
    if not media_qc:
        degraded_capabilities.append("media.ffmpeg")
    if adobe_required and tools["premiere"] and not desktop_available:
        degraded_capabilities.append("premiere.desktop_fallback")
    blockers = []
    if not sources_ok:
        blockers.append("no readable source media in inventory")
    if ns.editor_priority == "adobe-only" and not adobe_any:
        blockers.append("Adobe-only policy requested but neither Premiere Pro nor After Effects is installed")
    elif ns.editor_priority == "crafting-first" and not (crafting_any or adobe_any):
        blockers.append("no usable video editor found (FilmCraft/EffectCraft CLI or Adobe Premiere Pro/After Effects)")

    # A stable job id survives re-runs so init history stays attributable to one job.
    prior = read_json(job / "plans/init_state.json")
    job_id = prior.get("job_id") or f"job-{hashlib.sha256(str(job).encode()).hexdigest()[:10]}"

    init = {
        "schema_version": 1,
        "job_id": job_id,
        "status": status,
        "timestamp": time.time(),
        "initialized_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "job_root": str(job),
        "machine_state_dir": str(global_dir),
        "source_inventory": "analysis/source_inventory.json",
        "environment": "analysis/environment.json",
        "capability_matrix": "plans/capability_matrix.json",
        "editor_priority": ns.editor_priority,
        "preferred_editors": preferred_editors(ns.editor_priority, crafting, tools),
        "preferred_premiere_surface": "uxp" if broker.get("premiere_connected") else (desktop_backend if desktop_available else None),
        "preferred_ae_surface": "jsx" if ae_probe.get("script_rpc") else (desktop_backend if desktop_available else None),
        "degraded_capabilities": degraded_capabilities,
        "blockers": blockers,
        "next": "workflow-routing" if status != "BLOCKED" else "resolve-blockers",
        "source_inventory_ok": sources_ok,
        "source_files_found": len(existing_sources),
        "bridge_secret_file": str(secret_file),
        "notes": notes,
    }
    (job / "plans/init_state.json").write_text(json.dumps(init, indent=2, ensure_ascii=False), encoding="utf-8")
    with (job / "logs/initialize.log").open("a", encoding="utf-8") as logf:
        logf.write(json.dumps(init, ensure_ascii=False) + "\n")
    history = job / "recovery/init-history" / f"init-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.json"
    history.write_text(json.dumps({"init": init, "capabilities": capabilities}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(init, indent=2, ensure_ascii=False))
    raise SystemExit(0 if status != "BLOCKED" else 2)


if __name__ == "__main__":
    main()
