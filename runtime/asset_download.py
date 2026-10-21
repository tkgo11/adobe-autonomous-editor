#!/usr/bin/env python3
"""Fetch explicitly supplied media URLs and record their rights metadata."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def rights_record(url: str, info: dict | None = None, error: str | None = None) -> dict:
    info = info or {}
    license_name = info.get("license") or None
    return {
        "source_url": url,
        "webpage_url": info.get("webpage_url") or url,
        "title": info.get("title"),
        "creator": info.get("creator") or info.get("uploader") or info.get("channel"),
        "license": license_name,
        "license_status": "review_required",
        "notice": (
            "Source lists this license; verify its terms, attribution, and your intended use before publishing."
            if license_name else
            "Source did not provide a license. Downloading does not grant permission to reuse or publish."
        ),
        "terms_notice": "Check the source site's terms and obtain any required permission before use.",
        "error": error,
    }


def download(url: str, job: Path) -> dict:
    """Download one video/audio asset; return paths and a rights record."""
    if not is_url(url):
        raise ValueError(f"Not an HTTP(S) URL: {url}")
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("URL sources require yt-dlp; install runtime/requirements.txt") from exc

    destination = job / "source" / "downloads"
    destination.mkdir(parents=True, exist_ok=True)
    options = {
        "noplaylist": True,
        "outtmpl": str(destination / "%(extractor_key)s" / "%(id)s.%(ext)s"),
        "restrictfilenames": True,
        "nooverwrites": True,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        if not isinstance(info, dict) or info.get("_type") in {"playlist", "multi_video"}:
            raise RuntimeError("Expected a single media item, not a playlist")
        rights = rights_record(url, info)
        result = ydl.extract_info(url, download=True)
        if not isinstance(result, dict):
            raise RuntimeError("Downloader returned no media details")
        candidates = [result.get("filepath"), ydl.prepare_filename(result)]
        candidates.extend(item.get("filepath") for item in result.get("requested_downloads", []))
        paths = [Path(p).resolve() for p in candidates if p]
        paths = [p for p in paths if p.is_file() and p.is_relative_to(destination.resolve())]
        # The first path is the final output when yt-dlp merges separate streams.
        paths = paths[:1]
        if not paths:
            raise RuntimeError("Downloader reported success but no local media file was found")
    return {"paths": [str(p) for p in paths], "rights": rights}


def write_rights_report(job: Path, records: list[dict]) -> None:
    target = job / "analysis"
    target.mkdir(parents=True, exist_ok=True)
    (target / "asset_rights.json").write_text(json.dumps({"assets": records}, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Downloaded asset rights", "", "Review each asset's license and source terms before use or publication.", ""]
    for record in records:
        rights = record["rights"]
        lines.extend([
            f"## {rights.get('title') or rights['source_url']}", "",
            f"- Source: {rights['webpage_url']}",
            f"- Creator: {rights.get('creator') or 'Not provided'}",
            f"- License: {rights.get('license') or 'Not provided by source'}",
            f"- Status: {rights['license_status']}",
            f"- Notice: {rights['notice']}",
            f"- Terms: {rights['terms_notice']}",
            f"- Local files: {', '.join(record.get('paths', [])) or 'None'}",
        ])
        if rights.get("error"):
            lines.append(f"- Download error: {rights['error']}")
        lines.append("")
    (target / "asset_rights.md").write_text("\n".join(lines), encoding="utf-8")
