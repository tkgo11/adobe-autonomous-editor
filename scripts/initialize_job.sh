#!/usr/bin/env bash
set -euo pipefail

JOB_ROOT=""
SKILL_ROOT=""
BRIEF=""
EDITOR_PRIORITY="crafting-first"
AUTO=1
SOURCES=()
EXTRA=()

usage() {
  echo "Usage: initialize_job.sh --job-root PATH --skill-root PATH --source PATH [--source PATH ...] [--brief TEXT] [--editor-priority crafting-first|adobe-only] [--no-auto]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --job-root) JOB_ROOT="$2"; shift 2 ;;
    --skill-root) SKILL_ROOT="$2"; shift 2 ;;
    --source) SOURCES+=("$2"); shift 2 ;;
    --brief) BRIEF="$2"; shift 2 ;;
    --editor-priority) EDITOR_PRIORITY="$2"; shift 2 ;;
    --no-auto) AUTO=0; shift ;;
    --) shift; EXTRA+=("$@"); break ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

[[ -n "$JOB_ROOT" && -n "$SKILL_ROOT" && ${#SOURCES[@]} -gt 0 ]] || { usage; exit 2; }
[[ "$EDITOR_PRIORITY" == "crafting-first" || "$EDITOR_PRIORITY" == "adobe-only" ]] || { usage; exit 2; }
mkdir -p "$JOB_ROOT/runtime"
PYTHON=$("$SKILL_ROOT/scripts/provision_python.sh" "$JOB_ROOT")
ARGS=("$SKILL_ROOT/runtime/bootstrap.py" --job-root "$JOB_ROOT" --skill-root "$SKILL_ROOT" --brief "$BRIEF" --editor-priority "$EDITOR_PRIORITY")
for source in "${SOURCES[@]}"; do ARGS+=(--source "$source"); done
if [[ $AUTO -eq 1 ]]; then ARGS+=(--auto); fi
if [[ ${#EXTRA[@]} -gt 0 ]]; then ARGS+=("${EXTRA[@]}"); fi
exec "$PYTHON" "${ARGS[@]}"
