#!/usr/bin/env python3
"""Find supplementary stock media from provider APIs after an editor identifies a gap."""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from asset_download import write_rights_report

LICENSES = {
    "pexels": "https://www.pexels.com/license/",
    "pixabay": "https://pixabay.com/service/license-summary/",
}
HEADERS = {"User-Agent": "AdobeAutonomousEditor/1.0 (supplementary media research)"}
MAX_BYTES = 500 * 1024 * 1024


def get_json(url: str, headers: dict | None = None) -> dict:
    try:
        with urlopen(Request(url, headers={**HEADERS, **(headers or {})}), timeout=25) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Provider API returned HTTP {exc.code}") from exc


def post_json(url: str, headers: dict) -> dict:
    try:
        with urlopen(Request(url, data=b"{}", headers={**HEADERS, **headers, "Content-Type": "application/json"}), timeout=25) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Provider API returned HTTP {exc.code}") from exc


def clean_html(value: str | None) -> str | None:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip() or None


def candidate(provider: str, media_type: str, ident: str, page: str, media_url: str | None,
              title: str | None, creator: str | None, license_name: str | None,
              license_url: str | None, **extra) -> dict:
    return {"provider": provider, "media_type": media_type, "id": str(ident),
            "source_url": page, "media_url": media_url, "title": title,
            "creator": creator, "license": license_name, "license_url": license_url, **extra}


def search_pexels(query: str, media_type: str) -> list[dict]:
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return []
    endpoint = "videos/search" if media_type == "video" else "search"
    data = get_json(f"https://api.pexels.com/v1/{endpoint}?{urlencode({'query': query, 'per_page': 5})}",
                    {"Authorization": key})
    found = []
    for item in data.get("videos" if media_type == "video" else "photos", []):
        if media_type == "video":
            files = [f for f in item.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("link")]
            files.sort(key=lambda f: (f.get("width") or 0) * (f.get("height") or 0), reverse=True)
            media_url = files[0]["link"] if files else None
            creator = (item.get("user") or {}).get("name")
            title = None
        else:
            media_url = (item.get("src") or {}).get("original")
            creator = item.get("photographer")
            title = item.get("alt")
        found.append(candidate("pexels", media_type, item["id"], item["url"], media_url,
                               title, creator, "Pexels License", LICENSES["pexels"]))
    return found


def search_pixabay(query: str, media_type: str) -> list[dict]:
    key = os.getenv("PIXABAY_API_KEY")
    if not key:
        return []
    endpoint = "api/videos/" if media_type == "video" else "api/"
    data = get_json(f"https://pixabay.com/{endpoint}?{urlencode({'key': key, 'q': query[:100], 'per_page': 5, 'safesearch': 'true'})}")
    found = []
    for item in data.get("hits", []):
        if media_type == "video":
            streams = item.get("videos") or {}
            media_url = next((streams[size].get("url") for size in ("large", "medium", "small")
                              if streams.get(size, {}).get("url")), None)
        else:
            media_url = item.get("imageURL") or item.get("fullHDURL") or item.get("largeImageURL")
        found.append(candidate("pixabay", media_type, item["id"], item["pageURL"], media_url,
                               item.get("tags"), item.get("user"), "Pixabay Content License", LICENSES["pixabay"]))
    return found


def search_commons(query: str, media_type: str) -> list[dict]:
    params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": query,
              "gsrnamespace": 6, "gsrlimit": 12, "prop": "imageinfo", "iiprop": "url|mime|extmetadata"}
    data = get_json(f"https://commons.wikimedia.org/w/api.php?{urlencode(params)}")
    found = []
    for page in (data.get("query") or {}).get("pages", {}).values():
        info = next(iter(page.get("imageinfo") or []), {})
        mime = info.get("mime", "")
        if not mime.startswith(media_type + "/"):
            continue
        meta = info.get("extmetadata") or {}
        field = lambda name: clean_html((meta.get(name) or {}).get("value"))
        license_name = field("LicenseShortName")
        license_url = field("LicenseUrl")
        if not license_name or not license_url:
            continue
        found.append(candidate("commons", media_type, page["pageid"], info.get("descriptionurl"),
                               info.get("url"), clean_html(page.get("title")),
                               field("Artist") or info.get("user"), license_name, license_url,
                               attribution=field("AttributionRequired")))
    return found


