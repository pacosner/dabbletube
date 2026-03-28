#!/usr/bin/env bash

set -euo pipefail

TASK_NAME="${TASK_NAME:-Dabbleverse}"
PROJECT_DIR="/home/pacos/dabbletube"
LOG_PATH="${LOG_PATH:-$PROJECT_DIR/output/task.log}"

mkdir -p "$(dirname "$LOG_PATH")"
touch "$LOG_PATH"

exec >>"$LOG_PATH" 2>&1

log_exit() {
  local exit_code=$?
  printf '==== %s run finished %s exit=%s ====\n' "$TASK_NAME" "$(date -Is)" "$exit_code"
}

trap log_exit EXIT

printf '\n==== %s run started %s ====\n' "$TASK_NAME" "$(date -Is)"

cd "$PROJECT_DIR"
if [[ ! -f .venv/bin/activate ]]; then
  printf 'Virtualenv activate script not found at %s\n' "$PROJECT_DIR/.venv/bin/activate" >&2
  exit 1
fi

source .venv/bin/activate
./dabbleverse-default
