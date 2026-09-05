---
name: adobe-autonomous-editor-initialize
description: Internal bootstrap skill for Adobe Autonomous Editor. Run before any editing workflow. It creates or resumes the job workspace, inventories source media without modifying it, discovers Adobe applications and versions, detects available automation/control surfaces, prepares and self-tests Premiere/After Effects bridges and local tooling, writes a capability matrix and initialization state, and returns READY, DEGRADED, or BLOCKED without performing creative edits.
---

# Adobe Autonomous Editor — Initialize

## Role

This is an **internal prerequisite skill** for `adobe-autonomous-editor`.

Run it **once at the start of every job** and again whenever the execution environment materially changes (Adobe restart/update, plugin/bridge failure, machine change, dependency change, project recovery, or a capability previously marked unavailable becomes necessary).

The initializer prepares the environment. It does **not** make creative editorial decisions and does **not** modify source footage.

## Invocation contract

Input:

- absolute or resolvable path(s) to user-provided footage/assets/project files;
- user brief verbatim;
- optional existing job directory when resuming;
- parent skill root.

Output:

- initialized/resumed job directory;
- `analysis/environment.json`;
- `analysis/source_inventory.json`;
- `plans/init_state.json`;
- `plans/capability_matrix.json`;
- `logs/initialize.log`;
- a final status of `READY`, `DEGRADED`, or `BLOCKED`.

The parent skill must not begin workflow routing or creative editing until this skill has produced `plans/init_state.json`.

## Status meanings

### READY

All capabilities required for the likely job are available or have a tested fallback.

### DEGRADED

Editing can proceed safely, but one or more preferred control surfaces are unavailable. At least one tested fallback path exists for every capability currently required.

### BLOCKED

A true external blocker prevents safe execution and no valid fallback exists, for example:

- required source path cannot be accessed;
- no usable Premiere/After Effects installation exists for a requirement that specifically needs it;
- Adobe sign-in/license activation blocks launch and cannot be resolved without user action;
- required paid/licensed third-party component is absent and cannot be reproduced with native tools;
- OS permission blocks all viable control paths.

Do not use `BLOCKED` for ordinary missing utilities that can be installed or replaced automatically.

---

# 1. Non-negotiable initializer properties

## 1.1 Idempotent

Running initialization repeatedly against the same job must be safe.

- Reuse valid prior state.
- Refresh only stale or failed checks.
- Never duplicate imported assets or edit timeline/project state merely because initialization reruns.
- Keep previous initialization reports under `recovery/init-history/` when replacing them.

## 1.2 Non-destructive

- Never modify original footage/assets.
- Hash or fingerprint sources read-only.
- Never overwrite the only Adobe project copy.
- Perform bridge/API self-tests in a disposable sandbox project, not the user's production project.

## 1.3 Autonomous by default

Routine setup is the agent's job.

Automatically handle when permitted by the host environment:

- directory creation;
- local Python package installation into an isolated environment;
- locating ffmpeg/ffprobe;
- locating Adobe binaries;
- generating adapters/plugins/scripts;
- loading or installing the local Premiere bridge when installation does not require a purchase or unknown credential;
- restarting a bridge or disposable Adobe test instance;
- self-testing control surfaces.

Only escalate to the user for credentials, licensing/purchase, privacy-sensitive external upload permission, or another genuine external blocker.

## 1.4 Capability truth over assumptions

Never assume a feature exists because a specific Adobe version is expected to expose it.

Feature-detect and self-test the actual installed host.

A capability is `available` only when one of these is true:

1. a deterministic API/adapter probe succeeds; or
2. a disposable end-to-end test performs the operation and independently verifies the result.

---

# 2. Initialization sequence

Execute these stages in order. Persist state after every stage so recovery can resume rather than restart.

## Stage A — Resolve skill and job roots

1. Resolve the parent skill root containing the main `SKILL.md`.
2. Resolve all user source paths.
3. If resuming, validate the existing job directory.
4. Otherwise create a deterministic job directory that does not collide with another active job.
5. Record canonical absolute paths.

Create or verify:

```text
<job>/
  source/
  proxies/
  analysis/
  plans/
  projects/
    premiere/
    after-effects/
  assets/
  previews/
  renders/
  qc/
  logs/
  recovery/
    init-history/
  temp/
```

Do not require the user to copy files into `source/`. The job may reference read-only originals from their supplied locations. If copies are created for isolation, preserve originals and record the mapping.

## Stage B — Persist request identity

Write the verbatim user requirement to `plans/user_brief.txt` and create a stable job identifier.

Record:

- creation/resume timestamp;
- parent skill version/hash when available;
- source path list;
- user brief hash;
- machine identity suitable for recovery without exposing secrets.

