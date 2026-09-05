#!/usr/bin/env python3
"""Loopback RPC broker between an external AI agent and the Premiere UXP bridge.

Premiere UXP can be a WebSocket client, not a server. This broker therefore exposes:
  * :8765 - Premiere bridge endpoint
  * :8766 - controller/agent endpoint

Both sides authenticate with the same machine-local secret, copied into each job runtime state. No arbitrary code execution is
accepted by the UXP bridge; only explicit registered operations are forwarded.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed


@dataclass
class BrokerState:
    started_at: float
    premiere_connected: bool = False
    premiere_info: dict[str, Any] | None = None
    premiere_last_seen: float | None = None
    forwarded_requests: int = 0
    failed_requests: int = 0


class Broker:
    def __init__(self, secret: str, state_path: Path | None, premiere_port: int, control_port: int):
        self.secret = secret
        self.state_path = state_path
        self.premiere_port = premiere_port
        self.control_port = control_port
        self.state = BrokerState(started_at=time.time())
        self.premiere_ws = None
        self.premiere_lock = asyncio.Lock()
        self._write_state()

    def _write_state(self):
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self.state) | {
            "premiere_port": self.premiere_port,
            "control_port": self.control_port,
            "pid": os.getpid(),
        }
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    async def premiere_handler(self, ws):
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            hello = json.loads(raw)
            if hello.get("type") != "hello" or hello.get("secret") != self.secret:
                await ws.close(code=4001, reason="authentication failed")
                return
            if self.premiere_ws is not None:
                try:
                    await self.premiere_ws.close(code=4002, reason="replaced by new Premiere bridge")
                except Exception:
                    pass
            self.premiere_ws = ws
            self.state.premiere_connected = True
            self.state.premiere_info = {
                "premiereVersion": hello.get("premiereVersion"),
                "uxpVersion": hello.get("uxpVersion"),
                "bridgeVersion": hello.get("bridgeVersion"),
                "capabilities": hello.get("capabilities", []),
            }
            self.state.premiere_last_seen = time.time()
            self._write_state()
            await ws.wait_closed()
        except Exception:
            pass
        finally:
            if self.premiere_ws is ws:
                self.premiere_ws = None
                self.state.premiere_connected = False
                self._write_state()

    async def _forward_to_premiere(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.premiere_ws is None:
            return {"id": request.get("id"), "ok": False, "error": "Premiere bridge is not connected"}
        timeout = float(request.get("timeout", 60))
        payload = {"id": request.get("id") or str(uuid.uuid4()), "op": request.get("op"), "args": request.get("args") or {}}
        async with self.premiere_lock:
            try:
                await self.premiere_ws.send(json.dumps(payload))
                raw = await asyncio.wait_for(self.premiere_ws.recv(), timeout=timeout)
                self.state.premiere_last_seen = time.time()
                self.state.forwarded_requests += 1
                self._write_state()
                return json.loads(raw)
            except Exception as exc:
                self.state.failed_requests += 1
                self._write_state()
                return {"id": payload["id"], "ok": False, "error": f"Premiere RPC failed: {exc}"}

    async def control_handler(self, ws):
        try:
            async for raw in ws:
                try:
                    req = json.loads(raw)
                except Exception:
                    await ws.send(json.dumps({"ok": False, "error": "invalid JSON"}))
                    continue
                if req.get("secret") != self.secret:
                    await ws.send(json.dumps({"id": req.get("id"), "ok": False, "error": "authentication failed"}))
                    continue
                op = req.get("op")
                if op == "broker.status":
                    await ws.send(json.dumps({"id": req.get("id"), "ok": True, "result": asdict(self.state)}))
                    continue
                result = await self._forward_to_premiere(req)
                await ws.send(json.dumps(result))
        except ConnectionClosed:
            return


async def amain(args):
    secret = args.secret
    if args.secret_file:
        secret = Path(args.secret_file).read_text(encoding="utf-8").strip()
    if not secret:
        raise SystemExit("A non-empty --secret or --secret-file is required")
    broker = Broker(secret, Path(args.state) if args.state else None, args.premiere_port, args.control_port)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is not None:
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass
    async with serve(broker.premiere_handler, args.host, args.premiere_port, max_size=8 * 1024 * 1024), \
               serve(broker.control_handler, args.host, args.control_port, max_size=8 * 1024 * 1024):
        await stop.wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--premiere-port", type=int, default=8765)
    ap.add_argument("--control-port", type=int, default=8766)
    ap.add_argument("--secret", default=None)
    ap.add_argument("--secret-file", default=None)
    ap.add_argument("--state", default=None)
    args = ap.parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