def search_shutterstock(query: str, media_type: str) -> list[dict]:
    token = os.getenv("SHUTTERSTOCK_API_TOKEN")
    if not token:
        return []
    endpoint = "videos" if media_type == "video" else "images"
    data = get_json(f"https://api.shutterstock.com/v2/{endpoint}/search?{urlencode({'query': query, 'per_page': 5})}",
                    {"Authorization": f"Bearer {token}"})
    found = []
    for item in data.get("data", []):
        ident = str(item["id"])
        media_url = None
        license_name = None
        try:
            history = get_json(f"https://api.shutterstock.com/v2/{endpoint}/licenses?{urlencode({media_type + '_id': ident})}",
                               {"Authorization": f"Bearer {token}"})
            for licensed in history.get("data", []):
                if (str((licensed.get(media_type) or {}).get("id")) == ident
                        and licensed.get("is_downloadable")
                        and "comp" not in str(licensed.get("license", "")).lower()):
                    link = post_json(f"https://api.shutterstock.com/v2/{endpoint}/licenses/{licensed['id']}/downloads",
                                     {"Authorization": f"Bearer {token}"})
                    media_url = link.get("url")
                    license_name = licensed.get("license")
                    break
        except Exception:
            pass  # The search result remains a candidate requiring a license.
        found.append(candidate("shutterstock", media_type, ident,
                               f"https://www.shutterstock.com/{'video/clip' if media_type == 'video' else 'image-photo'}/{ident}",
                               media_url, item.get("description"), str((item.get("contributor") or {}).get("id") or "") or None,
                               license_name, "https://www.shutterstock.com/license",
                               license_status="review_required" if media_url else "license_required"))
    return found


PROVIDERS = (search_pexels, search_pixabay, search_commons, search_shutterstock)
ALLOWED_HOSTS = {
    "pexels": {"images.pexels.com", "player.vimeo.com"},
    "pixabay": {"pixabay.com", "cdn.pixabay.com"},
    "commons": {"upload.wikimedia.org"},
    "shutterstock": {"download.shutterstock.com"},
}


def allowed_host(provider: str, host: str | None) -> bool:
    if not host:
        return False
    if host in ALLOWED_HOSTS[provider]:
        return True
    if provider == "pexels":
        return host.endswith(".vimeocdn.com") or host == "vod-progressive.akamaized.net"
    if provider == "shutterstock":
        return host.startswith("download") and host.endswith(".shutterstock.com")
    return False


class ProviderRedirects(HTTPRedirectHandler):
    def __init__(self, provider: str):
        self.provider = provider

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https" or not allowed_host(self.provider, urlparse(newurl).hostname):
            raise ValueError("Download redirected outside the provider's media hosts")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def save_media(item: dict, job: Path) -> Path:
    url = item.get("media_url")
    if not url or urlparse(url).scheme != "https" or not allowed_host(item["provider"], urlparse(url).hostname):
        raise ValueError("Provider returned an unexpected download host")
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix not in ({".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"} if item["media_type"] == "image" else {".mp4", ".webm", ".ogv", ".mov"}):
        raise ValueError("Provider returned an unsupported media format")
    destination = job / "source" / "downloads" / item["provider"] / f"{item['id']}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size:
        return destination
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        opener = build_opener(ProviderRedirects(item["provider"]))
        with opener.open(Request(url, headers=HEADERS), timeout=60) as response, partial.open("wb") as output:
            if not allowed_host(item["provider"], urlparse(response.url).hostname):
                raise ValueError("Download redirected outside the provider's media hosts")
            if response.headers.get("Content-Type", "").lower().startswith(("text/", "application/json")):
                raise ValueError("Provider returned a document instead of media")
            length = int(response.headers.get("Content-Length", "0"))
            if length > MAX_BYTES:
                raise ValueError("Asset exceeds the 500 MB download limit")
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError("Asset exceeds the 500 MB download limit")
                output.write(chunk)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def safe_error(exc: Exception) -> str:
    # API and download errors can include credential-bearing URLs; never persist them.
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, ValueError) and str(exc).startswith(("Provider returned", "Download redirected", "Asset exceeds")):
        return str(exc)
    return type(exc).__name__