Never store credentials, access tokens, or private keys in initialization reports.

## Stage C — Source inventory

Build `analysis/source_inventory.json` without creative interpretation.

For each accessible source record at minimum:

- canonical path;
- filename and extension;
- file size;
- modification timestamp;
- content fingerprint/hash when practical;
- media/container type;
- duration when media;
- video/audio stream count;
- codec, resolution, frame rate/timebase, pixel aspect, color metadata when available;
- audio sample rate/channel layout when available;
- whether the file is readable/decodable;
- whether it is a project, footage, audio, still image, subtitle, font, LUT, MOGRT, or miscellaneous asset.

Use `ffprobe` where applicable. For huge sources, a fast fingerprint may be recorded immediately and a full cryptographic hash may be deferred if it would materially delay startup; record which fingerprint method was used.

Flag but do not creatively repair:

- corrupt/undecodable media;
- missing linked media in supplied projects where detectable;
- variable frame rate;
- unusual frame rates/timebases;
- HDR/log/color-space metadata;
- unsupported codecs;
- very large media requiring proxies.

## Stage D — Host environment discovery

Discover and record:

### OS / hardware

- OS/build;
- CPU;
- RAM;
- GPU(s), VRAM when discoverable;
- available storage on job and cache volumes;
- hardware encoder/decoder availability when discoverable.

### Local media/AI utilities

At minimum probe:

- Python;
- PowerShell;
- ffmpeg;
- ffprobe;
- optional local speech-to-text runtime;
- optional OpenCV;
- optional GPU inference runtime;
- pywinauto/UI Automation capability;
- AutoHotkey when present.

### Adobe hosts

Locate and version:

- Premiere Pro;
- After Effects;
- `aerender`;
- Adobe Media Encoder;
- relevant installed UXP/CEP/plugin locations when discoverable.

Prefer actual binary/product version inspection over folder-name inference.

Write raw environment discovery to `analysis/environment.json`.

## Stage E — Prepare routine dependencies

For a missing routine dependency needed by this skill:

1. prefer an already installed compatible tool;
2. otherwise use a project-local/isolated installation when possible;
3. avoid global system mutation unless necessary;
4. verify the installed executable/library;
5. record version and path.

Do not silently install paid software, accept licenses on the user's behalf, bypass activation, or disable security controls.

If Internet/package access is unavailable, choose an installed fallback and mark the preferred path unavailable rather than blocking unnecessarily.

## Stage F — Premiere control-surface probe

Build a real capability profile rather than a single boolean.

Probe in this order where applicable:

1. Premiere UXP host/API availability;
2. Autonomous Editor Bridge installation/load/connectivity;
3. explicit tested UXP command handlers;
4. UXP Hybrid/native support when installed host supports it;
5. legacy CEP/ExtendScript adapter when present/needed;
6. QE adapter only as an unsupported compatibility fallback;
7. Windows UI Automation ability to identify the Premiere window and stable controls;
8. vision/Computer Use availability as last resort.

For the persistent Premiere bridge:

- prefer localhost-only communication;
- do not expose a listening service to the LAN by default;
- use a per-job/session secret if the bridge protocol supports authentication;
- verify host application/version and active project identity in the handshake;
- reconnect safely after Premiere restart;
- never treat socket connection alone as proof that edit commands work.

### Disposable Premiere self-test

When practical, use a disposable test project and verify a minimal subset such as:

1. launch/connect;
2. create/open disposable project;
3. create or identify a sequence;
4. import a tiny generated test asset when supported;
5. perform a non-destructive timeline mutation;
6. query project/timeline state independently;
7. remove/close disposable project without touching the production project.

If a high-level test fails, continue down the fallback ladder and record the failure reason.

## Stage G — After Effects control-surface probe

Probe:

1. `AfterFX.exe` availability/version;
2. command-line JSX execution (`afterfx -r` on Windows when supported);
3. ability to write a machine-readable completion marker from JSX;
4. project create/save in a disposable location;
5. `aerender` availability/version;
6. a tiny disposable render when practical;
7. AE UI Automation fallback;
8. vision/Computer Use fallback.

### Disposable AE self-test

Prefer a generated JSX that:

- creates a tiny project/comp;
- creates a solid/text layer;
- changes one property/keyframe;
- saves the project to `temp/`;
- writes a success JSON marker;
- optionally queues/renders a few frames;
- exits/closes safely if the automation surface allows it.

Validate the marker/project/render externally. A zero process exit code alone is insufficient.

## Stage H — Export/render capability probe

Determine tested paths for:

