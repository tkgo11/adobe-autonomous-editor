#!/usr/bin/env python3
"""Fetch explicitly supplied media URLs and record their rights metadata."""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_BYTES = 2 * 1024 * 1024 * 1024
MAX_SECONDS = 2 * 60 * 60


class DownloadError(RuntimeError):
    def __init__(self, message: str, rights: dict):
        super().__init__(message)
        self.rights = rights


def safe_error_message(exc: Exception) -> str:
    """Keep actionable diagnostics while stripping signed URLs and userinfo."""
    message = re.sub(r"https?://[^\s\]\[<>\"']+", lambda match: public_url(match.group(0).rstrip(".,)")), str(exc))
    message = re.sub(r"[\r\n\t]+", " ", message)
    return message[:500] or type(exc).__name__


def public_url(value: str) -> str:
    """Keep public identity parameters while removing credentials and signatures."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if not host:
            return "<invalid URL>"
        if ":" in host:
            host = f"[{host}]"
        netloc = host + (f":{parsed.port}" if parsed.port else "")
        safe_query = []
        identity_parameters = {"v", "id", "videoid", "photoid", "assetid", "t", "start", "end", "list", "index", "locale", "feature"}
        for key, item in parse_qsl(parsed.query, keep_blank_values=True):
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in identity_parameters and not normalized.startswith("xamz"):
                safe_query.append((key, item))
        return urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(safe_query), ""))
    except ValueError:
        return "<invalid URL>"


def is_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def rights_record(url: str, info: dict | None = None, error: str | None = None) -> dict:
    info = info or {}
    license_name = info.get("license") or None
    return {
        "source_url": public_url(url),
        "webpage_url": public_url(info.get("webpage_url") or url),
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
        "asset_origin": "user_url",
        "error": error,
    }


def download(url: str, job: Path) -> dict:
    """Download one video/audio asset; return paths and a rights record."""
    if not is_url(url):
        raise ValueError(f"Not an HTTP(S) URL: {url}")
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("URL sources require yt-dlp; install the runtime requirements") from exc

    destination = job / "source" / "downloads"
    destination.mkdir(parents=True, exist_ok=True)
    options = {
        "noplaylist": True,
        "outtmpl": str(destination / "%(extractor_key)s" / "%(id)s.%(ext)s"),
        "restrictfilenames": True,
        "overwrites": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
        "max_filesize": MAX_BYTES,
    }
    if not shutil.which("ffmpeg"):
        options["format"] = "best"  # Choose a single combined rendition when merging is unavailable.
    started = time.monotonic()

    def progress(status):
        if time.monotonic() - started > MAX_SECONDS:
            raise RuntimeError("Download exceeded the two-hour time limit")
        size = status.get("downloaded_bytes") or status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        if size > MAX_BYTES:
            raise RuntimeError("Download exceeded the 2 GB size limit")

    options["progress_hooks"] = [progress]
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        if not isinstance(info, dict) or info.get("_type") in {"playlist", "multi_video"}:
            raise RuntimeError("Expected a single media item, not a playlist")
        rights = rights_record(url, info)
        try:
            if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
                raise RuntimeError("Live and upcoming streams are not supported")
            if (info.get("duration") or 0) > MAX_SECONDS:
                raise RuntimeError("Media exceeds the two-hour duration limit")
            if (info.get("filesize") or info.get("filesize_approx") or 0) > MAX_BYTES:
                raise RuntimeError("Media exceeds the 2 GB size limit")
            result = ydl.extract_info(url, download=True)
            if not isinstance(result, dict):
                raise RuntimeError("Downloader returned no media details")
            final = [result.get("filepath"), ydl.prepare_filename(result)]
            paths = [Path(p).resolve() for p in final if p]
            paths = [p for p in paths if p.is_file() and p.is_relative_to(destination.resolve())]
            components = [Path(item["filepath"]).resolve() for item in result.get("requested_downloads", []) if item.get("filepath")]
            components = [p for p in components if p.is_file() and p.is_relative_to(destination.resolve())]
            if len(components) > 1 and (not paths or paths[0] in components):
                raise RuntimeError("Separate audio/video streams could not be merged")
            if not paths:
                paths = components
            if not paths:
                raise RuntimeError("Downloader reported success but no local media file was found")
        except Exception as exc:
            raise DownloadError(str(exc), rights) from exc
    return {"paths": [str(p) for p in paths], "rights": rights}


def write_rights_report(job: Path, records: list[dict]) -> None:
    target = job / "analysis"
    target.mkdir(parents=True, exist_ok=True)
    (target / "asset_rights.json").write_text(json.dumps({"assets": records}, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Downloaded asset rights", "", "Review each asset's license and source terms before use or publication.", ""]
    def safe(value):
        value = re.sub(r"\s+", " ", str(value or ""))
        return re.sub(r"([\\`*_[\]#<>|])", r"\\\1", value)

    for record in records:
        rights = record["rights"]
        lines.extend([
            f"## {safe(rights.get('title') or rights['source_url'])}", "",
            f"- Source: {safe(rights['webpage_url'])}",
            f"- Creator: {safe(rights.get('creator') or 'Not provided')}",
            f"- License: {safe(rights.get('license') or 'Not provided by source')}",
            f"- License terms: {safe(rights.get('license_url') or 'Not provided by source')}",
            f"- Attribution required: {safe(rights.get('attribution') or 'Check license terms')}",
            f"- Status: {safe(rights['license_status'])}",
            f"- Notice: {safe(rights['notice'])}",
            f"- Terms: {safe(rights['terms_notice'])}",
            f"- Local files: {safe(', '.join(record.get('paths', [])) or 'None')}",
        ])
        if rights.get("error"):
            lines.append(f"- Download error: {safe(rights['error'])}")
        lines.append("")
    (target / "asset_rights.md").write_text("\n".join(lines), encoding="utf-8")
