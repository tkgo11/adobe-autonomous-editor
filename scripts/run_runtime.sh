#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: run_runtime.sh JOB_ROOT SKILL_ROOT COMMAND [ARG ...]" >&2
  exit 2
fi

JOB_ROOT="$1"
SKILL_ROOT="$2"
COMMAND="$3"
shift 3

case "$COMMAND" in
  analyze_media|desktop_driver|execute_plan|review_packet|rpc_client|source_inventory|supervisor|transcribe) SCRIPT="$SKILL_ROOT/runtime/$COMMAND.py" ;;
  qc) SCRIPT="$SKILL_ROOT/scripts/qc.py" ;;
  *) echo "Unsupported runtime command: $COMMAND" >&2; exit 2 ;;
esac

PYTHON="$JOB_ROOT/runtime/venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "Job runtime is not initialized: $PYTHON" >&2
  exit 1
fi
[[ -f "$SCRIPT" ]] || { echo "Runtime command not found: $SCRIPT" >&2; exit 1; }
AAE_JOB_ROOT="$JOB_ROOT" exec "$PYTHON" "$SCRIPT" "$@"
