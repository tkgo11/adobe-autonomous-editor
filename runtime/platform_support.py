#!/usr/bin/env python3
"""Cross-platform discovery and launch helpers for Adobe desktop hosts."""
from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
from pathlib import Path


WINDOWS_NAMES = {
    "premiere": ["Adobe Premiere Pro.exe"],
    "afterfx": ["AfterFX.exe"],
    "aerender": ["aerender.exe"],
    "media_encoder": ["Adobe Media Encoder.exe"],
}

MAC_PATTERNS = {
    "premiere": ["Adobe Premiere Pro*/Adobe Premiere Pro*.app/Contents/MacOS/Adobe Premiere Pro*"],
    "afterfx": ["Adobe After Effects*/Adobe After Effects*.app/Contents/MacOS/After Effects"],
    "aerender": ["Adobe After Effects*/aerender", "Adobe After Effects*/Adobe After Effects*.app/Contents/MacOS/aerender"],
    "media_encoder": ["Adobe Media Encoder*/Adobe Media Encoder*.app/Contents/MacOS/Adobe Media Encoder*"],
}

PATH_NAMES = {
    "premiere": ["Adobe Premiere Pro", "premiere"],
    "afterfx": ["AfterFX.exe", "afterfx", "After Effects"],
    "aerender": ["aerender", "aerender.exe"],
    "media_encoder": ["Adobe Media Encoder", "Adobe Media Encoder.exe"],
}


def find_adobe_tool(kind: str, system: str | None = None, roots: list[Path] | None = None) -> str | None:
    hits: list[Path] = []
    system = system or platform.system()
    if system == "Windows":
        roots = roots or [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Adobe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Adobe",
        ]
        for root in roots:
            if root.exists():
                for name in WINDOWS_NAMES[kind]:
                    hits.extend(root.rglob(name))
    elif system == "Darwin":
        roots = roots or [Path("/Applications"), Path.home() / "Applications"]
        for root in roots:
            if root.exists():
                for pattern in MAC_PATTERNS[kind]:
                    hits.extend(root.glob(pattern))
    # Adobe desktop hosts exist only on Windows and macOS. Do not let an
    # unrelated Linux executable named "premiere" or "afterfx" masquerade as
    # an installed Adobe application.
    if system in {"Windows", "Darwin"}:
        for name in PATH_NAMES[kind]:
            path = shutil.which(name)
            if path:
                hits.append(Path(path))
    files = [path.resolve() for path in hits if path.is_file() and os.access(path, os.X_OK)]
    return str(sorted(files, key=lambda path: str(path), reverse=True)[0]) if files else None


def app_bundle(executable: str | Path) -> Path | None:
    path = Path(executable).resolve()
    for parent in (path, *path.parents):
        if parent.suffix.lower() == ".app":
            return parent
    return None


def product_version(executable: str | None, system: str | None = None) -> str | None:
    if not executable:
        return None
    system = system or platform.system()
    if system == "Darwin":
        bundle = app_bundle(executable)
        info = bundle / "Contents/Info.plist" if bundle else None
        if info and info.is_file():
            try:
                payload = plistlib.loads(info.read_bytes())
                return str(payload.get("CFBundleShortVersionString") or payload.get("CFBundleVersion") or "") or None
            except Exception:
                pass
    if system == "Windows":
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps:
            escaped = executable.replace("'", "''")
            command = f"(Get-Item -LiteralPath '{escaped}').VersionInfo.ProductVersion"
            run = subprocess.run([ps, "-NoProfile", "-Command", command], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            if run.returncode == 0 and run.stdout.strip():
                return run.stdout.strip()
    return None


def find_upia(system: str | None = None, base: Path | None = None) -> str | None:
    system = system or platform.system()
    if system == "Windows":
        candidate = Path(os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files")) / (
            "Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/"
            "UnifiedPluginInstallerAgent.exe"
        )
        return str(candidate) if candidate.exists() else None
    if system == "Darwin":
        base = base or Path("/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI")
        candidates = [
            base / "UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent",
            base / "UnifiedPluginInstallerAgent.app/Contents/MacOS/UnifiedPluginInstallerAgent",
        ]
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        if base.exists():
            hits = sorted(base.rglob("UnifiedPluginInstallerAgent"))
            for hit in hits:
                if hit.is_file() and os.access(hit, os.X_OK):
                    return str(hit)
    return None


def upia_install_command(upia: str, ccx: str | Path, system: str | None = None) -> list[str]:
    switch = "--install" if (system or platform.system()) == "Darwin" else "/install"
    return [upia, switch, str(ccx)]


def launch_application(executable: str) -> subprocess.Popen:
    if platform.system() == "Darwin":
        bundle = app_bundle(executable)
        if bundle and shutil.which("open"):
            return subprocess.Popen(["open", str(bundle)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.Popen([executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def desktop_probe() -> dict:
    system = platform.system()
    if system == "Windows":
        try:
            import pywinauto, pyautogui  # noqa: F401
            return {"available": True, "backend": "windows-uia", "pywinauto": getattr(pywinauto, "__version__", None)}
        except Exception as exc:
            return {"available": False, "backend": "windows-uia", "error": str(exc)}
    if system == "Darwin":
        osascript = shutil.which("osascript")
        screencapture = shutil.which("screencapture") or "/usr/sbin/screencapture"
        if not osascript or not Path(screencapture).exists():
            return {"available": False, "backend": "macos-accessibility", "error": "osascript or screencapture not found"}
        try:
            run = subprocess.run(
                [osascript, "-e", 'tell application "System Events" to get UI elements enabled'],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            )
            enabled = run.returncode == 0 and run.stdout.strip().lower() == "true"
            return {
                "available": enabled, "backend": "macos-accessibility",
                "accessibility_permission": enabled,
                "screen_recording_permission": "unverified_until_capture",
                "error": None if enabled else (run.stderr.strip() or "Accessibility permission is not enabled"),
            }
        except Exception as exc:
            return {"available": False, "backend": "macos-accessibility", "error": str(exc)}
    return {"available": False, "backend": None, "reason": "Adobe desktop applications are unavailable on this platform"}
