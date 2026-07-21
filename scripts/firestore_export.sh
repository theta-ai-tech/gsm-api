#!/usr/bin/env bash
# Export a Firestore database to a GCS bucket (managed export).
#
# Read-only with respect to Firestore data. Intended to run daily against prod
# (see .github/workflows/firestore-backup.yml) but is safe to run manually.
#
# The export lands under gs://<bucket>/<prefix>/<UTC-timestamp>/ so each run is a
# self-contained, restorable snapshot. Retention is handled by the bucket's
# lifecycle policy (deploy/backup-bucket-lifecycle.json), not by this script.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: ./scripts/firestore_export.sh --project <id> --bucket <gcs-bucket> [--prefix <p>] [--database <db>]

Options:
  --project    GCP project id (required)
  --bucket     GCS bucket name, no gs:// (required), e.g. gsm-prod-firestore-backups
  --prefix     Path prefix within the bucket (default: scheduled)
  --database   Firestore database id (default: "(default)")
  -h, --help   Show this help
USAGE
}

PROJECT="" ; BUCKET="" ; PREFIX="scheduled" ; DATABASE="(default)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="${2:-}"; shift 2 ;;
    --bucket) BUCKET="${2:-}"; shift 2 ;;
    --prefix) PREFIX="${2:-}"; shift 2 ;;
    --database) DATABASE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

[[ -n "$PROJECT" ]] || { echo "--project is required" >&2; exit 1; }
[[ -n "$BUCKET" ]] || { echo "--bucket is required" >&2; exit 1; }

TIMESTAMP="$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
DEST="gs://${BUCKET}/${PREFIX}/${TIMESTAMP}"

echo "Exporting Firestore"
echo "Project:  $PROJECT"
echo "Database: $DATABASE"
echo "Dest:     $DEST"

gcloud firestore export "$DEST" \
  --project "$PROJECT" \
  --database "$DATABASE"

echo "Export started/completed to $DEST"
echo "Restore with: gcloud firestore import $DEST --project <target-project>"
