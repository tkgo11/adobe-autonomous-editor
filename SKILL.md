---
name: adobe-autonomous-editor
description: Fully autonomous AI video-editing director and execution skill for Adobe Premiere Pro and After Effects. Use when the user supplies footage/assets plus creative requirements and expects a finished edit with no manual timeline work. The agent must plan, edit, create motion graphics/VFX, mix audio, caption, color, render, inspect the output, repair defects, and deliver final exports plus editable Adobe projects. Prefer programmable control, but escalate through every available control surface—including Premiere UXP/Hybrid plugins, After Effects ExtendScript/expressions, Adobe rendering interfaces, legacy Premiere scripting/QE when unavoidable, OS accessibility automation, keyboard/mouse automation, and computer-use vision—rather than declaring a requested edit impossible merely because a high-level API lacks a method.
---

# Adobe Autonomous Editor

## Mission

Turn **footage/assets + a natural-language brief** into a finished, editable Adobe Premiere Pro / After Effects production with minimal or zero user intervention.

The user is the client, not the operator. Do not ask the user to perform timeline edits, click menus, install routine dependencies manually, choose codecs, select tracks, create compositions, tune effect values, troubleshoot panels, or review intermediate technical states unless an external permission/license/credential decision truly cannot be made safely without them.

**The default behavior is to execute, inspect, fix, and finish—not to stop at advice or a plan.**

## Autonomy contract

Given:

1. one or more footage / audio / image / project / asset paths; and
2. a creative or technical requirement,

the agent shall autonomously:

1. invoke the mandatory internal initializer at `skills/initialize/SKILL.md`;
2. inventory/fingerprint sources and establish tested Adobe/tool capabilities through that initializer;
3. infer delivery format when not specified;
4. analyze dialogue, scenes, subjects, motion, shot quality, music, graphics needs, continuity, pacing, and technical defects;
5. translate the brief into an explicit edit specification;
6. choose the most reliable tested control surface for each operation;
7. create or update Premiere and After Effects projects;
8. render previews as needed;
9. inspect visual and audio results;
10. diagnose mismatches or defects;
11. repair them automatically;
12. export final deliverables;
13. preserve editable project files and a machine-readable execution report.

Do not treat a successful API call as proof of a successful edit. **Rendered output is the source of truth.**

---

# 0. Internal skill lifecycle

The root skill orchestrates internal sub-skills declared in `skills/manifest.json`.

## 0.1 Mandatory initialize skill

Before workflow routing, creative analysis, Premiere timeline mutation, or After Effects production work, **load and execute `skills/initialize/SKILL.md`**.

The initialize skill owns:

- job workspace creation/resume;
- non-destructive source inventory and technical fingerprinting;
- OS/hardware/tool discovery;
- Premiere/After Effects/AME binary and version discovery;
- Premiere UXP/bridge/legacy/UI fallback probing;
- After Effects JSX/`aerender` probing;
- routine dependency preparation;
- disposable self-tests;
- `plans/capability_matrix.json`;
- `plans/init_state.json`;
- readiness status: `READY`, `DEGRADED`, or `BLOCKED`.

Do not duplicate that preflight logic in the root skill. The root consumes the initializer's outputs.

Proceed on `READY` or `DEGRADED`. On `DEGRADED`, use the tested fallback paths recorded by the initializer. Stop only on a truthful `BLOCKED` state.

## 0.2 Targeted re-initialization

Reinvoke `skills/initialize/SKILL.md` in targeted refresh mode when Adobe restarts/updates, a bridge repeatedly disconnects, a capability probe proves wrong, a previously untested control surface becomes necessary, the machine/environment changes, or a crashed job is resumed.

A refresh should preserve creative/job state and retest only stale or affected capabilities when possible.

## 0.3 Bundled executable runtime

This skill ships a real local control plane under `runtime/`; do not treat the skill as prompt-only documentation. Prefer these implementations before inventing new adapters:

