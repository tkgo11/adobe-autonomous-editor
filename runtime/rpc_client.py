#!/usr/bin/env python3
"""CLI client for Autonomous Editor's local broker."""
from __future__ import annotations
import argparse, asyncio, json, uuid
from pathlib import Path
from websockets.asyncio.client import connect

async def call(uri: str, secret: str, op: str, args: dict, timeout: float):
    async with connect(uri, max_size=8 * 1024 * 1024) as ws:
        req = {"id": str(uuid.uuid4()), "secret": secret, "op": op, "args": args, "timeout": timeout}
        await ws.send(json.dumps(req))
        return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout + 5))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("op")
    ap.add_argument("--args", default="{}", help="JSON object")
    ap.add_argument("--args-file")
    ap.add_argument("--secret")
    ap.add_argument("--secret-file")
    ap.add_argument("--uri", default="ws://127.0.0.1:8766")
    ap.add_argument("--timeout", type=float, default=60)
    ns = ap.parse_args()
    secret = ns.secret or (Path(ns.secret_file).read_text(encoding="utf-8").strip() if ns.secret_file else None)
    if not secret:
        raise SystemExit("--secret or --secret-file required")
    args = json.loads(Path(ns.args_file).read_text(encoding="utf-8")) if ns.args_file else json.loads(ns.args)
    result = asyncio.run(call(ns.uri, secret, ns.op, args, ns.timeout))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result.get("ok") else 2)

if __name__ == "__main__":
    main()
