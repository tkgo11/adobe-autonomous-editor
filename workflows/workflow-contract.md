# Workflow Module Contract

A workflow module is an execution policy layered on top of the universal autonomous pipeline in `SKILL.md`.

## Orchestrator contract

When a module is selected, the orchestrator must:

1. preserve every non-negotiable rule from `SKILL.md`;
2. merge module defaults into `plans/edit_spec.json` only where the user did not specify a value;
3. add module-specific analysis fields to `analysis/media_index.json`;
4. emit module-specific planned events with stable IDs;
5. select the highest reliable Adobe control surface for each operation;
6. render and inspect an intermediate review before final export;
7. run both universal QC and module-specific QC;
8. repair failures automatically until acceptance criteria pass or a genuine blocker remains.

## Precedence

When instructions conflict, use this order:

1. explicit user requirement;
2. safety/licensing/privacy constraints;
3. `SKILL.md` non-negotiable operating rules;
4. primary workflow module;
5. overlay workflow modules;
6. inferred defaults.

## Composition

A job can combine modules. Use one dominant primary workflow, optional **supporting workflows** for another editorial dimension, and overlays for cross-cutting technical requirements. Example:

```text
primary: short-form-vertical
supporting:
  - talking-head
overlays:
  - captions-localization
  - multicam-sync
```

When two modules prescribe different values for the same field, prefer the more specific module for the final deliverable. Example: `short-form-vertical` aspect ratio overrides `talking-head` landscape defaults.

## State additions

Append to `plans/job_state.json`:

```json
{
  "workflow": {
    "primary": "short-form-vertical",
    "supporting": ["talking-head"],
    "overlays": ["captions-localization"],
    "module_versions": {},
    "module_stage_status": {}
  }
}
```

## Reusable caches

Cache expensive analysis across modules and deliverables:

- transcript + word timestamps;
- speaker diarization;
- shot boundaries;
- face/subject tracks;
- source quality metrics;
- music beat grid;
- semantic embeddings;
- logo/brand asset detection;
- caption corrections and proper nouns.

Never repeat heavy analysis merely because a second deliverable uses a different workflow module.
