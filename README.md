# Adobe Autonomous Editor Skill

A high-autonomy Agent Skill plus executable local runtime for turning **footage/assets + a natural-language brief** into finished Adobe Premiere Pro / After Effects projects and rendered deliverables.

The design target is: **the user supplies media and requirements; the agent operates the editors.** It does not promise to bypass Adobe licensing, UAC/admin consent, third-party purchases, or other external permission boundaries. Once those prerequisites exist, routine editing should require no manual timeline operation by the user.

## Architecture

The package now has four layers:

1. **Internal prerequisite skills (`skills/`)** — `skills/initialize/SKILL.md` prepares and probes the machine before editing.
2. **Root orchestration skill (`SKILL.md`)** — autonomy policy, control-surface routing, workflow selection, verification and repair loop.
3. **Workflow modules (`workflows/`)** — common editorial patterns loaded only when relevant.
4. **Executable runtime (`runtime/`)** — real Premiere RPC, After Effects action-plan RPC, Windows UI fallback, source inventory, plan execution, and render-review tooling.

## Executable control plane

```text
AI agent / runtime/execute_plan.py
        |
        +--> ws://127.0.0.1:8766  (controller)
        |           |
        |      runtime/orchestrator.py
        |           |
        |           +--> ws://127.0.0.1:8765 <-- Premiere UXP bridge
        |
        +--> runtime/ae_rpc.py --> AfterFX.exe -r generated.jsx
        |
        +--> runtime/desktop_driver.py --> UIA / keyboard / mouse / screenshots
        |
        +--> runtime/analyze_media.py --> scenes / silence / metadata
        |
        +--> runtime/transcribe.py --> local timestamped STT / SRT / VTT
        |
        +--> ffmpeg / ffprobe --> spec QC + runtime/review_packet.py

runtime/supervisor.py watches broker/Premiere health and performs bounded restarts.
```

The Premiere bridge and controller authenticate with a machine-local random secret and bind to loopback. The UXP bridge uses an explicit operation registry; it does not accept arbitrary JavaScript/eval over the socket.

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

## Windows UI / Computer-Use fallback

`runtime/desktop_driver.py` provides a deterministic lower layer for functions that Adobe APIs do not expose. It can:

- discover/focus/wait for application windows;
- dump the UI Automation accessibility tree;
- click and fill accessible controls;
- invoke native menus where exposed;
- send key sequences/hotkeys;
- click deterministic screen coordinates;
- capture full-screen or application screenshots.

A vision-capable agent can repeatedly inspect screenshots/accessibility state, issue the next action, and verify the result. This is the coverage layer for interactive-only tracking/roto/plugin dialogs/new Adobe UI features.

## Initialize skill

Every job begins with `skills/initialize/SKILL.md`, implemented by `runtime/initialize.py` and the PowerShell wrappers.

It creates/resumes the job workspace, inventories source files read-only, discovers Adobe binaries and versions, generates a machine-authenticated Premiere `.ccx` bridge, can invoke Adobe UPIA, starts the local broker, probes AE JSX, detects UIA availability, and writes:

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

`initialize_job.ps1` defaults to autonomous bootstrap when no control switches are supplied: it installs/updates the bridge when needed, starts/reuses the broker, and launches Premiere for probing. Use `-NoAuto` only for debugging/manual setup.

`setup_runtime.ps1` creates a job-local Python virtual environment and installs runtime dependencies. If first-time `.ccx` installation requires OS/Adobe permission approval, the agent should automate permitted visible UI where possible; it must not bypass UAC, Adobe licensing, or security policy.

## Plan execution

A machine-readable execution plan can mix content analysis and control surfaces in one job. Each action may also declare bounded `retries`, post-action `verify` steps, and ordered `fallbacks`, allowing automatic per-operation downgrade such as UXP → UIA:

