#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: ./scripts/deploy_functions.sh [--project <firebase_project_id>] [--revision <rev>] [--env <dev|prod>]

Options:
  --project   Firebase project id (defaults to FIREBASE_PROJECT_ID or GOOGLE_CLOUD_PROJECT)
  --revision  Revision tag to stamp (defaults to git short SHA)
  --env       Target environment; selects deploy/last_good_revision_<env>.txt (default: dev)
  -h, --help  Show this help
USAGE
}

PROJECT=""
REVISION=""
DEPLOY_ENV="${DEPLOY_ENV:-dev}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT="${2:-}"
      shift 2
      ;;
    --revision)
      REVISION="${2:-}"
      shift 2
      ;;
    --env)
      DEPLOY_ENV="${2:-}"
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

if [[ "$DEPLOY_ENV" != "dev" && "$DEPLOY_ENV" != "prod" ]]; then
  echo "Invalid --env '$DEPLOY_ENV' (expected dev or prod)." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -z "$PROJECT" ]]; then
  PROJECT="${FIREBASE_PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
fi
if [[ -z "$PROJECT" ]]; then
  echo "Missing --project and FIREBASE_PROJECT_ID/GOOGLE_CLOUD_PROJECT is not set." >&2
  exit 1
fi

if [[ -z "$REVISION" ]]; then
  if git -C "$ROOT_DIR" rev-parse --short HEAD >/dev/null 2>&1; then
    REVISION="$(git -C "$ROOT_DIR" rev-parse --short HEAD)"
  else
    REVISION="unknown"
  fi
fi

FUNCTION_SOURCE="functions"
if [[ ! -d "$ROOT_DIR/$FUNCTION_SOURCE" ]]; then
  echo "Expected functions source at $ROOT_DIR/$FUNCTION_SOURCE" >&2
  exit 1
fi

if command -v rg >/dev/null 2>&1; then
  HAS_FUNCTIONS_BLOCK=$(rg -q '"functions"\s*:' "$ROOT_DIR/firebase.json" && echo "yes" || echo "no")
else
  HAS_FUNCTIONS_BLOCK=$(grep -Eq '"functions"[[:space:]]*:' "$ROOT_DIR/firebase.json" && echo "yes" || echo "no")
fi

VENV_DIR="$ROOT_DIR/$FUNCTION_SOURCE/venv"
if [[ ! -d "$VENV_DIR" ]]; then
  if command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN="python3.11"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    echo "Python not found. Install Python 3.11+ to create the functions venv." >&2
    exit 1
  fi
  echo "Creating functions venv at $VENV_DIR"
  (cd "$ROOT_DIR/$FUNCTION_SOURCE" && "$PYTHON_BIN" -m venv venv)
  echo "Installing functions deps"
  (cd "$ROOT_DIR/$FUNCTION_SOURCE" && ./venv/bin/pip install --upgrade pip && ./venv/bin/pip install -r requirements.txt)
fi

if [[ "$HAS_FUNCTIONS_BLOCK" != "yes" ]]; then
  cat <<'EOF' >&2
firebase.json has no "functions" block, so Firebase CLI cannot deploy functions.
Add a functions config (e.g., {"functions": {"source": "functions", "runtime": "python311"}})
and ensure a functions entrypoint exists before deploying.
EOF
  exit 1
fi

echo "Deploying Firebase Functions"
echo "Project:  $PROJECT"
echo "Revision: $REVISION"
echo "Source:   $FUNCTION_SOURCE/"
echo "Scope:    functions"

# The push-delivery trigger onNotificationIntentCreated (functions/notification_triggers/,
# wired in functions/main.py) ships as part of `firebase deploy --only functions` below —
# there is no separate deploy target for it. Deploying functions deploys the trigger.
echo "Includes: onNotificationIntentCreated (push delivery) + match-cache triggers"

echo "Setting revision config: gsm.revision=$REVISION"
firebase functions:config:set gsm.revision="$REVISION" --project "$PROJECT"

firebase deploy --only functions --project "$PROJECT"

echo "Deployed functions:"
firebase functions:list --project "$PROJECT"
echo "Revision: $REVISION"

# Post-deploy smoke creates a synthetic match in the target project. That is fine
# for dev but would pollute prod, so prod skips auto-smoke unless FORCE_SMOKE=1.
SMOKE_ENV="${SMOKE_ENV:-dev}"
if [[ "$DEPLOY_ENV" == "prod" && "${FORCE_SMOKE:-0}" != "1" ]]; then
  echo "Skipping auto-smoke for prod (it writes synthetic data). Set FORCE_SMOKE=1 to override."
else
  echo "Running smoke checks: env=$SMOKE_ENV"
  ./scripts/smoke_triggers.sh --env "$SMOKE_ENV" --project "$PROJECT"
fi

LOG_FILE="$ROOT_DIR/deploy/last_good_revision_${DEPLOY_ENV}.txt"
timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
mkdir -p "$(dirname "$LOG_FILE")"
printf "%s DEPLOYED %s\n" "$REVISION" "$timestamp" >> "$LOG_FILE"
echo "Logged:   $LOG_FILE"
