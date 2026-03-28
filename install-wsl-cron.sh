#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER_PATH="$SCRIPT_DIR/run-dabbleverse-task.sh"
CRON_SCHEDULE="${CRON_SCHEDULE:-0 * * * *}"
CRON_TAG="# dabbleverse-task"
CRON_COMMAND="/bin/bash \"$RUNNER_PATH\""
CRON_LINE="$CRON_SCHEDULE $CRON_COMMAND $CRON_TAG"

if [[ ! -x "$RUNNER_PATH" ]]; then
  echo "Runner script is not executable: $RUNNER_PATH" >&2
  exit 1
fi

tmpfile="$(mktemp)"
trap 'rm -f "$tmpfile"' EXIT

crontab -l 2>/dev/null | sed '/# dabbleverse-task$/d' > "$tmpfile" || true
printf '%s\n' "$CRON_LINE" >> "$tmpfile"
crontab "$tmpfile"

printf 'Installed cron entry:\n%s\n' "$CRON_LINE"
printf 'Current crontab:\n'
crontab -l
