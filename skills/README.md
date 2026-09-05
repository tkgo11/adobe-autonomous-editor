# Internal Skills

Internal sub-skills used by the root `adobe-autonomous-editor` skill.

## initialize

`initialize/SKILL.md` is a mandatory prerequisite for every edit job. It owns workspace/bootstrap, source inventory, host/dependency discovery, Adobe control-surface self-tests, capability-matrix generation, readiness state, and targeted re-initialization after environment failures.

The root skill must load/run it before workflow selection. It is intentionally separate from editorial workflow modules under `workflows/`.