- Premiere export;
- Adobe Media Encoder when relevant;
- AE `aerender`;
- ffmpeg preview/proxy/QC generation.

Record codec/container availability needed for likely deliverables when they can be inferred cheaply from the brief. Do not start creative export presets yet.

## Stage I — Build capability matrix

Write `plans/capability_matrix.json`.

Use a structure equivalent to:

```json
{
  "premiere": {
    "timeline_edit": {
      "preferred": "uxp",
      "available_paths": ["uxp", "uia", "computer_use"],
      "tested": true
    },
    "effect_control": {
      "preferred": "uxp",
      "available_paths": ["uxp", "qe", "uia", "computer_use"],
      "tested": true
    }
  },
  "after_effects": {
    "jsx": {"available": true, "tested": true},
    "render": {"preferred": "aerender", "tested": true}
  },
  "media": {
    "ffmpeg": {"available": true, "tested": true},
    "ffprobe": {"available": true, "tested": true}
  }
}
```

For each meaningful capability record:

- preferred path;
- all known viable fallback paths in priority order;
- test status;
- host/version constraints;
- last error, if any;
- confidence/verification method where useful.

Do not claim universal coverage merely because Computer Use exists. Record whether the actual application can be launched and visually controlled.

## Stage J — Compute readiness

Write `plans/init_state.json` with at least:

```json
{
  "schema_version": 1,
  "status": "READY",
  "job_id": "...",
  "initialized_at": "...",
  "source_inventory": "analysis/source_inventory.json",
  "environment": "analysis/environment.json",
  "capability_matrix": "plans/capability_matrix.json",
  "preferred_premiere_surface": "uxp",
  "preferred_ae_surface": "jsx",
  "degraded_capabilities": [],
  "blockers": [],
  "next": "workflow-routing"
}
```

Status rules:

- `READY`: preferred paths work for the likely task.
- `DEGRADED`: preferred path failed, but a tested safe fallback exists.
- `BLOCKED`: no safe path exists for a capability required by the user's brief.

If the exact later workflow may require capabilities not yet tested, mark them `untested` rather than `unavailable`; the parent skill may request targeted re-initialization after workflow routing.

---

# 3. Re-initialization triggers

The parent skill must rerun this initializer in **targeted refresh mode** if any of the following occurs:

- Premiere or After Effects restarts unexpectedly;
- Adobe version changes;
- UXP plugin/bridge reloads or disconnects repeatedly;
- a command fails because a capability was misdetected;
- an operation requires a previously untested legacy/UI/native path;
- render/export executable disappears or fails self-test;
- machine/GPU/environment changes;
- job is resumed after a crash or long interruption;
- cached capability state is stale.

Targeted refresh should probe only affected capabilities when safe.

---

# 4. Recovery behavior

If initialization partially fails:

1. persist the completed stage and failure details;
2. preserve prior good state in `recovery/init-history/`;
3. repair or switch control surface;
4. rerun only the failed/stale stage;
5. regenerate the capability matrix;
6. return the strongest truthful readiness status.

Never loop forever on the same installer, bridge load, app launch, or self-test. After repeated identical failure, change strategy or downgrade to a tested fallback.

---

# 5. Security and privacy defaults

- Bind local automation bridges to loopback only unless a remote architecture is explicitly required.
- Do not expose footage, transcripts, project metadata, or bridge endpoints publicly.
- Do not upload source media to external AI/services during initialization.
- Do not log secrets.
- Do not disable antivirus, firewall, UAC, Adobe licensing, code-signing, or plugin security merely to make automation easier.
- Prefer least-privilege local processes and project-scoped dependencies.

---

# 6. Handoff to parent skill

On `READY` or `DEGRADED`:

1. return the absolute job root;
2. return paths to initialization artifacts;
3. return preferred Premiere/AE execution surfaces;
4. list degraded paths and their tested fallbacks;
5. set `next` to `workflow-routing`;
6. hand control back to the root `adobe-autonomous-editor/SKILL.md`.

The parent then selects workflow modules and may request a targeted capability refresh if a selected workflow requires something not yet tested.

On `BLOCKED`, return only genuine external blockers and the minimum user action needed to unblock them.

---

# 7. Scope boundary

This initializer may:

- inspect media technically;
- create test assets/projects;
- install/build routine automation infrastructure;
- test Adobe control surfaces;
- prepare proxies only when required to prove decoding/toolchain compatibility and clearly mark them as initialization artifacts.

It must **not**:

- choose story structure;
- cut the user's real timeline;
- choose takes for creative quality;
- design motion graphics;
- grade the production footage;
- mix the actual program;
- publish final exports.

Those responsibilities belong to the parent skill and selected workflow modules.
