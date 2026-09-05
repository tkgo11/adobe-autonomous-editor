#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import py_compile
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def broker_roundtrip(premiere_port, control_port, secret):
    from websockets.asyncio.client import connect

    premiere = None
    deadline = asyncio.get_running_loop().time() + 5
    while premiere is None:
        try:
            premiere = await connect(f"ws://127.0.0.1:{premiere_port}")
        except OSError:
            if asyncio.get_running_loop().time() >= deadline:
                raise
            await asyncio.sleep(0.1)
    async with premiere:
        await premiere.send(json.dumps({
            "type": "hello", "secret": secret, "premiereVersion": "selftest",
            "uxpVersion": "selftest", "bridgeVersion": "selftest", "capabilities": ["ping"],
        }))

        async def mock_host():
            req = json.loads(await asyncio.wait_for(premiere.recv(), timeout=3))
            check(req["op"] == "ping", "broker forwarded wrong op")
            await premiere.send(json.dumps({"id": req["id"], "ok": True, "result": {"pong": True}}))

        task = asyncio.create_task(mock_host())
        async with connect(f"ws://127.0.0.1:{control_port}") as controller:
            await controller.send(json.dumps({"id": "r1", "secret": secret, "op": "ping", "args": {}, "timeout": 3}))
            resp = json.loads(await asyncio.wait_for(controller.recv(), timeout=4))
            check(resp.get("ok") is True and resp.get("result", {}).get("pong") is True, "broker roundtrip failed")
        await task


def main():
    for p in (ROOT / "runtime").glob("*.py"):
        py_compile.compile(str(p), doraise=True)
    for p in (ROOT / "scripts").glob("*.py"):
        py_compile.compile(str(p), doraise=True)
    for p in ROOT.rglob("*.json"):
        json.loads(p.read_text(encoding="utf-8-sig"))

    m = json.loads((ROOT / "templates/premiere-uxp/manifest.json").read_text())
    check(m["manifestVersion"] == 5, "UXP manifest must be v5")
    check(m["host"]["minVersion"] == "25.6.0", "Premiere minimum mismatch")
    domains = m.get("requiredPermissions", {}).get("network", {}).get("domains", [])
    check(any("127.0.0.1:8765" in x for x in domains), "Premiere broker permission missing")

    js = (ROOT / "templates/premiere-uxp/index.js").read_text()
    for op in [
        "importFiles", "createSequence", "insertProjectItem", "editTrackItem", "addEffect",
        "setEffectParam", "insertMogrt", "importAEComps", "exportSequence",
        "attachProxy", "changeMediaPath", "createSubclip", "transcribeProjectItem",
        "exportTranscript", "getSequenceSettings", "setSequenceQuality", "renameTrack",
    ]:
        check(f"async {op}" in js, f"missing Premiere handler {op}")
    if shutil.which("node"):
        subprocess.run(["node", "--check", str(ROOT / "templates/premiere-uxp/index.js")], check=True)

    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        secret = "selftest-secret"
        r = subprocess.run(
            [sys.executable, str(ROOT / "runtime/package_bridge.py"), "--template", str(ROOT / "templates/premiere-uxp"), "--out", str(td), "--secret", secret],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        check(r.returncode == 0, r.stderr)
        ccx = Path(r.stdout.strip())
        check(ccx.exists(), "ccx not created")
        with zipfile.ZipFile(ccx) as z:
            check("manifest.json" in z.namelist(), "manifest missing from ccx")
            cfg = z.read("runtime-config.js").decode()
            check(secret in cfg, "secret not injected")

        plan = td / "ae.json"
        plan.write_text(json.dumps({"actions": [
            {"op": "newProject"},
            {"op": "createComp", "name": "T", "width": 64, "height": 64, "duration": 1, "fps": 24},
            {"op": "addTextLayer", "comp": "T", "name": "Title", "text": "Hello"},
            {"op": "setTextDocument", "comp": "T", "name": "Title", "fontSize": 24},
            {"op": "setLayerSwitches", "comp": "T", "name": "Title", "motionBlur": True},
            {"op": "addMask", "comp": "T", "name": "Title", "maskName": "Mask 1"},
            {"op": "setMaskProperties", "comp": "T", "name": "Title", "maskName": "Mask 1", "opacity": 100},
            {"op": "setCompWorkArea", "comp": "T", "start": 0, "duration": 1}
        ]}))
        r = subprocess.run([sys.executable, str(ROOT / "runtime/ae_rpc.py"), str(plan), "--compile-only"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        check(r.returncode == 0, r.stderr)
        compiled = json.loads(r.stdout)
        jsx_path = Path(compiled["jsx"])
        check(jsx_path.exists(), "AE JSX not generated")
        if shutil.which("node"):
            js_copy = td / "compiled-ae-selftest.js"
            shutil.copyfile(jsx_path, js_copy)
            subprocess.run(["node", "--check", str(js_copy)], check=True)

        # Exercise the real WebSocket broker with a mock Premiere client.
        try:
            import websockets  # noqa: F401
            pport, cport = free_port(), free_port()
            while cport == pport:
                cport = free_port()
            broker = subprocess.Popen([
                sys.executable, str(ROOT / "runtime/orchestrator.py"), "--secret", secret,
                "--premiere-port", str(pport), "--control-port", str(cport),
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                time.sleep(0.5)
                asyncio.run(broker_roundtrip(pport, cport, secret))
            finally:
                broker.terminate()
                try:
                    broker.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    broker.kill()
        except ImportError:
            pass

    check((ROOT / "runtime/supervisor.py").exists(), "supervisor missing")
    print("SELFTEST_OK")


if __name__ == "__main__":
    main()