```json
{
  "actions": [
    {"engine":"analysis","media":"D:/Footage/A001.mp4"},
    {"engine":"transcribe","media":"D:/Footage/A001.mp4","model":"large-v3"},
    {"engine":"premiere","op":"importFiles","args":{"paths":["D:/Footage/A001.mp4"]}},
    {"engine":"premiere","op":"createSequence","args":{"name":"MASTER"}},
    {"engine":"after_effects","actions":[{"op":"createComp","name":"TITLE","width":1920,"height":1080,"duration":5,"fps":30}]},
    {"engine":"desktop","steps":[{"op":"screenshot","path":"D:/EditJobs/job-001/qc/premiere.png"}]},
    {"engine":"qc","media":"D:/EditJobs/job-001/renders/final.mp4","spec":"D:/EditJobs/job-001/plans/delivery-spec.json"},
    {"engine":"review","media":"D:/EditJobs/job-001/renders/final.mp4","frames":12}
  ]
}
```

Run with `runtime/execute_plan.py`. Each stage returns structured success/error data and writes an execution report.

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
- `runtime/rpc_client.py` — controller CLI.
- `runtime/package_bridge.py` — per-machine-secret `.ccx` generator.
- `runtime/initialize.py` — executable initializer.
- `runtime/source_inventory.py` — media/project inventory.
- `runtime/analyze_media.py` — scene/silence/black/loudness planning analysis.
- `runtime/transcribe.py` — optional fully local timestamped STT + SRT/VTT.
- `runtime/ae_rpc.py` — AE action DSL → JSX compiler/dispatcher.
- `runtime/desktop_driver.py` — Windows API/UI fallback.
- `runtime/execute_plan.py` — mixed-engine execution plan runner.
- `runtime/review_packet.py` — multimodal QC evidence generator.
- `runtime/supervisor.py` — bounded broker/Premiere crash-recovery supervisor.
- `tests/selftest.py` — offline package/static self-test.

See `references/runtime-architecture.md` for the detailed data flow.

## Baseline dependencies

Recommended:

- Adobe Premiere Pro 25.6+;
- Adobe After Effects;
- Adobe Media Encoder when AME queueing is desired;
- Python 3.11+;
- ffmpeg + ffprobe;
- PowerShell on Windows.

Job-local Python dependencies are declared in `runtime/requirements.txt`. Optional local transcription is declared separately in `runtime/requirements-ml.txt` and can be installed with `scripts/setup_ml.ps1` only when a speech workflow needs it.

## Bundled vs on-demand compatibility layers

The package **bundles and tests** the modern control path: Premiere UXP RPC, After Effects JSX RPC, deterministic Windows UIA/keyboard/mouse fallback, broker/supervisor, and render QC. Legacy Premiere CEP/QE and Premiere Hybrid C++ remain **on-demand compatibility/performance layers**: the root skill may build and feature-probe them for a concrete host/version, but must never report them as available merely because they are mentioned in policy. UIA/vision is the universal fallback when no stable host API exists.

## Important boundary

No software layer can truthfully guarantee "every possible feature with zero interaction under every system state." Examples include an expired Adobe license, MFA/login challenges, UAC/admin consent, a paid third-party plugin that is not licensed, or a destructive external action requiring authorization. The skill therefore defines those as external blockers—not editing tasks.

For normal licensed/installed environments, its design goal is to keep **editorial operation itself autonomous**, using UXP/JSX first and UI/vision control for the remaining interactive surface.

## Official Adobe references

- Premiere UXP API: https://developer.adobe.com/premiere-pro/uxp/
- Premiere UXP API fundamentals: https://developer.adobe.com/premiere-pro/uxp/resources/fundamentals/apis/
- UXP manifest/permissions: https://developer.adobe.com/premiere-pro/uxp/plugins/concepts/manifest/
- UXP WebSocket/networking: https://developer.adobe.com/premiere-pro/uxp/resources/recipes/network/
- UXP plugin installation / UPIA: https://developer.adobe.com/premiere-pro/uxp/plugins/distribution/install/
- Premiere Hybrid plugins: https://developer.adobe.com/premiere-pro/uxp/plugins/hybrid-plugins/
