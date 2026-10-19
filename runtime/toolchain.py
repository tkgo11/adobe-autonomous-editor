#!/usr/bin/env python3
"""Install and expose routine local media tools without system-wide changes."""
from __future__ import annotations

import hashlib
import html
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path


USER_AGENT = "adobe-autonomous-editor-toolchain/1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _probe(path: str) -> dict:
    try:
        run = subprocess.run(
            [path, "-version"], text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=20,
        )
        first = (run.stdout or run.stderr).splitlines()
        return {
            "ok": run.returncode == 0,
            "returncode": run.returncode,
            "version": first[0] if first else None,
            "stderr": run.stderr[-2000:],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _prepend(path: Path) -> None:
    value = str(path.resolve())
    entries = os.environ.get("PATH", "").split(os.pathsep)
    if value not in entries:
        os.environ["PATH"] = os.pathsep.join([value, *entries])


def _request(url: str):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    try:
        with urllib.request.urlopen(_request(url), timeout=300) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def _is_musl_linux(system: str | None = None, libc: str | None = None) -> bool:
    system = system or platform.system()
    if system != "Linux":
        return False
    if libc is not None:
        return "musl" in libc.lower()
    detected_libc = platform.libc_ver()[0].lower()
    if "musl" in detected_libc:
        return True
    if any(Path("/lib").glob("ld-musl-*.so.1")):
        return True
    try:
        run = subprocess.run(["ldd", "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        return "musl" in (run.stdout + run.stderr).lower()
    except Exception:
        return False


def _btbn_asset(system: str | None = None, machine: str | None = None, libc: str | None = None) -> str | None:
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    arch = "64" if machine in {"x86_64", "amd64", "x64"} else "arm64" if machine in {"arm64", "aarch64"} else None
    if not arch:
        return None
    if system == "Windows":
        return f"ffmpeg-master-latest-win{arch}-gpl.zip"
    if system == "Linux" and not _is_musl_linux(system, libc):
        return f"ffmpeg-master-latest-linux{arch}-gpl.tar.xz"
    return None


def _release_digest(asset: str, repo: str = "BtbN/FFmpeg-Builds", tag: str = "latest") -> str:
    url = f"https://github.com/{repo}/releases/expanded_assets/{tag}"
    with urllib.request.urlopen(_request(url), timeout=60) as response:
        page = response.read().decode("utf-8", "replace")
    pattern = rf'aria-label="Copy to clipboard digest for {re.escape(html.escape(asset))}"[^>]*value="sha256:([0-9a-fA-F]{{64}})"'
    match = re.search(pattern, page)
    if not match:
        raise RuntimeError(f"GitHub release metadata did not publish a SHA-256 digest for {asset}")
    return match.group(1).lower()


def _latest_release_tag(repo: str) -> str:
    with urllib.request.urlopen(_request(f"https://github.com/{repo}/releases/latest"), timeout=60) as response:
        final = response.geturl()
    match = re.search(r"/releases/tag/([^/?#]+)$", final)
    if not match or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]*", match.group(1)):
        raise RuntimeError(f"could not resolve a safe release tag for {repo}: {final}")
    return match.group(1)


def _safe_target(root: Path, name: str) -> Path:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise RuntimeError(f"unsafe absolute archive member: {name}")
    target = (root / normalized).resolve()
    base = root.resolve()
    if target != base and base not in target.parents:
        raise RuntimeError(f"unsafe archive traversal member: {name}")
    return target


def _extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                target = _safe_target(destination, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(member) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
        return
    with tarfile.open(archive, "r:xz") as bundle:
        for member in bundle.getmembers():
            target = _safe_target(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise RuntimeError(f"could not read archive member: {member.name}")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)


def _find_binary(root: Path, name: str) -> Path | None:
    suffix = ".exe" if platform.system() == "Windows" else ""
    hits = sorted(root.rglob(name + suffix), key=lambda item: (len(item.parts), str(item)))
    return hits[0].resolve() if hits else None


def _install_btbn(root: Path, asset: str) -> tuple[str, str, dict]:
    expected = _release_digest(asset)
    archive = root / "downloads" / asset
    if not archive.exists() or _sha256(archive) != expected:
        _download(f"https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/{asset}", archive)
    actual = _sha256(archive)
    if actual != expected:
        raise RuntimeError(f"checksum mismatch for {asset}: expected {expected}, got {actual}")
    release = root / "releases" / expected[:16]
    if not release.exists():
        release.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ffmpeg-", dir=str(release.parent)) as temp_raw:
            temp = Path(temp_raw)
            _extract(archive, temp)
            Path(temp_raw).replace(release)
    ffmpeg = _find_binary(release, "ffmpeg")
    ffprobe = _find_binary(release, "ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(f"{asset} did not contain ffmpeg and ffprobe")
    if platform.system() != "Windows":
        ffmpeg.chmod(ffmpeg.stat().st_mode | 0o700)
        ffprobe.chmod(ffprobe.stat().st_mode | 0o700)
    return str(ffmpeg), str(ffprobe), {"asset": asset, "archive_sha256": actual, "expected_sha256": expected}


def _static_asset_names(system: str, machine: str | None = None) -> tuple[str, str]:
    machine = (machine or platform.machine()).lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64" if machine in {"x86_64", "amd64", "x64"} else None
    if not arch:
        raise RuntimeError(f"no managed ffmpeg-static distribution for {system}/{machine}")
    os_name = {"Darwin": "darwin", "Linux": "linux"}.get(system)
    if not os_name:
        raise RuntimeError(f"no managed ffmpeg-static distribution for {system}/{machine}")
    return f"ffmpeg-{os_name}-{arch}", f"ffprobe-{os_name}-{arch}"


def _mac_asset_names(machine: str | None = None) -> tuple[str, str]:
    return _static_asset_names("Darwin", machine)


def _install_static(root: Path, system: str) -> tuple[str, str, dict]:
    repo = "eugeneware/ffmpeg-static"
    tag = _latest_release_tag(repo)
    assets = _static_asset_names(system)
    target = root / "releases" / tag
    downloads = root / "downloads" / tag
    paths = []
    digests = {}
    for asset in assets:
        expected = _release_digest(asset, repo, tag)
        downloaded = downloads / asset
        if not downloaded.exists() or _sha256(downloaded) != expected:
            _download(f"https://github.com/{repo}/releases/download/{tag}/{asset}", downloaded)
        actual = _sha256(downloaded)
        if actual != expected:
            raise RuntimeError(f"checksum mismatch for {asset}: expected {expected}, got {actual}")
        target.mkdir(parents=True, exist_ok=True)
        installed = target / asset.split("-", 1)[0]
        shutil.copyfile(downloaded, installed)
        installed.chmod(0o755)
        paths.append(str(installed.resolve()))
        digests[asset] = actual
    return paths[0], paths[1], {"provider": repo, "tag": tag, "sha256": digests}


def _install_macos(root: Path) -> tuple[str, str, dict]:
    return _install_static(root, "Darwin")


def probe_system_media_tools() -> dict:
    """Return system media paths only after both executables pass probes."""
    paths = {"ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe")}
    result = {"ok": False, "installed": False, "source": "system", "probes": {}}
    if not all(paths.values()):
        result["error"] = "ffmpeg and ffprobe were not both found on PATH"
        return result
    probes = {name: _probe(path) for name, path in paths.items()}
    result["probes"] = probes
    if not all(item.get("ok") for item in probes.values()):
        result["error"] = f"system media tools failed version probes: {probes}"
        return result
    result.update({"ok": True, **paths})
    return result


def ensure_media_tools(state_dir: Path) -> dict:
    """Return verified ffmpeg/ffprobe paths, installing a local copy if needed.

    Windows/Linux use the SHA-256 published in BtbN's GitHub release metadata.
    macOS uses eugeneware/ffmpeg-static assets and GitHub-published SHA-256 digests.
    Every bundle lives under machine state, never a system directory, and both
    executables must pass a real version probe before use.
    """
    state_dir = Path(state_dir)
    system_tools = probe_system_media_tools()
    if system_tools["ok"]:
        return system_tools

    root = state_dir / "toolchain/ffmpeg"
    manifest_path = root / "manifest.json"
    try:
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        paths = prior["paths"]
        probes = {name: _probe(paths[name]) for name in ("ffmpeg", "ffprobe")}
        if all(item["ok"] for item in probes.values()):
            _prepend(Path(paths["ffmpeg"]).parent)
            return {
                "ok": True, "installed": False, "reused": True, "source": "managed",
                **paths, "probes": probes, "manifest": str(manifest_path),
            }
    except Exception:
        pass

    result = {"ok": False, "installed": False, "source": "managed", "error": None}
    try:
        existed = manifest_path.exists()
        asset = _btbn_asset()
        if asset:
            ffmpeg, ffprobe, provenance = _install_btbn(root, asset)
        elif platform.system() == "Darwin":
            ffmpeg, ffprobe, provenance = _install_macos(root)
        elif _is_musl_linux():
            # BtbN Linux releases require glibc. The ffmpeg-static project
            # publishes fully static Linux binaries and SHA-256 digests, so it
            # is safe to use on musl distributions such as Alpine.
            ffmpeg, ffprobe, provenance = _install_static(root, "Linux")
        else:
            raise RuntimeError(f"no managed ffmpeg distribution for {platform.system()}/{platform.machine()}")
        paths = {"ffmpeg": str(Path(ffmpeg).resolve()), "ffprobe": str(Path(ffprobe).resolve())}
        probes = {name: _probe(path) for name, path in paths.items()}
        if not all(item["ok"] for item in probes.values()):
            raise RuntimeError(f"managed media tools failed version probes: {probes}")
        _prepend(Path(paths["ffmpeg"]).parent)
        manifest = {
            "schema_version": 1,
            "source": "BtbN/FFmpeg-Builds" if asset else "eugeneware/ffmpeg-static",
            "provenance": provenance,
            "installed_at": time.time(),
            "paths": paths,
            "sha256": {name: _sha256(Path(path)) for name, path in paths.items()},
            "probes": probes,
        }
        root.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        result.update({
            "ok": True, "installed": not existed, **paths,
            "probes": probes, "manifest": str(manifest_path),
        })
    except Exception as exc:
        result["error"] = str(exc)
    return result


def restore_media_path(environment: dict) -> None:
    """Expose managed tools recorded by initialization to later job processes."""
    tools = environment.get("tools") or {}
    for key in ("ffmpeg", "ffprobe"):
        value = tools.get(key)
        if value and Path(value).exists():
            _prepend(Path(value).parent)
