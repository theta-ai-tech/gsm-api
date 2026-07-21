#!/usr/bin/env bash
# Apply GSM Cloud Monitoring alert policies from monitoring/*.json.
#
# OPERATOR ACTION — creates billable Cloud Monitoring resources. This is NOT run
# by CI. Run it manually against a target project once the notification channel
# and uptime check exist. See docs/operations/monitoring.md.
#
# Placeholders substituted into each policy file before `gcloud` applies it:
#   ${SERVICE_NAME}         Cloud Run service name (default: gsm-api)
#   ${NOTIFICATION_CHANNEL} full channel resource name (projects/…/notificationChannels/ID)
#   ${UPTIME_CHECK_ID}      uptime check id (for alert-uptime.json)
#   ${RUNBOOK_URL}          link included in the alert documentation

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: ./scripts/apply_monitoring.sh --project <id> --channel <channel-resource> \
         [--service <name>] [--uptime-check-id <id>] [--runbook <url>] [--dry-run]

Options:
  --project           GCP project id (required)
  --channel           Notification channel resource name (required), e.g.
                      projects/<id>/notificationChannels/1234567890
  --service           Cloud Run service name (default: gsm-api)
  --uptime-check-id   Uptime check id for the uptime alert (optional; skips
                      alert-uptime.json if not provided)
  --runbook           Runbook URL embedded in alert docs
  --dry-run           Print the substituted policy JSON without creating anything
  -h, --help          Show this help
USAGE
}

PROJECT="" ; CHANNEL="" ; SERVICE="gsm-api" ; UPTIME_ID="" ; RUNBOOK="" ; DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="${2:-}"; shift 2 ;;
    --channel) CHANNEL="${2:-}"; shift 2 ;;
    --service) SERVICE="${2:-}"; shift 2 ;;
    --uptime-check-id) UPTIME_ID="${2:-}"; shift 2 ;;
    --runbook) RUNBOOK="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

[[ -n "$PROJECT" ]] || { echo "--project is required" >&2; exit 1; }
[[ -n "$CHANNEL" ]] || { echo "--channel is required" >&2; exit 1; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MON_DIR="$ROOT_DIR/monitoring"

render() {
  # Substitute placeholders in a policy file, emit to stdout.
  sed \
    -e "s|\${SERVICE_NAME}|${SERVICE}|g" \
    -e "s|\${NOTIFICATION_CHANNEL}|${CHANNEL}|g" \
    -e "s|\${UPTIME_CHECK_ID}|${UPTIME_ID}|g" \
    -e "s|\${RUNBOOK_URL}|${RUNBOOK}|g" \
    "$1"
}

POLICIES=(
  "alert-5xx-rate.json"
  "alert-p95-latency.json"
  "alert-function-failures.json"
  "alert-firestore-quota.json"
)
# Only apply the uptime alert when an uptime check id was supplied.
if [[ -n "$UPTIME_ID" ]]; then
  POLICIES+=("alert-uptime.json")
else
  echo "No --uptime-check-id given; skipping alert-uptime.json." >&2
fi

for policy in "${POLICIES[@]}"; do
  file="$MON_DIR/$policy"
  [[ -f "$file" ]] || { echo "Missing $file" >&2; exit 1; }
  echo "=== $policy ==="
  if [[ "$DRY_RUN" -eq 1 ]]; then
    render "$file"
    echo
    continue
  fi
  tmp="$(mktemp)"
  render "$file" > "$tmp"
  gcloud monitoring policies create --project "$PROJECT" --policy-from-file "$tmp"
  rm -f "$tmp"
done

echo "Done."