- `runtime/initialize.py` — executable preflight and capability state writer.
- `runtime/orchestrator.py` — authenticated loopback broker. Premiere UXP connects as a WebSocket client on port 8765; controllers connect on 8766.
- `runtime/rpc_client.py` — direct Premiere RPC client.
- `templates/premiere-uxp/` — installable UXP bridge with explicit handlers for project, sequence, timeline, effects, transitions, MOGRT, AE-comp import and export operations.
- `runtime/ae_rpc.py` — explicit AE action-plan compiler/dispatcher using generated JSX and `AfterFX.exe -r`.
- `runtime/desktop_driver.py` — Windows UI Automation + keyboard/mouse + screenshot fallback.
- `runtime/analyze_media.py` — deterministic scene/silence/metadata analysis for edit planning.
- `runtime/transcribe.py` — optional local timestamped STT producing JSON/SRT/VTT.
- `runtime/execute_plan.py` — mixed-engine action-plan executor with bounded retries, verification actions, and ordered per-operation fallbacks.
- `runtime/review_packet.py` — representative rendered frames/contact sheet/waveform for multimodal review.
- `runtime/supervisor.py` — bounded broker/Premiere health recovery; use during long unattended jobs.
- `scripts/qc.py` — delivery-spec-aware deterministic render QC.

The bridge secret is machine-local and reusable across jobs. The network bridge must remain loopback-only. Never expose arbitrary `eval`/JSX execution over the socket.

When the bundled command registry lacks a newly exposed Adobe operation, add the smallest explicit handler, self-test it, then cache it. When Adobe exposes no programmable operation, fall through to UIA/vision rather than pretending an API exists.

Bundled executable coverage is **UXP + AE JSX + UIA/keyboard/mouse + render/QC**. CEP/QE and Hybrid C++ are compatibility/performance tiers generated or attached only when a concrete job requires them. Do not mark those tiers available until an installed-host feature probe succeeds.

---

# 1. Non-negotiable operating rules

## 1.1 User interaction budget

Assume the user will provide only footage/assets and requirements.

Do not ask preference questions that can be inferred reasonably. Make professional defaults and record them in the execution report.

Only interrupt for a blocking decision involving one of these categories:

- required login/credential that is unavailable;
- purchase/license approval;
- explicit permission to upload private footage to an external cloud service when the user has not already allowed it;
- irreversible destructive operation outside the isolated project workspace;
- an ambiguity where two materially different final deliverables are equally plausible and cannot both be produced reasonably.

Otherwise choose a sensible default and continue.

## 1.2 Never destructively experiment on the only copy

- Work in a dedicated job directory.
- Copy or duplicate project files before risky changes.
- Version sequences/comps before structural rewrites.
- Prefer non-destructive Adobe effects, adjustment layers, nests, precomps, masks, and keyframes.
- Never directly hex-edit or reverse-engineer `.prproj`/`.aep` project files as the primary automation path.
- Preserve source media untouched.

## 1.3 API limitations are routing signals, not stopping conditions

If a requested operation is not exposed by the current API:

1. try another supported Adobe API/control surface;
2. try an Adobe scripting path;
3. try a documented/known legacy scripting path when compatibility warrants it;
4. try OS accessibility/UI Automation;
5. try keyboard/mouse automation using deterministic coordinates anchored by detected UI elements;
6. use vision-based Computer Use as the last resort;
7. verify the result visually and retry if necessary.

Do not respond “not possible through the API” when the UI itself can perform the operation.

## 1.4 Verification is mandatory

After every major edit phase, verify state using at least one independent mechanism:

- query Adobe DOM/project state;
- inspect exported XML/metadata where appropriate;
- render a low-resolution preview and inspect frames;
- inspect waveform/loudness/silence;
- compare requirement checklist to produced timeline;
- use multimodal visual review of representative frames or short rendered segments.

For UI fallbacks, verification is mandatory after **every** operation batch.

---

# 2. Control-surface hierarchy

Use the highest reliable layer that can perform the task. Mix layers inside one job.

## Tier A — External analysis and deterministic media tooling

Use shell/Python plus media tools before touching the GUI when they improve reliability.

Preferred capabilities:

- `ffprobe`: codec, duration, streams, FPS, color metadata, timebase, sample rate.
- `ffmpeg`: proxy creation, mezzanine transcodes, waveform extraction, contact sheets, loudness analysis, black/freeze/silence detection, preview generation, frame extraction.
- local speech-to-text such as Whisper/WhisperX when available.
- local visual models / OpenCV for shot boundaries, face/subject tracking, blur/shake/exposure heuristics, duplicate detection, motion metrics.
- OCR for signs, slides, captions, lower thirds, screens.
- local embeddings for semantic clip search.

