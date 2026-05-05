#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
PLAYLIST_ID="${PLAYLIST_ID:-PLieDuyulq1X7z4ch-V_oGGoVkuZJy8nSQ}"
CLIENT_SECRETS="${CLIENT_SECRETS:-$SCRIPT_DIR/secret.json}"
TOKEN_FILE="${TOKEN_FILE:-$PROJECT_DIR/.secrets/youtube-token.json}"
DAYS_TO_KEEP="${DAYS_TO_KEEP:-30}"
DRY_RUN="false"
LOG_PATH="${LOG_PATH:-$PROJECT_DIR/output/prune-old-playlist.log}"

usage() {
  cat <<EOF
Usage: $0 [--dry-run] [--days-to-keep N] [--help]

Environment variables:
  PLAYLIST_ID      ID of the existing YouTube playlist to prune.
  CLIENT_SECRETS   Path to Google OAuth client secrets JSON.
  TOKEN_FILE       Path to cached OAuth token. Defaults to .secrets/youtube-token.json.
  DAYS_TO_KEEP     Number of days to retain playlist items. Defaults to 30.
  PYTHON           Path to the Python interpreter to use.

Options:
  --dry-run        Print the command and do not delete playlist items.
  --days-to-keep N Use N instead of the DAYS_TO_KEEP environment variable.
  --help           Show this help message.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --days-to-keep)
      if [[ -z "${2:-}" ]]; then
        printf 'Missing value for --days-to-keep\n' >&2
        usage
        exit 1
      fi
      DAYS_TO_KEEP="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$PLAYLIST_ID" ]]; then
  printf 'Error: PLAYLIST_ID must be set.\n' >&2
  usage
  exit 1
fi

mkdir -p "$(dirname "$LOG_PATH")"
touch "$LOG_PATH"
exec > >(tee -a "$LOG_PATH") 2>&1

log_exit() {
  local exit_code=$?
  printf '==== YouTube playlist prune run finished %s exit=%s ====' "$(date -Is)" "$exit_code"
}
trap log_exit EXIT

printf '\n==== YouTube playlist prune run started %s ====' "$(date -Is)"
printf '\nProject directory: %s' "$PROJECT_DIR"
printf '\nYouTube playlist ID: %s' "$PLAYLIST_ID"
printf '\nDays to keep: %s\n' "$DAYS_TO_KEEP"
if [[ "$DRY_RUN" == "true" ]]; then
  printf 'Dry run mode enabled. No playlist items will be deleted.\n'
fi

cd "$PROJECT_DIR"

PYTHON="${PYTHON:-$PROJECT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON" ]]; then
  printf 'Error: Python interpreter not found.\n' >&2
  exit 1
fi

EMPTY_INPUTS_FILE="$(mktemp)"
trap 'rm -f "$EMPTY_INPUTS_FILE"' EXIT

cmd=("$PYTHON" "$PROJECT_DIR/run.py" --channel-source youtube-api --channels-file "$EMPTY_INPUTS_FILE" --videos-file "$EMPTY_INPUTS_FILE" --youtube-playlist-id "$PLAYLIST_ID" --youtube-client-secrets "$CLIENT_SECRETS" --youtube-token-file "$TOKEN_FILE" --youtube-prune-older-than-days "$DAYS_TO_KEEP")
if [[ "$DRY_RUN" == "true" ]]; then
  cmd+=(--dry-run)
fi

printf 'Running: %s\n' "${cmd[*]}"
"${cmd[@]}"
