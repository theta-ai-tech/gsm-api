#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: ./scripts/rollback_functions.sh [--project <firebase_project_id>] [--revision <rev>] [--env <dev|prod>]

Options:
  --project   Firebase project id (defaults to FIREBASE_PROJECT_ID or GOOGLE_CLOUD_PROJECT)
  --revision  Revision to roll back to (defaults to deploy/last_good_revision_<env>.txt)
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
  REV_FILE="$ROOT_DIR/deploy/last_good_revision_${DEPLOY_ENV}.txt"
  if [[ ! -f "$REV_FILE" ]]; then
    echo "Missing $REV_FILE; provide --revision explicitly." >&2
    exit 1
  fi
  REVISION="$(awk '/ DEPLOYED /{rev=$1} END{print rev}' "$REV_FILE")"
fi

if [[ -z "$REVISION" || "$REVISION" == "UNSET" ]]; then
  echo "Revision is empty or UNSET; provide --revision explicitly." >&2
  exit 1
fi

if ! git -C "$ROOT_DIR" rev-parse --verify "$REVISION" >/dev/null 2>&1; then
  echo "Revision $REVISION not found in git history." >&2
  exit 1
fi

WORKTREE_DIR="$(mktemp -d)"
cleanup() {
  git -C "$ROOT_DIR" worktree remove --force "$WORKTREE_DIR" >/dev/null 2>&1 || true
  rm -rf "$WORKTREE_DIR"
}
trap cleanup EXIT

echo "Rolling back Firebase Functions"
echo "Project:  $PROJECT"
echo "Revision: $REVISION"
echo "Worktree: $WORKTREE_DIR"

git -C "$ROOT_DIR" worktree add --detach "$WORKTREE_DIR" "$REVISION" >/dev/null

"$WORKTREE_DIR/scripts/deploy_functions.sh" --project "$PROJECT" --revision "$REVISION" --env "$DEPLOY_ENV"

LOG_FILE="$ROOT_DIR/deploy/last_good_revision_${DEPLOY_ENV}.txt"
timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
mkdir -p "$(dirname "$LOG_FILE")"
printf "%s ROLLED BACK %s\n" "$REVISION" "$timestamp" >> "$LOG_FILE"
echo "Logged:   $LOG_FILE"

echo "Rollback complete."
echo "Revision: $REVISION"
