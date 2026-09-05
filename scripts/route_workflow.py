#!/usr/bin/env python3
"""Lightweight fallback router for workflow modules.

The agent should route semantically. This script is a deterministic baseline for
bootstrapping/tests and must not override an explicit user workflow choice.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def score(entry: dict, text: str) -> int:
    total = 0
    for sig in entry.get("signals", []):
        s = norm(sig)
        if s and s in text:
            total += max(1, len(s.split()))
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("brief", help="Natural-language editing brief")
    ap.add_argument(
        "--manifest",
        default=str(Path(__file__).resolve().parents[1] / "workflows" / "manifest.json"),
    )
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    text = norm(args.brief)

    primaries = [
        (score(x, text), x["id"]) for x in manifest.get("primary_workflows", [])
    ]
    primaries.sort(reverse=True)
    best_score, primary = primaries[0] if primaries else (0, None)
    if best_score <= 0:
        primary = None

    overlays = []
    for x in manifest.get("overlay_workflows", []):
        if score(x, text) > 0:
            overlays.append(x["id"])

    print(json.dumps({
        "primary": primary,
        "overlays": overlays,
        "routing_mode": "keyword-fallback",
        "semantic_review_required": True
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