Prefer local processing for private footage. Do not upload raw media to an external service unless the user's requirements or standing permission allow it.

## Tier B — Premiere Pro UXP DOM (primary Premiere control)

For Premiere 25.6+ prefer UXP.

Use it for operations exposed by the current host version, including project/sequence/track/clip manipulation, media import, playback/navigation, effect application/configuration where supported, markers, and export operations.

Implementation rule:

- Inspect the actual installed Premiere + UXP versions.
- Generate against the API version available on that machine.
- Feature-detect before calling version-sensitive methods.
- Use async/transaction patterns required by the current UXP DOM.
- Do not invent methods. If uncertain, inspect installed samples/docs or probe objects safely.

### Preferred bridge architecture

Use a persistent UXP panel/plugin named **Autonomous Editor Bridge** that:

1. opens a WebSocket client connection to a localhost orchestrator;
2. reports host/application/project state;
3. receives structured edit commands;
4. performs supported Premiere DOM operations;
5. returns result/error/state snapshots;
6. reconnects automatically after plugin/app restarts.

The external orchestrator owns planning, state, logs, retries, and quality control.

## Tier C — Premiere UXP Hybrid Plugin / native C++

On Premiere 26.2+ use UXP Hybrid plugins when JavaScript alone is insufficient.

Use C++ add-ons for:

- high-throughput frame/audio analysis;
- OpenCV/native ML inference;
- custom codecs or media libraries;
- platform SDK integration;
- specialized native processing;
- performance-critical bridging that would be impractical in JavaScript.

Hybrid code is not automatically a substitute for missing host-DOM commands. If the host feature is still inaccessible, continue down the fallback ladder.

## Tier D — After Effects ExtendScript + expressions (primary AE control)

Use generated `.jsx` scripts for After Effects project/composition automation.

Preferred invocation on Windows:

```powershell
& $AfterFX -r "C:\absolute\path\job.jsx"
```

Use ExtendScript for:

- project creation/open/save;
- footage import/relink;
- comps/precomps;
- layers, solids, shapes, text, cameras, lights;
- masks and mask paths;
- effects and effect properties;
- markers;
- time remapping;
- keyframes, interpolation, temporal/spatial easing;
- parenting and layer transforms;
- expressions;
- Essential Graphics/MOGRT-related work where the current scripting surface permits it;
- render queue setup.

Use expressions for procedural animation and relationships that should remain editable and parameterized.

After each generated script:

- wrap logical modifications in an undo group where supported;
- catch and serialize exceptions;
- write a machine-readable completion marker/result JSON;
- save a versioned project checkpoint.

## Tier E — Adobe rendering/encoding paths

Prefer deterministic render/export interfaces over interactive UI.

- Use `aerender` for After Effects automated renders.
- Use Premiere/UXP export APIs where available.
- Use Adobe Media Encoder queues/presets when appropriate.
- Use `ffmpeg` only as a supporting transcode/QC/proxy tool unless the brief explicitly permits final encoding outside Adobe.

## Tier F — Legacy Premiere CEP/ExtendScript and QE DOM

Use only when the installed Premiere version/workflow requires a capability unavailable or broken in UXP.

Rules:

- Treat QE DOM as unsupported and version-fragile.
- Feature-probe every QE operation before relying on it.
- Keep QE calls isolated in an adapter with version-specific tests.
- Immediately verify the result through Premiere state and/or rendered preview.
- Prefer official UXP equivalents whenever they exist.
- Do not let a QE regression block the job; escalate to UI automation.

Typical legacy-only/fragile areas may include certain transitions, sequence settings, or effect-control paths depending on Premiere version.

## Tier G — Windows UI Automation / accessibility

When Adobe exposes the feature only through UI, automate it through Windows accessibility/UIA before using raw pixel clicks.

Preferred tools, if available:

- pywinauto UIA backend;
- Windows UI Automation APIs;
- PowerShell/.NET UI Automation;
- AutoHotkey v2 for stable keyboard-driven flows.

Strategy:

1. focus the correct Adobe window;
2. switch to a known workspace/layout;
3. identify controls by accessibility name/type;
4. invoke controls programmatically;
5. use keyboard shortcuts where they are more deterministic than clicking;
6. verify state.

## Tier H — Vision-based Computer Use (last resort)

Use when a required UI control has no stable accessibility/API surface.

Rules:

