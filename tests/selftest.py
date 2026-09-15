#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import py_compile
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIPPED = []


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def skip(name, reason):
    SKIPPED.append(f"{name} ({reason})")


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
            # Negative paths must fail cleanly, not forward to Premiere.
            await controller.send("not json at all")
            resp = json.loads(await asyncio.wait_for(controller.recv(), timeout=4))
            check(resp.get("ok") is False and "invalid JSON" in resp.get("error", ""), "malformed JSON not rejected")

            await controller.send(json.dumps([1, 2, 3]))
            resp = json.loads(await asyncio.wait_for(controller.recv(), timeout=4))
            check(resp.get("ok") is False and "JSON object" in resp.get("error", ""), "non-object request not rejected")

            await controller.send(json.dumps({"id": "bad", "secret": "wrong", "op": "ping", "args": {}}))
            resp = json.loads(await asyncio.wait_for(controller.recv(), timeout=4))
            check(resp.get("ok") is False and "authentication failed" in resp.get("error", ""), "bad secret not rejected")

            # A non-ASCII secret must fail auth, not crash the handler task.
            await controller.send(json.dumps({"id": "bad2", "secret": "sëcret→", "op": "ping", "args": {}}))
            resp = json.loads(await asyncio.wait_for(controller.recv(), timeout=4))
            check(resp.get("ok") is False and "authentication failed" in resp.get("error", ""), "non-ASCII secret not rejected cleanly")

            await controller.send(json.dumps({"id": "st", "secret": secret, "op": "broker.status", "args": {}}))
            resp = json.loads(await asyncio.wait_for(controller.recv(), timeout=4))
            check(resp.get("ok") is True and resp.get("result", {}).get("control_port") == control_port, "broker.status failed")

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
    else:
        skip("node --check", "node not installed")

    # --- In-process unit checks (stdlib-only modules; no Adobe host required) ---
    sys.path.insert(0, str(ROOT / "runtime"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import ae_rpc, analyze_media, qc, source_inventory  # noqa: E402

    # AE JSX generation: payload text must survive placeholder substitution and
    # ES3 line terminators must be escaped.
    jsx_src = ae_rpc.compile_jsx(
        {"actions": [{"op": "addTextLayer", "comp": "C", "text": "literal __RESULT_FILE__ and \u2028sep"}]},
        Path("/tmp/ae-result-selftest.json"),
    )
    check("__RESULT_FILE__" in jsx_src, "payload placeholder text was rewritten")
    check(jsx_src.count("/tmp/ae-result-selftest.json") == 1, "result path must appear exactly once")
    check("\u2028" not in jsx_src and "\\u2028" in jsx_src, "U+2028 must be escaped in generated JSX")

    for ext, want in {".mxf": "video", ".r3d": "video", ".braw": "video", ".mts": "video",
                      ".wav": "audio", ".srt": "subtitle", ".prproj": "project",
                      ".mogrt": "mogrt", ".dpx": "image", ".xyz": "asset"}.items():
        check(source_inventory.kind(Path("clip" + ext)) == want, f"kind({ext}) misclassified as {source_inventory.kind(Path('clip' + ext))}")

    code, _, err = source_inventory.run([sys.executable, "-c", "import time; time.sleep(3)"], timeout=0.3)
    check(code == 124 and "timed out" in err, "run() must report subprocess timeouts")

    sil = analyze_media.parse_silence("silence_start: -0.023\nsilence_end: 1.5 | silence_duration: 1.523\nsilence_start: 4.0\n")
    check(sil == [{"start": -0.023, "end": 1.5}, {"start": 4.0, "end": None}], "negative/unmatched silence ranges misparsed")
    starts, ends = qc.parse_silence("silence_start: -0.5\nsilence_end: 2.0 | silence_duration: 2.5\n")
    check(starts == ["-0.5"] and ends == ["2.0"], "qc silence parse failed")
    lufs, peak = qc.parse_loudness("    I:         -14.2 LUFS\n    Peak:      -1.5 dBFS\n")
    check(lufs == -14.2 and peak == -1.5, "qc loudness parse failed")

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

        # A secret containing quotes/newlines must not break out of the JS string.
        hostile = 'x";process.exit(1);//\n'
        r = subprocess.run(
            [sys.executable, str(ROOT / "runtime/package_bridge.py"), "--template", str(ROOT / "templates/premiere-uxp"), "--out", str(td / "h"), "--secret", hostile],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        check(r.returncode == 0, r.stderr)
        hcfg = (td / "h/premiere-uxp/runtime-config.js").read_text(encoding="utf-8")
        m = re.search(r'secret:\s*("(?:\\.|[^"\\])*")', hcfg)
        check(m and json.loads(m.group(1)) == hostile, "hostile secret not escaped in runtime-config.js")
        if shutil.which("node"):
            subprocess.run(["node", "--check", str(td / "h/premiere-uxp/runtime-config.js")], check=True)

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

        # dispatch() must delete a stale result file instead of consuming it.
        stale = td / "ae-stale-result.json"
        stale.write_text('{"ok": true, "stale": true}')
        out = ae_rpc.dispatch(sys.executable, td / "noop.jsx", stale, timeout=0.8)
        check(out.get("ok") is False and "Timed out" in str(out.get("error")), "dispatch consumed a stale result file")
        check(not stale.exists(), "stale result file was not removed before dispatch")

        # iter_files must terminate on symlink cycles and list each file once.
        try:
            cyc = td / "cycle"
            (cyc / "sub").mkdir(parents=True)
            (cyc / "a.mov").write_text("x")
            (cyc / "sub" / "b.mxf").write_text("x")
            (cyc / "loop").symlink_to(cyc)
            files = [str(p) for p in source_inventory.iter_files(cyc)]
            check(len(files) == len(set(files)) == 2, "iter_files must be cycle-safe and duplicate-free")
        except OSError:
            skip("symlink cycle traversal", "symlinks unsupported")

        # Plan loading/validation.
        try:
            import execute_plan  # noqa: E402
        except ImportError:
            skip("execute_plan checks", "websockets not installed")
        else:
            for bad in (["x"], {"actions": "no"}, {"actions": [{"op": "ping"}]}):
                try:
                    execute_plan.minimal_plan_check(bad)
                    raise AssertionError("minimal_plan_check accepted invalid plan")
                except SystemExit:
                    pass
            execute_plan.minimal_plan_check({"actions": [{"engine": "shell"}]})
            bad_plan = td / "bad-plan.json"
            bad_plan.write_text("{not json")
            try:
                execute_plan.load_plan(bad_plan, ROOT)
                raise AssertionError("load_plan accepted malformed JSON")
            except SystemExit as e:
                check("Could not read plan" in str(e), "load_plan error message missing")
            noeng = td / "noeng.json"
            noeng.write_text(json.dumps({"actions": [{"op": "x"}]}))
            try:
                execute_plan.load_plan(noeng, ROOT)
                raise AssertionError("load_plan accepted action without engine")
            except SystemExit:
                pass
            good = td / "good.json"
            good.write_text(json.dumps({"actions": [{"engine": "shell", "argv": ["echo", "hi"]}]}))
            check(execute_plan.load_plan(good, ROOT)["actions"][0]["engine"] == "shell", "valid plan rejected")

            # initialize.py end-to-end: no readable sources -> BLOCKED contract artifacts.
            job = td / "job"
            r = subprocess.run(
                [sys.executable, str(ROOT / "runtime/initialize.py"), "--job-root", str(job),
                 "--skill-root", str(ROOT), "--brief", "selftest", "--source", str(td / "missing.mov")],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            check(r.returncode == 2, f"initialize should exit 2 when BLOCKED: {r.stderr[-400:]}")
            init = json.loads((job / "plans/init_state.json").read_text())
            for field in ("schema_version", "job_id", "status", "initialized_at", "job_root",
                          "source_inventory", "environment", "capability_matrix", "next",
                          "degraded_capabilities", "blockers", "notes"):
                check(field in init, f"init_state missing documented field {field}")
            check(init["status"] == "BLOCKED" and init["blockers"], "init_state should be BLOCKED with blockers")
            check((job / "logs/initialize.log").stat().st_size > 0, "initialize.log not written")
            check(list((job / "recovery/init-history").glob("init-*.json")), "init history snapshot missing")

        # Exercise the real WebSocket broker with a mock Premiere client.
        try:
            import websockets  # noqa: F401
            pport, cport = free_port(), free_port()
            while cport == pport:
                cport = free_port()
            state_path = td / "broker-state.json"
            broker = subprocess.Popen([
                sys.executable, str(ROOT / "runtime/orchestrator.py"), "--secret", secret,
                "--premiere-port", str(pport), "--control-port", str(cport),
                "--state", str(state_path),
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
            state = json.loads(state_path.read_text())
            check(state.get("pid") and state.get("control_port") == cport, "broker state file incomplete")
            check(state.get("forwarded_requests", 0) >= 1, "forwarded request not recorded in state")
        except ImportError:
            skip("broker roundtrip", "websockets not installed")

    check((ROOT / "runtime/supervisor.py").exists(), "supervisor missing")
    for s in SKIPPED:
        print(f"SKIPPED: {s}")
    print("SELFTEST_OK")


if __name__ == "__main__":
    main()
