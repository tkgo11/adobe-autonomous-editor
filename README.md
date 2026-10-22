# Autonomous Video Editor Skill

A high-autonomy Agent Skill plus executable local runtime for turning **footage/assets + a natural-language brief** into finished video projects and rendered deliverables. It uses the video-related [Crafting Apps](https://getartcraft.com/apps) CLIs first—FilmCraft for editing and EffectCraft for motion/VFX—then uses Adobe Premiere Pro or After Effects only when the required feature is unavailable or fails verification.

The design target is: **the user supplies media and requirements; the agent operates the editors.** It does not promise to bypass licensing, UAC/admin consent, third-party purchases, or other external permission boundaries. Routine editing should require no manual timeline operation by the user.

## Quick install

This repository is itself the installable skill directory. Install the **whole repository**; do not copy only `SKILL.md`, because the skill uses the bundled `runtime/`, `scripts/`, `workflows/`, `templates/`, schemas, references, and internal initialize skill.

```powershell
$installer = Join-Path $env:TEMP "install-adobe-autonomous-editor.ps1"
Invoke-WebRequest "https://raw.githubusercontent.com/tkgo11/adobe-autonomous-editor/main/install.ps1" -OutFile $installer
& $installer
```

The default destination is:

```text
%USERPROFILE%\.agents\skills\adobe-autonomous-editor\
```

Restart Codex (or start a fresh session), then invoke:

```text
$adobe-autonomous-editor
```

On macOS or Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/tkgo11/adobe-autonomous-editor/main/install.sh -o /tmp/install-adobe-autonomous-editor.sh
bash /tmp/install-adobe-autonomous-editor.sh
```

You only need to provide the footage/assets and the result you want. The skill bootstraps its isolated Python environment, Python packages, ffmpeg/ffprobe, optional local transcription stack, and the official FilmCraft/EffectCraft command-line releases. It discovers installed Adobe fallbacks and activates an Adobe control surface only when needed.

Example:

```text
$adobe-autonomous-editor Use D:\Footage\shoot to create a polished 60-second vertical product video. Use Crafting Apps first and Adobe only as fallback.
```

## Editor policy and CLI setup

The default policy is `crafting-first`. Only FilmCraft and EffectCraft are included; the other Crafting Apps are intentionally out of scope for video editing. `runtime/bootstrap.py` creates the isolated runtime and delegates to `runtime/initialize.py --auto`, which reuses machine-local installs and downloads missing official release archives from `storytold/filmcraft` and `storytold/effectcraft`. Every Crafting Apps archive must match its release's `SHA256SUMS.txt` before extraction.

To inspect or install the CLIs directly:

```powershell
python runtime\crafting_apps.py status --state-dir "$env:USERPROFILE\.adobe-autonomous-editor"
python runtime\crafting_apps.py install --state-dir "$env:USERPROFILE\.adobe-autonomous-editor"
```

To retain the old Adobe-only behavior for a specific job, initialize it with `--editor-priority adobe-only` or pass `-EditorPriority adobe-only` to `scripts/initialize_job.ps1`.

For project-only installation, manual Git installation, updates, uninstalling, verification, macOS/Linux skill discovery, and troubleshooting, see **[INSTALL.md](INSTALL.md)**.

The package also includes `agents/openai.yaml`, so Codex can show a human-friendly skill name, description, and default invocation prompt.

## Architecture

The package now has four layers:

1. **Internal prerequisite skills (`skills/`)** — `skills/initialize/SKILL.md` installs/probes FilmCraft and EffectCraft first, then prepares Adobe fallbacks.
2. **Root orchestration skill (`SKILL.md`)** — Crafting Apps-first routing, workflow selection, verification and repair loop.
3. **Workflow modules (`workflows/`)** — common editorial patterns loaded only when relevant.
4. **Executable runtime (`runtime/`)** — real Premiere RPC, After Effects action-plan RPC, Windows UIA/macOS Accessibility fallback, source inventory, plan execution, and render-review tooling.

## Executable control plane

```text
AI agent / runtime/execute_plan.py
        |
        +--> filmcraft-cli --> .fcproj / editorial render
        |
        +--> effectcraft-cli --> .ecproj / motion-VFX render
        |
        +--> ws://127.0.0.1:8766  (controller)
        |           |
        |      runtime/orchestrator.py
        |           |
        |           +--> ws://127.0.0.1:8765 <-- Premiere UXP bridge
        |
        +--> runtime/ae_rpc.py --> After Effects -r generated.jsx
        |
        +--> runtime/desktop_driver.py --> Windows UIA or macOS Accessibility / input / screenshots
        |
        +--> runtime/analyze_media.py --> scenes / silence / metadata
        |
        +--> runtime/transcribe.py --> local timestamped STT / SRT / VTT
        |
        +--> ffmpeg / ffprobe --> spec QC + runtime/review_packet.py

runtime/supervisor.py watches broker/Premiere health and performs bounded restarts.
```

The Premiere bridge and controller authenticate with a machine-local random secret and bind to loopback. The UXP bridge is an Adobe fallback and uses an explicit operation registry; it does not accept arbitrary JavaScript/eval over the socket.

## Premiere runtime coverage

`templates/premiere-uxp/index.js` is no longer a two-command starter. It includes handlers for:

- project create/open/save/save-as and state inspection;
- recursive project-item inventory, rename/label/move/remove;
- media import and bin creation;
- proxy attach, media relink/refresh, and subclip creation where the host exposes it;
- Premiere Transcript API start/export/import/language discovery, with local STT fallback;
- sequence creation/from-media/open/activation/delete/close;
- sequence settings inspection, render-quality controls, and track rename;
- complete basic timeline inspection;
- insert/overwrite edits;
- clip in/out/start/end/move/disable/rename;
- audio/video track mute;
- sequence in/out and playhead;
- sequence markers;
- video/audio effect discovery and application;
- component/effect parameter inspection;
- static parameter values and keyframes;
- video transitions;
- MOGRT insertion;
- After Effects comp import/Dynamic Link entry points exposed by Premiere;
- frame export;
- Premiere/AME sequence export;
- OTIO/FCPXML/AAF export where the installed Premiere version exposes it.

Missing host API functionality is a **routing signal**: the skill drops to UI Automation/vision rather than declaring the UI feature impossible.

## After Effects runtime coverage

`runtime/ae_rpc.py` compiles a JSON action plan into explicit ExtendScript. Bundled operations include:

- new/open/save projects;
- file import and folders;
- comps;
- footage/text/solid/null/shape/camera/light layers;
- layer timing and transforms;
- arbitrary property paths plus generic property-group add/remove/duplicate/reorder (useful for shape contents, text animators and other extensible groups);
- expressions;
- keyframes, removal, temporal interpolation/easing, and spatial tangents;
- layer switches, blending mode, layer ordering/source replacement, track mattes, and time remapping;
- text-document styling controls;
- masks, mask paths and mask properties;
- comp work-area/core property controls;
- markers;
- effects and effect parameters;
- parenting, duplicate/remove, precompose;
- render queue/output module setup, templates/settings, render ranges, and render;
- named/ID menu-command execution for scriptable menu fallbacks.

For uncommon AE scripting capabilities not yet represented in the action DSL, the root skill may generate a one-off reviewed JSX script, execute it through the same dispatcher, and validate the resulting render/state. API-independent UI operations remain available through the desktop fallback.

## Desktop UI / Computer-Use fallback

`runtime/desktop_driver.py` provides a deterministic lower layer for functions that Adobe APIs do not expose. It uses Windows UI Automation on Windows and System Events Accessibility plus CoreGraphics input on macOS. It can:

- discover/focus/wait for application windows;
- dump the UI Automation accessibility tree;
- click and fill accessible controls;
- invoke native menus where exposed;
- send key sequences/hotkeys;
- click deterministic screen coordinates;
- capture full-screen or application screenshots.

A vision-capable agent can repeatedly inspect screenshots/accessibility state, issue the next action, and verify the result. This is the coverage layer for interactive-only tracking/roto/plugin dialogs/new Adobe UI features.

## Initialize skill

Every job begins with `skills/initialize/SKILL.md`, implemented by the standard-library `runtime/bootstrap.py`, `runtime/initialize.py`, and the PowerShell/Bash wrappers.

It creates/resumes the job workspace, inventories source files read-only, installs/probes the FilmCraft and EffectCraft CLIs, discovers Adobe binaries and versions, generates a machine-authenticated Premiere `.ccx` bridge, can invoke Adobe UPIA, starts the local broker, probes AE JSX, detects platform desktop-accessibility availability, and writes:

- `analysis/environment.json`
- `analysis/source_inventory.json`
- `plans/capability_matrix.json`
- `plans/init_state.json`

The machine bridge secret is stored under the local user profile and reused across jobs, avoiding a new plugin installation for every edit.

## Typical unattended bootstrap on Windows

```powershell
./scripts/initialize_job.ps1 `
  -JobRoot "D:\EditJobs\job-001" `
  -SkillRoot "D:\skills\adobe-autonomous-editor" `
  -Source "D:\Footage\shoot" `
  -Brief "Create a polished 60-second vertical product video"
```

`initialize_job.ps1` defaults to autonomous bootstrap when no control switches are supplied. Crafting-first jobs defer Premiere activation until a selected fallback needs it. Adobe-only jobs set up the Premiere bridge and broker only when Premiere Pro is installed, and can still probe After Effects when Premiere Pro is absent. Use `-NoAuto` only for debugging/manual setup.

`initialize_job.ps1` provisions a compatible per-job Python base on Windows when none is installed, then `runtime/bootstrap.py` creates a job-local virtual environment and installs the declared runtime dependencies. Initialization also installs a machine-local ffmpeg/ffprobe bundle when the tools are absent. A transcription action installs its optional ML stack on first use. If first-time `.ccx` installation requires OS/Adobe permission approval, the agent should automate permitted visible UI where possible; it must not bypass UAC, Adobe licensing, or security policy.

The equivalent macOS/Linux entry point is:

```bash
./scripts/initialize_job.sh \
  --job-root "$HOME/EditJobs/job-001" \
  --skill-root "$HOME/.agents/skills/adobe-autonomous-editor" \
  --source "$HOME/Footage/shoot" \
  --brief "Create a polished 60-second vertical product video"
```

When Python 3.10+ is absent, `provision_python.sh` downloads a platform-native `uv` release, verifies its published SHA-256 sidecar, and installs an isolated Python 3.12 runtime under the job. No system package-manager or administrator access is required.

## Plan execution

A machine-readable execution plan can mix content analysis and control surfaces in one job. Each action may also declare bounded `retries`, post-action `verify` steps, and ordered `fallbacks`, allowing automatic per-operation downgrade such as UXP → platform desktop accessibility:

```json
{
  "editorPolicy": "crafting-first",
  "actions": [
    {"engine":"analysis","media":"D:/Footage/A001.mp4"},
    {"engine":"transcribe","media":"D:/Footage/A001.mp4","model":"large-v3"},
    {"engine":"filmcraft","argv":["--project","D:/EditJobs/job-001/projects/filmcraft/master.fcproj","--save","import","D:/Footage/A001.mp4"],"fallbacks":[{"engine":"premiere","op":"importFiles","args":{"paths":["D:/Footage/A001.mp4"]}}]},
    {"engine":"effectcraft","argv":["exec","comp.new","--params","{\"name\":\"TITLE\",\"width\":1920,\"height\":1080,\"duration\":5,\"frameRate\":30}","--empty","--save-as","D:/EditJobs/job-001/projects/effectcraft/title.ecproj"],"fallbacks":[{"engine":"after_effects","actions":[{"op":"createComp","name":"TITLE","width":1920,"height":1080,"duration":5,"fps":30}]}]},
    {"engine":"desktop","steps":[{"op":"screenshot","path":"D:/EditJobs/job-001/qc/premiere.png"}]},
    {"engine":"qc","media":"D:/EditJobs/job-001/renders/final.mp4","spec":"D:/EditJobs/job-001/plans/delivery-spec.json"},
    {"engine":"review","media":"D:/EditJobs/job-001/renders/final.mp4","frames":12}
  ]
}
```

Run follow-on commands through `scripts/run_runtime.ps1` on Windows or `scripts/run_runtime.sh` on macOS/Linux. These launch the requested tool with the job's virtual environment, which contains the dependencies installed during initialization. For example:

```powershell
./scripts/run_runtime.ps1 -JobRoot "D:\EditJobs\job-001" -SkillRoot "D:\skills\adobe-autonomous-editor" -Command execute_plan -Arguments @("D:\EditJobs\job-001\plans\plan.json", "--job-root", "D:\EditJobs\job-001", "--skill-root", "D:\skills\adobe-autonomous-editor")
```

```bash
./scripts/run_runtime.sh "$HOME/EditJobs/job-001" "$HOME/.agents/skills/adobe-autonomous-editor" execute_plan "$HOME/EditJobs/job-001/plans/plan.json" --job-root "$HOME/EditJobs/job-001" --skill-root "$HOME/.agents/skills/adobe-autonomous-editor"
```

The same wrappers support `analyze_media`, `transcribe`, `review_packet`, `qc`, and other listed runtime commands. They pass the trusted job root so those tools can restore only hash-verified ffmpeg/ffprobe from the private machine cache; media and output folders are never searched for executable paths. When invoking analysis, review-packet, or QC directly instead of through a wrapper, pass `--environment <job>/analysis/environment.json`. Each stage returns structured success/error data and writes an execution report. If a Crafting Apps action fails and selects a Premiere fallback that was not active during initialization, the executor installs/reuses the packaged bridge, starts the broker, launches Premiere, probes connectivity, and retries the Adobe operation automatically.

## Render verification

Rendered output is the source of truth.

- `scripts/qc.py` verifies decode integrity, streams, resolution, FPS, duration, codecs/audio properties, black/freeze/silence policies, EBU R128 loudness and true peak against an optional delivery-spec JSON.
- `runtime/review_packet.py` generates representative frames, a contact sheet and waveform image for multimodal inspection.
- `runtime/supervisor.py` performs bounded broker restart and Premiere relaunch recovery without bypassing OS/Adobe security boundaries.
- The root skill compares the rendered evidence against both universal requirements and workflow-specific QC gates, then repairs and rerenders automatically.

## Workflow modules

Primary modules:

- `talking-head.md`
- `short-form-vertical.md`
- `youtube-longform.md`
- `interview-podcast.md`
- `tutorial-screencast.md`
- `event-highlight.md`
- `commercial-product-ad.md`
- `repurpose-master-to-social.md`

Composable overlays:

- `captions-localization.md`
- `multicam-sync.md`

`workflows/manifest.json` and `workflows/workflow-contract.md` define module composition.

## Runtime files

- `runtime/orchestrator.py` — authenticated loopback broker.
- `runtime/crafting_apps.py` — verified FilmCraft/EffectCraft CLI installer, discovery, probe, and runner.
- `runtime/bootstrap.py` — standard-library isolated Python dependency bootstrap.
- `scripts/run_runtime.ps1` / `scripts/run_runtime.sh` — run subsequent commands using the job virtual environment.
- `runtime/toolchain.py` — machine-local ffmpeg/ffprobe bootstrap and path restoration.
- `runtime/rpc_client.py` — controller CLI.
- `runtime/package_bridge.py` — per-machine-secret `.ccx` generator.
- `runtime/initialize.py` — executable initializer.
- `runtime/source_inventory.py` — media/project inventory.
- `runtime/analyze_media.py` — scene/silence/black/loudness planning analysis.
- `runtime/transcribe.py` — optional fully local timestamped STT + SRT/VTT.
- `runtime/ae_rpc.py` — AE action DSL → JSX compiler/dispatcher.
- `runtime/platform_support.py` — Windows/macOS Adobe discovery, versioning, UPIA, and app launching.
- `runtime/desktop_driver.py` — Windows UIA and macOS Accessibility/UI fallback.
- `runtime/execute_plan.py` — mixed-engine execution plan runner.
- `runtime/review_packet.py` — multimodal QC evidence generator.
- `runtime/supervisor.py` — bounded broker/Premiere crash-recovery supervisor.
- `tests/selftest.py` — offline package/static self-test.

See `references/runtime-architecture.md` for the detailed data flow.

## Baseline dependencies

User-provided applications:

- Adobe Premiere Pro 25.6+;
- Adobe After Effects;
- Adobe Media Encoder when AME queueing is desired;
- Windows PowerShell on Windows, or a POSIX shell plus `curl`/`wget` and `tar` on macOS/Linux.

Python, job-local packages, ffmpeg/ffprobe, FilmCraft, EffectCraft, and optional transcription dependencies are provisioned by the skill and do not require a separate user installation. Base dependencies are declared in `runtime/requirements.txt`; optional local transcription is declared in `runtime/requirements-ml.txt` and is installed automatically on first use.

## Bundled vs on-demand compatibility layers

The package **bundles and tests** the modern control path: Premiere UXP RPC, After Effects JSX RPC, deterministic Windows UIA or macOS Accessibility/input fallback, broker/supervisor, and render QC. Linux supports the complete Crafting Apps/media pipeline, but not Adobe fallback because Adobe does not distribute Premiere Pro or After Effects for Linux. Legacy Premiere CEP/QE and Premiere Hybrid C++ remain **on-demand compatibility/performance layers** and must be feature-probed before use.

## Important boundary

No software layer can truthfully guarantee "every possible feature with zero interaction under every system state." The bootstrap also needs outbound access to its official package/release hosts and permission to create and execute files in the job/user state directories. Other irreducible examples include an expired Adobe license, MFA/login challenges, UAC/AppLocker or macOS privacy consent, a paid third-party plugin that is not licensed, or a destructive external action requiring authorization. The skill defines those as external blockers—not user setup tasks.

For normal licensed/installed environments, its design goal is to keep **editorial operation itself autonomous**, using UXP/JSX first and UI/vision control for the remaining interactive surface.

## Official Adobe references

- Premiere UXP API: https://developer.adobe.com/premiere-pro/uxp/
- Premiere UXP API fundamentals: https://developer.adobe.com/premiere-pro/uxp/resources/fundamentals/apis/
- UXP manifest/permissions: https://developer.adobe.com/premiere-pro/uxp/plugins/concepts/manifest/
- UXP WebSocket/networking: https://developer.adobe.com/premiere-pro/uxp/resources/recipes/network/
- UXP plugin installation / UPIA: https://developer.adobe.com/premiere-pro/uxp/plugins/distribution/install/
- Premiere Hybrid plugins: https://developer.adobe.com/premiere-pro/uxp/plugins/hybrid-plugins/