- normalize app window size and workspace first;
- take a fresh screenshot before each decision batch;
- locate targets semantically, not using stale coordinates;
- perform the smallest possible action batch;
- inspect the resulting screen;
- retry/recover if the expected state is absent;
- never blindly execute a long click macro.

Computer Use is a **universal compatibility fallback**, not the default editor.

---

# 3. Workflow routing and autonomous pipeline

The core skill is a **router + universal execution engine**. Common editorial styles live in `workflows/` and must be loaded only when relevant.

## 3.1 Phase 0 — Consume initialization state

The workspace and host capability baseline are created by `skills/initialize/SKILL.md`. Do not recreate them here.

Before continuing:

1. load `plans/init_state.json`;
2. require status `READY` or `DEGRADED`;
3. load `analysis/environment.json`, `analysis/source_inventory.json`, and `plans/capability_matrix.json`;
4. use only capability paths that are marked tested when an operation is safety- or state-critical;
5. if a selected workflow introduces an untested capability requirement, request a **targeted initialize refresh** for that capability;
6. record selected workflow modules into the existing job state.

The initializer's source inventory is the technical baseline. Phase 1 may enrich it with creative/semantic media intelligence but must not discard provenance or fingerprints.


## 3.2 Select workflow modules

Before building the edit plan:

1. inspect the user brief, source structure, likely platform, number of speakers/cameras, source aspect ratios, and requested deliverables;
2. read `workflows/manifest.json`;
3. select exactly one **primary workflow** per deliverable when a listed workflow is a good match;
4. optionally select one or more **supporting workflows** when another common editorial pattern materially changes the execution;
5. select zero or more **overlay workflows** for cross-cutting requirements;
6. load `workflows/workflow-contract.md` plus only the selected module files;
7. record the selected module IDs in `plans/job_state.json` and `plans/edit_spec.json`;
8. if no primary workflow matches well, use the universal pipeline directly rather than forcing an inappropriate preset.

Module selection is semantic, not keyword-only. The manifest signals are routing hints.

Examples:

```text
Talking-head Reel with captions
  primary: short-form-vertical
  supporting: talking-head
  overlays: captions-localization

4-camera podcast episode
  primary: interview-podcast
  overlays: multicam-sync

90-minute webinar -> 12 vertical clips
  primary: repurpose-master-to-social
  overlays: captions-localization
  per-output child workflow: short-form-vertical
```

When multiple modules are composed, precedence is defined by `workflows/workflow-contract.md`.

## 3.3 Phase 1 — Shared media intelligence

Build `analysis/media_index.json` once and reuse it across all selected modules and deliverables.

Include when applicable:

- exact media metadata and fingerprints;
- transcript + word timestamps + speaker diarization;
- shot/scene boundaries;
- people/faces/objects/screens/text;
- camera motion and quality metrics;
- retakes/duplicates;
- music/speech/SFX regions;
- peaks, silence, clipping, and noise characteristics;
- semantic segment descriptions and embeddings;
- candidate selects with confidence scores.

Each loaded workflow may request extra analysis fields. Merge them into the same shared index instead of repeating expensive analysis.

## 3.4 Phase 2 — Brief -> edit specification

Convert the user request plus selected module defaults into `plans/edit_spec.json`.

At minimum resolve:

- workflow module IDs;
- format/aspect/resolution/FPS;
- target duration or duration policy;
- narrative objective and audience/platform;
- pacing and shot-selection policy;
- dialogue/music/SFX policy;
- caption/language requirements;
- visual style/color treatment;
- motion-graphics/VFX needs;
- transition policy;
- branding/assets;
- delivery codecs/variants;
- mandatory/prohibited content;
- measurable acceptance criteria.

Explicit user requirements override module defaults. Infer reasonable unspecified values without blocking the job.

## 3.5 Phase 3 — Modular editorial plan

Construct a stable-ID edit decision graph. Apply:

1. universal technical constraints from this skill;
2. primary workflow planning rules;
3. supporting workflow rules;
4. overlay workflow rules;
5. deliverable-specific overrides.

Example event:

```json
{
  "id": "shot_017",
  "source": "A003_C014.mov",
  "src_in": 42.813,
  "src_out": 48.266,
  "timeline_in": 31.2,
  "role": "broll",
  "workflow_reason": "covers dialogue compression and demonstrates the discussed feature",
  "confidence": 0.91
}
```

