#!/usr/bin/env python3
"""Install, discover, probe, and invoke the video-related Crafting Apps CLIs.

Only FilmCraft (video editing) and EffectCraft (motion graphics/VFX) are in
scope.  Releases are downloaded from the official ``storytold`` GitHub
repositories and must match the published SHA256SUMS.txt before extraction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid
import urllib.request
import zipfile
from pathlib import Path


APPS = {
    "filmcraft": {
        "cli": "filmcraft-cli",
        "repo": "storytold/filmcraft",
        "role": "nonlinear video editing, color, sound, captions, and delivery",
    },
    "effectcraft": {
        "cli": "effectcraft-cli",
        "repo": "storytold/effectcraft",
        "role": "motion graphics, compositing, visual effects, and animation",
    },
}
USER_AGENT = "autonomous-video-editor-crafting-apps/1"


def _arch() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64", "x64"}:
        return "x86_64"
    if machine in {"aarch64", "arm64"}:
        return "aarch64"
    if machine in {"x86", "i386", "i686"}:
        return "x86"
    return machine


def release_asset(app: str, version: str, system: str | None = None, arch: str | None = None) -> str:
    """Return the official release artifact containing the requested CLI."""
    system = system or platform.system()
    arch = arch or _arch()
    if system == "Darwin":
        return f"{app}-cli-{version}-macos-universal.zip"
    if system == "Windows":
        win_arch = {"x86_64": "x64", "aarch64": "arm64", "x86": "x86"}.get(arch)
        if not win_arch:
            raise RuntimeError(f"Unsupported Windows architecture: {arch}")
        return f"{app}-{version}-windows-{win_arch}-portable.zip"
    if system == "Linux":
        linux_arch = {"x86_64": "x86_64", "aarch64": "aarch64"}.get(arch)
        if not linux_arch:
            raise RuntimeError(f"Unsupported Linux architecture: {arch}")
        return f"{app}-{version}-linux-{linux_arch}.tar.gz"
    if system == "FreeBSD" and arch == "x86_64":
        return f"{app}-{version}-freebsd-x86_64.tar.gz"
    raise RuntimeError(f"No official {app} CLI release for {system}/{arch}")


def _request(url: str, method: str = "GET"):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method=method)


def latest_version(repo: str, timeout: float = 30) -> str:
    """Resolve GitHub's /releases/latest redirect without requiring the API."""
    url = f"https://github.com/{repo}/releases/latest"
    with urllib.request.urlopen(_request(url, "HEAD"), timeout=timeout) as response:
        final = response.geturl()
    match = re.search(r"/releases/tag/v?([^/?#]+)", final)
    if not match:
        raise RuntimeError(f"Could not resolve latest release tag for {repo}: {final}")
    version = match.group(1)
    if version in {".", ".."} or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]*", version):
        raise RuntimeError(f"Unsafe release tag for {repo}: {version}")
    return version


def _download(url: str, destination: Path, timeout: float = 120) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    try:
        with urllib.request.urlopen(_request(url), timeout=timeout) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out, length=1024 * 1024)
        partial.replace(destination)
    finally:
        try:
            partial.unlink()
        except FileNotFoundError:
            pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_checksum(checksums: str, artifact: str) -> str:
    for line in checksums.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            name = parts[-1].lstrip("*")
            if name == artifact:
                return parts[0].lower()
    raise RuntimeError(f"{artifact} is missing from SHA256SUMS.txt")


def _safe_target(root: Path, name: str) -> Path:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise RuntimeError(f"Unsafe absolute archive member: {name}")
    target = (root / normalized).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise RuntimeError(f"Unsafe archive traversal member: {name}")
    return target


