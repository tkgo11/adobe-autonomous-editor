# Adobe control-surface notes

## Premiere Pro

### UXP

Premiere UXP is the preferred modern automation surface. The external orchestrator should communicate with a persistent UXP plugin using a localhost WebSocket client. UXP networking requires manifest permissions, and the plugin should reconnect after Premiere restarts.

Do not assume API parity across host versions. Detect Premiere/UXP versions and feature-detect commands.

### Hybrid plugins

Premiere 26.2+ supports UXP Hybrid plugins with native C++ `.uxpaddon` modules. Use these for high-performance native work and libraries such as OpenCV. Native add-ons do not magically expose every host UI function; missing host commands may still require other control tiers.

### CEP / ExtendScript / QE

CEP has been superseded by UXP for new Premiere development. Keep a legacy adapter only for version compatibility or gaps.

`app.enableQE()` exposes the unsupported QE DOM. QE can reach operations that historically lacked official scripting hooks, but it is not a stable contract. Isolate QE calls, version-test them, and verify every result. If QE breaks in a new Premiere release, switch to UXP or UI automation rather than blocking the job.

## After Effects

### ExtendScript

After Effects scripts are `.jsx`/`.jsxbin`. On Windows, an open AE instance can receive a script using `afterfx -r <absolute-script-path>`. Generated job-specific scripts are often the simplest reliable RPC mechanism.

### Expressions

Use expressions to preserve procedural relationships and editability. Expressions operate on properties; scripts perform application/project mutations.

### Rendering

Use `aerender` for unattended deterministic rendering and small range verification renders. Prefer project checkpoints before major script batches.

## UI fallback

For Windows:

1. UI Automation / accessibility (`pywinauto` UIA, .NET UIA)
2. stable keyboard shortcuts
3. AutoHotkey for deterministic flows
4. vision-based Computer Use

Always normalize workspace/window state before UI automation and verify resulting project/render state afterward.