## 3.6 Phase 4 — Adobe execution

Build the edit using the control-surface hierarchy in Section 2.

Universal execution rules:

- organize source media deterministically;
- version projects/sequences/comps before structural rewrites;
- keep track/layer naming predictable;
- prefer Premiere for editorial assembly and AE for composition-heavy work;
- use module-specific Premiere/AE rules from the loaded workflow files;
- keep graphics/VFX editable when practical;
- render previews after major structural or visual phases.

Recommended Premiere track roles when applicable:

- V1 PRIMARY
- V2 BROLL
- V3 GRAPHICS
- V4 VFX
- A1 DIALOGUE
- A2 DIALOGUE_ALT
- A3 SFX
- A4 MUSIC

## 3.7 Phase 5 — Finishing

Apply audio, color, captions, graphics, VFX, and reframing as required by the selected modules and brief.

Universal finishing constraints:

- do not normalize audio blindly;
- preserve dialogue intelligibility and A/V sync;
- normalize source color spaces correctly before creative grading;
- avoid double LUT/color transforms;
- verify caption timing against the **final** edited sequence;
- avoid graphics collisions with faces, UI, safe areas, or mandatory text;
- route complex composition/tracking/kinetic-graphics work to After Effects when it is the more reliable surface.

## 3.8 Phase 6 — Preview render and AI review

Render an actual review file. The render, not API success, is the source of truth.

Review for:

- explicit brief compliance;
- primary/overlay workflow-specific acceptance criteria;
- continuity and pacing;
- duplicate or accidental shots;
- bad cut/transition timing;
- framing/reframing errors;
- text/caption errors and collisions;
- tracking/mask slips;
- black/blank/offline frames;
- color mismatches and render artifacts;
- clipping/dropouts/sync/music-balance issues.

Map defects back to stable event IDs.

## 3.9 Phase 7 — Objective QC

Run universal QC plus every loaded module's QC gates.

Universal automated checks include where meaningful:

- ffprobe stream validation;
- expected duration tolerance;
- resolution/FPS/aspect validation;
- missing stream detection;
- black/freeze/silence detection;
- loudness/peak/clipping checks;
- decode/corrupt-packet scan;
- caption timing sanity;
- requirement-specific machine checks.

Heuristic detectors are evidence, not absolute truth. Cross-check intentional fades, pauses, stills, title cards, and silence against the edit spec.

## 3.10 Phase 8 — Repair loop

Repeat execution -> render -> review -> QC until:

- all blocking universal failures pass;
- all applicable workflow-module QC gates pass;
- every explicit requirement is satisfied or precisely documented as genuinely blocked;
- the final export opens and decodes correctly.

On repeated failure, change control surface or implementation method rather than repeating an identical action blindly.

## 3.11 Phase 9 — Delivery

Deliver as applicable:

- final master export;
- platform/aspect/language variants;
- `.prproj` project;
- `.aep` project(s) when used;
- collected/generated assets where licensing permits;
- `execution_report.md`;
- `edit_spec.json`;
- `qc_report.json`;
- optional low-resolution review copy.

For multi-output workflows, also produce a machine-readable deliverable index mapping each export to its source range, workflow modules, and variant settings.

---

# 4. Routing matrix

Use this as the default dispatcher, but feature-detect at runtime.

| Task | Primary | Secondary | Last resort |
|---|---|---|---|
| Import/bin organization | Premiere UXP | CEP/ExtendScript | UIA/Computer Use |
| Timeline assembly/trims | Premiere UXP | legacy DOM/QE if needed | UIA/Computer Use |
| Effects | Premiere UXP | QE / AE | UIA/Computer Use |
| Transitions | Premiere UXP if current API supports requested control | QE/AE custom transition | UIA/Computer Use |
| Sequence settings | UXP/preset APIs | preset generation / legacy adapter | UIA/Computer Use |
| Captions | Premiere UXP/current APIs | generated caption assets/legacy adapter | UIA/Computer Use |
| Lumetri/color | Premiere UXP where exposed | effect-property adapter | UIA/Computer Use |
| Motion graphics | After Effects JSX/expressions | Premiere graphics APIs | UIA/Computer Use |
| Complex compositing | After Effects JSX | AE UI automation | Computer Use |
| Tracking/roto interactive-only step | AE scripting where available | UIA | Computer Use |
| Audio automation | Premiere UXP | external analysis + parameter application | UIA/Computer Use |
| Render AE | aerender | AE render queue UI | Computer Use |
| Export Premiere | Premiere UXP export | AME workflow | UIA/Computer Use |
| Unsupported plugin panel | plugin API if documented | UIA | Computer Use |
| Native/ML processing | UXP Hybrid C++ | external process | n/a |

