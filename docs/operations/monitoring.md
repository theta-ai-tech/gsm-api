# Production monitoring, alerting & error reporting (#376)

What pages us when the GSM API or its Cloud Functions break, and how it's wired.
Structured logging, request tracing, and slow-request logging are covered in
`observability.md`; this doc adds uptime, alerts, and Error Reporting.

---

## Error Reporting (app code)

The app already logs 5xx with a traceback (`observability.py`). For those to be
**grouped in Cloud Error Reporting**, they must reach Cloud Logging at severity
`ERROR` — plain stdout on Cloud Run is ingested at `DEFAULT` and not reliably
grouped. `app/telemetry.py::setup_cloud_logging()` attaches the
`google-cloud-logging` handler, which maps Python levels to Cloud Logging
severities.

- **Enabled automatically on Cloud Run** (`K_SERVICE` is set there). Force with
  `GSM_ENABLE_CLOUD_LOGGING=1`; force off with `GSM_ENABLE_CLOUD_LOGGING=0`.
- No-op in tests/local, and initialization failures are swallowed so startup can
  never break.

Verify after deploy: trigger a handled 5xx (or check the logs for a real one) and
confirm it appears under **Error Reporting** in the Cloud Console for the project.

---

## Uptime check

Target the existing liveness probe. (The issue calls it `/healthz`; this service
exposes the equivalent at **`GET /health`** — public, no external deps, 200 when
the process is up. No new endpoint is added.)

Operator action — create the uptime check (note the returned check id):
```bash
gcloud monitoring uptime create "gsm-api-health" \
  --project "$PROJECT_ID" \
  --resource-type=uptime-url \
  --resource-labels=host=<CLOUD_RUN_HOST>,project_id=$PROJECT_ID \
  --path="/health" --port=443 --protocol=https \
  --period=1 --timeout=10
# Capture the check id:
gcloud monitoring uptime list-configs --project "$PROJECT_ID"
```

---

## Alert policies (committed as code)

Policy definitions live in `monitoring/*.json` with substitutable placeholders:

| File | Fires when |
|---|---|
| `alert-uptime.json` | uptime check on `/health` not passing |
| `alert-5xx-rate.json` | Cloud Run 5xx rate > 0.1/s for 5m |
| `alert-p95-latency.json` | Cloud Run p95 latency > 2000ms for 5m |
| `alert-function-failures.json` | Cloud Function executions with `status != ok` |
| `alert-firestore-quota.json` | Firestore reads > 500/s or writes > 200/s for 5m |

`tests/tools/test_monitoring_policies.py` validates each file parses and is
well-formed, so a broken policy fails CI before an operator applies it.

Thresholds are sensible starting points — **tune to the observed baseline** after
launch.

Apply them (operator action — creates billable resources, not run by CI):
```bash
# Preview the substituted JSON without creating anything:
./scripts/apply_monitoring.sh --project "$PROJECT_ID" \
  --channel "projects/$PROJECT_ID/notificationChannels/<CHANNEL_ID>" \
  --service gsm-api --uptime-check-id <UPTIME_CHECK_ID> \
  --runbook "https://github.com/theta-ai-tech/gsm-api/blob/main/docs/operations/monitoring.md" \
  --dry-run

# Create the policies (drop --dry-run):
./scripts/apply_monitoring.sh --project "$PROJECT_ID" \
  --channel "projects/$PROJECT_ID/notificationChannels/<CHANNEL_ID>" \
  --service gsm-api --uptime-check-id <UPTIME_CHECK_ID> \
  --runbook "https://github.com/theta-ai-tech/gsm-api/blob/main/docs/operations/monitoring.md"
```

---

## Notification channel (email)

Operator action — create the email channel and capture its id for `--channel`:
```bash
gcloud beta monitoring channels create \
  --project "$PROJECT_ID" \
  --display-name="GSM on-call" \
  --type=email \
  --channel-labels=email_address=oncall@example.com
gcloud beta monitoring channels list --project "$PROJECT_ID"   # copy the name: projects/…/notificationChannels/ID
```
Email now; upgrade to PagerDuty/Slack/SMS later by adding channels and passing
multiple `--channel` values (extend the script's single-channel placeholder to a
list when that time comes).

---

## ⚠️ Operator actions summary (run manually — none executed by CI)
1. Create the email **notification channel** → capture its resource name.
2. Create the **uptime check** on `/health` → capture its check id.
3. Run `scripts/apply_monitoring.sh` with the project, channel, service, and
   uptime-check id to create all alert policies.
4. Ensure **Error Reporting API** is enabled on the project (`gcloud services
   enable clouderrorreporting.googleapis.com`); on Cloud Run the app enables the
   Cloud Logging handler automatically.

Acceptance: killing the service (uptime alert) or a failing leaderboard run
(function-failures alert) pages the notification channel within minutes; each
alert's documentation links back to this runbook.