def rights(item: dict) -> dict:
    license_name = item.get("license")
    return {"source_url": item["source_url"], "webpage_url": item["source_url"],
            "title": item.get("title"), "creator": item.get("creator"),
            "license": license_name, "license_url": item.get("license_url"),
            "attribution": item.get("attribution"),
            "license_status": item.get("license_status", "review_required"),
            "notice": "Verify license restrictions, attribution, model/property releases, and intended use before publishing."
                      if license_name else "A license is required before this asset can be downloaded or used.",
            "terms_notice": "Check the provider's current terms and retain attribution when required."}


def acquire(job: Path, needs: list[dict]) -> dict:
    """Try bounded searches for agent identified gaps; keep full candidate provenance."""
    if len(needs) > 5:
        raise ValueError("At most five asset needs can be requested per run")
    output = {"needs": [], "downloaded": [], "errors": []}
    rights_path = job / "analysis" / "asset_rights.json"
    old = json.loads(rights_path.read_text(encoding="utf-8")).get("assets", []) if rights_path.exists() else []
    for need in needs:
        media_type = need.get("media_type")
        query = str(need.get("query") or "").strip()
        reason = str(need.get("reason") or "").strip()
        if media_type not in {"image", "video"} or not query or not reason or len(query) > 100:
            raise ValueError("Each need requires media_type (image/video), query (up to 100 characters), and reason")
        entry = {"query": query, "media_type": media_type, "reason": reason, "candidates": [], "selected": None}
        output["needs"].append(entry)
        for provider in PROVIDERS:
            if entry["selected"]:
                break
            try:
                candidates = provider(query, media_type)
                entry["candidates"].extend({k: v for k, v in item.items() if k != "media_url"} for item in candidates)
                for item in candidates:
                    if not item.get("media_url"):
                        continue
                    try:
                        path = save_media(item, job)
                        entry["selected"] = {"provider": item["provider"], "id": item["id"], "path": str(path)}
                        record = {"paths": [str(path)], "rights": rights(item)}
                        old = [r for r in old if r.get("paths") != record["paths"]]
                        old.append(record)
                        output["downloaded"].append(str(path))
                        break
                    except Exception as exc:
                        output["errors"].append(f"{item['provider']} {item['id']}: {safe_error(exc)}")
            except Exception as exc:
                output["errors"].append(f"{provider.__name__}: {safe_error(exc)}")
        if not entry["selected"]:
            for item in entry["candidates"]:
                if item.get("license_status") == "license_required":
                    old.append({"paths": [], "rights": rights(item)})
    analysis = job / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    (analysis / "asset_candidates.json").write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    if old:
        write_rights_report(job, old)
    if output["downloaded"]:
        inventory_path = analysis / "source_inventory.json"
        scanned = analysis / "supplementary_inventory.json"
        subprocess.run([sys.executable, str(Path(__file__).with_name("source_inventory.py")),
                        *output["downloaded"], "--out", str(scanned)], check=True, capture_output=True, text=True)
        inventory = json.loads(inventory_path.read_text(encoding="utf-8")) if inventory_path.exists() else {"sources": []}
        rows = json.loads(scanned.read_text(encoding="utf-8"))["sources"]
        paths = {row["path"] for row in rows}
        inventory["sources"] = [row for row in inventory["sources"] if row["path"] not in paths] + rows
        inventory_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
        scanned.unlink()
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--needs", type=Path, required=True, help="JSON array of agent identified asset gaps")
    args = parser.parse_args()
    result = acquire(args.job_root.resolve(), json.loads(args.needs.read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