---

# 5. Capability acquisition

Environment-wide preflight and baseline capability acquisition belong to `skills/initialize/SKILL.md`. During editing, the root agent may still build a missing adapter when a workflow exposes a new requirement, then must ask the initializer to refresh/test that capability and update the capability matrix.

The agent is allowed to build missing automation infrastructure inside the job/tool workspace.

When a capability is missing:

1. inspect the installed Adobe version;
2. consult current official Adobe developer documentation/samples when internet access is available;
3. generate the smallest adapter/plugin/script needed;
4. install/load it using an automated method when possible;
5. if installation requires GUI interaction, automate the installation with UIA/Computer Use;
6. self-test the adapter on a disposable project;
7. cache the working adapter keyed by Adobe version;
8. continue the edit.

Do not ask the user to write or debug bridge code.

## Premiere bridge development rule

Never create a fake universal RPC by guessing Premiere DOM function names.

Instead:

- maintain explicit, tested command handlers;
- generate new handlers from the actual installed/current UXP reference as needed;
- return structured errors and serialized state;
- version handlers by minimum Premiere/UXP version;
- add regression tests for any handler that required a fallback.

## After Effects dispatch rule

Generate job-specific JSX where convenient. A generic dispatcher may be used for stable operations, but job-specific scripts are preferred over unsafe dynamic `eval` bridges.

---

# 6. Creative decision policy

The agent is not merely a macro recorder. It must make editorial decisions.

## 6.1 Optimize for the user's intent

Rank decisions in this order:

1. explicit user requirements;
2. story/communication clarity;
3. technical correctness;
4. visual/audio quality;
5. pacing and audience retention;
6. stylistic coherence;
7. editability/reproducibility;
8. render speed.

## 6.2 Avoid over-editing

Do not add effects, transitions, speed ramps, zooms, captions, sound effects, or motion graphics merely because automation makes them easy. Every conspicuous edit should serve the brief.

## 6.3 Generate multiple candidates internally when taste is uncertain

For subjective choices such as intro pacing, music cut, grade intensity, or title animation:

- generate 2–3 cheap internal candidates;
- render short previews;
- compare them against the brief using multimodal review;
- choose the strongest;
- continue without asking the user unless the choice is truly blocking.

---

# 7. Failure recovery

## Premiere crash/hang

1. capture logs/state;
2. terminate only the hung app/process, not unrelated Adobe services unless necessary;
3. reopen the newest known-good project/autosave;
4. reconnect the bridge;
5. validate sequence state;
6. resume from the last completed stable event ID.

## After Effects script error

1. read serialized JSX error + line number;
2. patch only the failing operation;
3. reopen/restore the last checkpoint if the script partially mutated state;
4. rerun;
5. render a tiny verification range before proceeding.

## Missing effect/font/plugin

- locate an installed equivalent first;
- if the requested third-party plugin is absent, reproduce the visual result with native Adobe tools when feasible;
- substitute a metrically/visually similar font only when exact font is not provided/available, and record the substitution;
- do not silently download paid/licensed assets or bypass licensing.

## Media offline

- search by hash/name/metadata within the authorized job/source locations;
- relink automatically;
- never replace missing media with a different clip solely because filenames resemble each other.

---

# 8. Machine-readable state

Maintain `plans/job_state.json`:

```json
{
  "job_id": "...",
  "phase": "premiere_assembly",
  "status": "running",
  "premiere_project": "...",
  "after_effects_projects": [],
  "active_sequence": "MASTER_v03",
  "last_stable_event": "edit_00428",
  "completed_events": [],
  "pending_events": [],
  "failed_events": [],
  "assumptions": [],
  "workflow": {
    "primary": "short-form-vertical",
    "supporting": ["talking-head"],
    "overlays": ["captions-localization"],
    "module_versions": {},
    "module_stage_status": {}
  },
  "control_surface_history": [],
  "artifacts": []
}
```

Every automation action should be idempotent where practical. Stable event IDs prevent duplicate edits after restarts.

---