def _extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                target = _safe_target(destination, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open("wb") as out:
                    shutil.copyfileobj(source, out)
        return
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                target = _safe_target(destination, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    # Release packages do not require links for the CLIs. Refuse them
                    # rather than allowing archive-controlled link targets.
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise RuntimeError(f"Could not read archive member: {member.name}")
                with source, target.open("wb") as out:
                    shutil.copyfileobj(source, out)
                try:
                    target.chmod(member.mode & 0o777)
                except OSError:
                    pass
        return
    raise RuntimeError(f"Unsupported release archive: {archive.name}")


def _binary_name(app: str) -> str:
    suffix = ".exe" if platform.system() == "Windows" else ""
    return APPS[app]["cli"] + suffix


def _find_in_tree(root: Path, app: str) -> Path | None:
    if not root.exists():
        return None
    candidates = sorted(root.rglob(_binary_name(app)), key=lambda p: (len(p.parts), str(p)))
    return candidates[0].resolve() if candidates else None


def discover(app: str, state_dir: Path | None = None) -> str | None:
    """Find a working managed release first, then a working CLI on PATH."""
    candidates: list[str] = []
    if state_dir:
        root = (Path(state_dir) / "crafting-apps" / app).resolve()
        try:
            manifest = json.loads((root / "install.json").read_text(encoding="utf-8"))
            recorded = Path(manifest["path"]).resolve()
            if root in recorded.parents and recorded.name == _binary_name(app) and recorded.is_file() and os.access(recorded, os.X_OK):
                candidates.append(str(recorded))
        except Exception:
            pass
        hit = _find_in_tree(root, app)
        if hit and str(hit) not in candidates:
            candidates.append(str(hit))
    path = shutil.which(APPS[app]["cli"])
    if path:
        system_path = str(Path(path).resolve())
        if system_path not in candidates:
            candidates.append(system_path)
    for candidate in candidates:
        if probe(app, candidate).get("available"):
            return candidate
    return None


def _catalog_probe(app: str, path: str) -> dict:
    args = ["commands", "--json"] if app == "filmcraft" else ["exec", "--list", "--schemas", "--json"]
    try:
        run = subprocess.run([path, *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if run.returncode:
            return {"ok": False, "args": args, "returncode": run.returncode, "stderr": run.stderr[-4000:]}
        try:
            payload = json.loads(run.stdout)
        except json.JSONDecodeError as exc:
            return {"ok": False, "args": args, "error": f"catalog was not valid JSON: {exc}", "stdout": run.stdout[-4000:]}
        catalog = payload
        while isinstance(catalog, dict):
            nested_key = next((key for key in ("commands", "schemas", "result") if key in catalog), None)
            if nested_key:
                catalog = catalog[nested_key]
            else:
                catalog = {key: value for key, value in catalog.items() if key not in {"ok", "success", "version", "error", "description"}}
                break
        if isinstance(catalog, list):
            names = [str(row.get("name") or row.get("command") or row.get("id")) if isinstance(row, dict) else str(row) for row in catalog]
            count = len(catalog)
        elif isinstance(catalog, dict):
            names = list(map(str, catalog.keys()))
            count = len(catalog)
        else:
            names = []
            count = 0
        return {"ok": count > 0, "args": args, "command_count": count, "command_names": names[:256]}
    except Exception as exc:
        return {"ok": False, "args": args, "error": str(exc)}


def probe(app: str, path: str | None) -> dict:
    result = {"app": app, "role": APPS[app]["role"], "path": path, "available": False, "version": None}
    if not path:
        result["error"] = "CLI not found"
        return result
    try:
        run = subprocess.run([path, "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        output = (run.stdout or run.stderr).strip()
        version_ok = run.returncode == 0 and bool(output)
        catalog = _catalog_probe(app, path) if version_ok else {"ok": False, "error": "version probe failed"}
        result.update({
            "available": version_ok and catalog.get("ok", False),
            "returncode": run.returncode,
            "version": output.splitlines()[0] if output else None,
            "stdout": run.stdout[-4000:],
            "stderr": run.stderr[-4000:],
            "catalog_probe": catalog,
        })
    except Exception as exc:
        result["error"] = str(exc)
    return result


def install(app: str, state_dir: Path, force: bool = False, timeout: float = 300) -> dict:
    """Install one official CLI release under a machine-local state directory."""
    root = Path(state_dir) / "crafting-apps" / app
    existing = discover(app, state_dir)
    existing_probe = probe(app, existing) if existing else None
    if existing_probe and existing_probe.get("available") and not force:
        return {"app": app, "ok": True, "installed": False, "reused": True, "path": existing, "probe": existing_probe}
    result = {"app": app, "ok": False, "installed": False, "reused": False, "path": None}
    try:
        version = latest_version(APPS[app]["repo"])
        artifact = release_asset(app, version)
        tag = f"v{version}"
        base = f"https://github.com/{APPS[app]['repo']}/releases/download/{tag}"
        downloads = root / "downloads" / version
        archive = downloads / artifact
        checksums = downloads / "SHA256SUMS.txt"
        if force or not archive.exists():
            _download(f"{base}/{artifact}", archive, timeout)
        if force or not checksums.exists():
            _download(f"{base}/SHA256SUMS.txt", checksums, min(timeout, 120))
        expected = _expected_checksum(checksums.read_text(encoding="utf-8"), artifact)
        actual = _sha256(archive)
        if actual != expected:
            raise RuntimeError(f"Checksum mismatch for {artifact}: expected {expected}, got {actual}")

        releases = root / "releases"
        releases.mkdir(parents=True, exist_ok=True)
        final = releases / version
        # Never overwrite an installed release before the replacement is
        # extracted and verified. A content-addressed directory also lets a
        # forced reinstall of the same version coexist with its current copy.
        if final.exists():
            final = releases / f"{version}-{actual[:12]}-{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory(prefix=f".{app}-{version}-stage-", dir=str(releases)) as temp_raw:
            staged = Path(temp_raw)
            _extract(archive, staged)
            binary = _find_in_tree(staged, app)
            if not binary:
                raise RuntimeError(f"{_binary_name(app)} was not present in {artifact}")
            if platform.system() != "Windows":
                binary.chmod(binary.stat().st_mode | 0o700)
            checked = probe(app, str(binary))
            if not checked.get("available"):
                raise RuntimeError(f"Installed CLI failed its version probe: {checked.get('error') or checked.get('stderr')}")
            Path(temp_raw).replace(final)
        binary = _find_in_tree(final, app)
        if not binary:
            raise RuntimeError(f"Validated CLI disappeared after installation: {final}")
        manifest = {
            "schema_version": 1,
            "app": app,
            "repo": APPS[app]["repo"],
            "version": version,
            "artifact": artifact,
            "sha256": actual,
            "path": str(binary),
        }
        manifest_path = root / "install.json"
        temporary_manifest = root / f"install.json.{uuid.uuid4().hex}.tmp"
        temporary_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        temporary_manifest.replace(manifest_path)
        result.update({"ok": True, "installed": True, "version": version, "artifact": artifact, "sha256": actual, "path": str(binary), "probe": checked})
    except Exception as exc:
        result["error"] = str(exc)
    return result


def install_video_clis(state_dir: Path, force: bool = False) -> dict:
    results = {app: install(app, state_dir, force=force) for app in APPS}
    return {"ok": all(row.get("ok") for row in results.values()), "apps": results}


def status(state_dir: Path | None = None) -> dict:
    return {app: probe(app, discover(app, state_dir)) for app in APPS}


def run_cli(path: str, argv: list[str], timeout: float = 3600, cwd: str | None = None) -> dict:
    try:
        result = subprocess.run([path, *argv], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        parsed = None
        if result.stdout.strip():
            try:
                parsed = json.loads(result.stdout)
            except json.JSONDecodeError:
                pass
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-32000:],
            "stderr": result.stderr[-32000:],
            "json": parsed,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def payload_succeeded(payload: dict) -> bool:
    """Interpret both action payloads and the per-app status payload."""
    if "ok" in payload:
        return bool(payload["ok"])
    return bool(payload) and all(isinstance(row, dict) and row.get("available") for row in payload.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage FilmCraft and EffectCraft command-line tools")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "install"):
        p = sub.add_parser(name)
        p.add_argument("--state-dir", required=True)
        if name == "install":
            p.add_argument("--force", action="store_true")
            p.add_argument("--app", choices=[*APPS, "all"], default="all")
    run = sub.add_parser("run")
    run.add_argument("--state-dir", required=True)
    run.add_argument("--app", choices=APPS, required=True)
    run.add_argument("--timeout", type=float, default=3600)
    run.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args()
    state_dir = Path(ns.state_dir).expanduser().resolve()
    if ns.command == "status":
        payload = status(state_dir)
    elif ns.command == "install":
        payload = install_video_clis(state_dir, ns.force) if ns.app == "all" else install(ns.app, state_dir, ns.force)
    else:
        path = discover(ns.app, state_dir)
        payload = run_cli(path, ns.args[1:] if ns.args[:1] == ["--"] else ns.args, ns.timeout) if path else {"ok": False, "error": f"{APPS[ns.app]['cli']} not found"}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(0 if payload_succeeded(payload) else 2)


if __name__ == "__main__":
    main()
