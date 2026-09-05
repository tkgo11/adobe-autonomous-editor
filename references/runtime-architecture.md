# Executable runtime architecture

The skill ships an executable control plane in addition to agent instructions.

## Data plane

```text
AI agent / execute_plan.py
        |
        +--> controller WebSocket :8766
        |         |
        |     orchestrator.py
        |         |
        |         +--> Premiere WebSocket :8765 <-- installed UXP bridge
        |
        +--> ae_rpc.py --> generated explicit JSX --> AfterFX.exe -r
        |
        +--> desktop_driver.py --> Windows UI Automation / keyboard / mouse / screenshots
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

New Premiere APIs should be added as explicit handlers and self-tested against the installed version. If a host function is absent, route to UIA rather than inventing method names.

## After Effects RPC

`runtime/ae_rpc.py` compiles a JSON action plan into a bounded ExtendScript program. It covers common project/comp/layer/effect/property/keyframe/expression/render-queue operations and can execute a named/ID menu command when scripting has no higher-level method.

For a rare operation that is scriptable but missing from the DSL, the root agent may generate a one-off reviewed JSX file. The generic network endpoints must not accept arbitrary JSX/eval.

## UI fallback

`runtime/desktop_driver.py` is deliberately low-level. It can dump the UI Automation tree, focus/wait for windows, click/set accessible controls, select native menus, send keyboard/hotkey input, use deterministic coordinates, and capture screenshots. A vision-capable parent agent uses those observations to operate features not exposed through scripting.

## Installation boundary

The initializer can generate a `.ccx` and invoke Adobe UPIA. Adobe/OS policy may still require elevation or permission consent during first install. The agent should automate visible dialogs when allowed, but must not bypass UAC, licensing, or security policy. Once installed, the machine-local secret is reused so normal jobs do not require reinstalling the bridge.

## Compatibility layers

The packaged executable baseline is Premiere UXP RPC + After Effects JSX RPC + Windows UIA/keyboard/mouse + deterministic render QC. Legacy Premiere CEP/QE and UXP Hybrid C++ are intentionally on-demand: they are generated/attached only for an installed version and must be feature-probed before use. This avoids claiming unsupported private APIs while retaining an escape hatch for version-specific compatibility or native-performance workloads.

## Failure semantics

`execute_plan.py` supports bounded retries, explicit verification actions, and ordered fallbacks for each operation. A Premiere UXP mutation can therefore be independently queried and, if unsupported or unverifiable, downgraded to an AE or desktop/UI action without abandoning the rest of the job.