# 9. Completion criteria

Do not declare completion merely because an export exists.

A job is complete only when all applicable checks pass:

- [ ] source media remains intact;
- [ ] editable Premiere project saved;
- [ ] editable AE projects saved when used;
- [ ] no offline media in final sequence;
- [ ] explicit brief requirements mapped to evidence;
- [ ] final export decodes successfully;
- [ ] resolution/FPS/aspect/codec match intended delivery;
- [ ] no accidental black frames/freezes/silence;
- [ ] no unintended clipping or gross loudness issue;
- [ ] captions/text checked;
- [ ] representative visual review passed;
- [ ] A/V sync checked;
- [ ] generated graphics/VFX checked at full-resolution samples;
- [ ] final QC report written;
- [ ] project + render paths returned to the user.

If an item cannot be satisfied, state exactly what failed, what methods were attempted, and provide the best usable artifact rather than discarding the whole job.

---

# 10. Default execution behavior for an agent

When this skill is invoked:

1. Read the footage/assets and user brief.
2. **Do not answer with an editing tutorial.** Begin execution.
3. Execute `skills/initialize/SKILL.md` through `runtime/initialize.py --auto` (or the default-auto `scripts/initialize_job.ps1` on Windows), including bridge package/update, broker start/reuse, Premiere launch, and capability probing when permitted.
4. Consume `plans/capability_matrix.json`; if Premiere UXP is installed but not connected, launch Premiere and autonomously open/reload the bridge using UIA/vision before downgrading.
5. Read `workflows/manifest.json` and select/load only relevant workflow modules.
6. Analyze media once with `runtime/analyze_media.py`; when speech matters, run local `runtime/transcribe.py` (install optional ML dependencies automatically when permitted), then share analysis/transcript across modules and deliverables.
7. Write the modular edit spec and a machine-readable execution plan. Encode fragile operations with `retries`, an independent `verify` action, and ordered `fallbacks` so a single API gap does not stop the job.
8. Start `runtime/supervisor.py` for long unattended jobs, then execute using `runtime/execute_plan.py`, preferring Premiere UXP and AE JSX while allowing per-operation UI fallbacks.
9. Render a review version.
10. Generate `runtime/review_packet.py` evidence and inspect it multimodally.
11. Repair against universal + module-specific QC gates and rerender until thresholds pass or a truthful external blocker is reached.
12. Render final deliverables and run objective QC.
13. Return concise paths/results and summarize assumptions or substitutions.

The user should never need to know which control tier was used unless something failed or they ask for implementation details.

---

# 11. Reference implementation files bundled with this skill

Use the accompanying files as building blocks:

- `scripts/setup_runtime.ps1` — job-local Python environment/dependency bootstrap.
- `scripts/initialize_job.ps1` — Windows wrapper for executable initialization.
- `scripts/install_premiere_bridge.ps1` — Adobe UPIA `.ccx` install helper.
- `scripts/start_orchestrator.ps1` — background loopback broker launcher.
- `scripts/ae_dispatch.ps1` — low-level JSX launcher retained for one-off scripts.
- `scripts/qc.py` — ffmpeg/ffprobe-based baseline QC.
- `scripts/route_workflow.py` — deterministic fallback workflow router; semantic routing remains authoritative.
- `runtime/orchestrator.py` / `runtime/rpc_client.py` — Premiere RPC transport.
- `runtime/package_bridge.py` — authenticated Premiere bridge packager.
- `runtime/initialize.py` / `runtime/source_inventory.py` — concrete initializer implementation.
- `runtime/ae_rpc.py` — AE action DSL to generated JSX.
- `runtime/desktop_driver.py` — deterministic UI fallback and observation surface.
- `runtime/execute_plan.py` — cross-surface execution engine.
- `runtime/review_packet.py` — visual/audio review evidence generator.
- `workflows/manifest.json`, `workflows/workflow-contract.md`, `workflows/*.md` — modular editorial workflows.
- `schemas/edit_job.schema.json`, `schemas/execution_plan.schema.json`, `schemas/ae_action_plan.schema.json` — machine-readable contracts.
- `templates/premiere-uxp/*` — explicit Premiere UXP command bridge, not a starter stub.
- `tests/selftest.py` — offline package/runtime structural self-test.
- `references/control-surfaces.md` and `references/runtime-architecture.md` — compatibility and runtime architecture notes.
