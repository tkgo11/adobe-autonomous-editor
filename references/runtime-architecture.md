# Executable runtime architecture

The skill ships an executable control plane in addition to agent instructions.

The editor route is Crafting Apps first: `filmcraft-cli` owns nonlinear editorial work and `effectcraft-cli` owns motion/VFX work. Premiere Pro and After Effects remain per-operation fallbacks when a required command is unavailable, fails, or cannot be verified.

## Data plane

```text
AI agent / execute_plan.py
        |
        +--> filmcraft-cli --> FilmCraft project/render
        |
        +--> effectcraft-cli --> EffectCraft project/render
        |
        +--> controller WebSocket :8766
        |         |
        |     orchestrator.py
        |         |
        |         +--> Premiere WebSocket :8765 <-- installed UXP bridge
        |
        +--> ae_rpc.py --> generated explicit JSX --> After Effects executable -r
        |
        +--> desktop_driver.py --> Windows UIA or macOS Accessibility / input / screenshots
        |
        +--> analyze_media.py --> scene/silence/metadata analysis
        |
        +--> transcribe.py --> local timestamped STT / SRT / VTT
        |
        +--> ffmpeg/ffprobe --> delivery-spec QC + review_packet.py

supervisor.py --> bounded broker restart / Premiere relaunch recovery
```

Both controller and Premiere bridge authenticate to the loopback broker using a machine-local random secret. The UXP bridge accepts only registered operations and never evaluates arbitrary code received over the socket.

## Premiere bridge

The bundled UXP bridge provides explicit handlers for project open/create/save, project state, recursive project items, import, bins, sequence creation, timeline inspection, insert/overwrite, trim/move/disable/rename, track mute, markers, sequence range/playhead, video/audio effects, effect parameters and keyframes, video transitions, MOGRT insertion, After Effects comp import, still-frame export, sequence export/AME, and supported timeline interchange exports.

New Premiere APIs should be added as explicit handlers and self-tested against the installed version. If a host function is absent, route to the platform desktop-accessibility layer rather than inventing method names.

## After Effects RPC

`runtime/ae_rpc.py` compiles a JSON action plan into a bounded ExtendScript program. It covers common project/comp/layer/effect/property/keyframe/expression/render-queue operations and can execute a named/ID menu command when scripting has no higher-level method.

For a rare operation that is scriptable but missing from the DSL, the root agent may generate a one-off reviewed JSX file. The generic network endpoints must not accept arbitrary JSX/eval.

## UI fallback

`runtime/desktop_driver.py` is deliberately low-level. It uses UIA on Windows and System Events Accessibility/CoreGraphics on macOS to dump accessibility state, focus/wait for windows, click/set accessible controls, select native menus, send keyboard/hotkey input, use deterministic coordinates, and capture screenshots. A vision-capable parent agent uses those observations to operate features not exposed through scripting. Linux uses the Crafting Apps path because Adobe desktop applications are not distributed for Linux.

## Installation boundary

The initializer can generate a `.ccx` and invoke Adobe UPIA. Adobe/OS policy may still require elevation or permission consent during first install. The agent should automate visible dialogs when allowed, but must not bypass UAC, licensing, or security policy. Once installed, the machine-local secret is reused so normal jobs do not require reinstalling the bridge.

## Compatibility layers

The packaged executable baseline is FilmCraft CLI + EffectCraft CLI + Premiere UXP RPC + After Effects JSX RPC + Windows UIA or macOS Accessibility/keyboard/mouse + deterministic render QC. Legacy Premiere CEP/QE and UXP Hybrid C++ are intentionally on-demand: they are generated/attached only for an installed version and must be feature-probed before use.

## Failure semantics

`bootstrap.py` creates the isolated job runtime, while `toolchain.py` provides a machine-local ffmpeg/ffprobe pair when the system has none. `execute_plan.py` supports FilmCraft and EffectCraft CLI actions, bounded retries, explicit verification actions, and ordered fallbacks for each operation. A FilmCraft mutation can therefore be independently queried and, if unsupported or unverifiable, downgraded to Premiere, AE, or desktop/UI without abandoning the rest of the job. When a Premiere fallback is first selected, the executor activates the packaged bridge, broker, and host on demand before retrying the operation. `crafting_apps.py` discovers installed CLIs or installs official checksum-verified releases under machine-local state. Transcription dependencies are installed lazily by the execution engine.
