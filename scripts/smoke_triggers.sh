#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: ./scripts/smoke_triggers.sh --env emu|dev [--project <firebase_project_id>]

Options:
  --env      emu or dev
  --project  Firebase project id (required for dev; optional for emu)
  -h, --help Show this help
USAGE
}

ENVIRONMENT=""
PROJECT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENVIRONMENT="${2:-}"
      shift 2
      ;;
    --project)
      PROJECT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$ENVIRONMENT" != "emu" && "$ENVIRONMENT" != "dev" ]]; then
  echo "--env must be 'emu' or 'dev'" >&2
  exit 1
fi

if [[ "$ENVIRONMENT" == "emu" ]]; then
  EMU_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
  EMU_HOSTNAME="${EMU_HOST%:*}"
  EMU_PORT="${EMU_HOST#*:}"
  if command -v nc >/dev/null 2>&1; then
    if ! nc -z "$EMU_HOSTNAME" "$EMU_PORT" >/dev/null 2>&1; then
      echo "Firestore emulator not reachable at $EMU_HOST. Start it with: make emu-firestore" >&2
      exit 1
    fi
  else
    python - <<PY >/dev/null 2>&1 || { echo "Firestore emulator not reachable at $EMU_HOST. Start it with: make emu-firestore" >&2; exit 1; }
import socket
s = socket.socket()
s.settimeout(1.0)
s.connect(("${EMU_HOSTNAME}", int("${EMU_PORT}")))
s.close()
PY
  fi
  export FIRESTORE_EMULATOR_HOST="$EMU_HOST"
  export GOOGLE_CLOUD_PROJECT="${PROJECT:-gsm-dev-f70d0}"
  export FIREBASE_PROJECT_ID="${PROJECT:-gsm-dev-f70d0}"
  echo "Seeding emulator baseline data..."
  python -m tools.seed_firestore --env=emu >/dev/null 2>&1 || true
fi

if [[ "$ENVIRONMENT" == "dev" ]]; then
  if [[ -z "$PROJECT" ]]; then
    echo "--project is required for dev smoke." >&2
    exit 1
  fi
  export GOOGLE_CLOUD_PROJECT="$PROJECT"
  export FIREBASE_PROJECT_ID="$PROJECT"
fi

# Only forward --project when set: passing an empty value would make the Firestore
# client build a "projects//databases/(default)" path. For emu the client falls back
# to GOOGLE_CLOUD_PROJECT (exported above) when --project is omitted.
if [[ -n "$PROJECT" ]]; then
  python -m tools.smoke_triggers --env "$ENVIRONMENT" --project "$PROJECT"
else
  python -m tools.smoke_triggers --env "$ENVIRONMENT"
fi
