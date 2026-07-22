# Firestore backups — PITR + scheduled exports (#378)

User-generated data (journals, matches, rankings) must be recoverable at launch.
Two independent layers:

1. **Point-in-Time Recovery (PITR)** — continuous, ~7-day rolling window for
   fine-grained "oops" recovery (recover the DB to any microsecond in the window).
2. **Scheduled daily exports to GCS** — coarse, longer-horizon snapshots with
   30-day retention, restorable into any project (also the DR / migration path).

---

## Layer 1 — PITR

**Operator action** (enables a billable feature — not run by CI):
```bash
gcloud firestore databases update \
  --project "$PROD_PROJECT_ID" \
  --database "(default)" \
  --enable-pit-recovery

# Verify:
gcloud firestore databases describe --project "$PROD_PROJECT_ID" --database "(default)" \
  --format='value(pointInTimeRecoveryEnablement)'   # -> POINT_IN_TIME_RECOVERY_ENABLED
```

Restore to a point in time (creates a NEW database from the snapshot; you then
swap the app over):
```bash
gcloud firestore databases restore \
  --source-database="(default)" \
  --snapshot-time="2026-07-21T10:00:00Z" \
  --destination-database="recovered-20260721" \
  --project "$PROD_PROJECT_ID"
```

---

## Layer 2 — Scheduled GCS exports

### Bucket + lifecycle (operator action, once)
```bash
# Same region as Firestore; uniform bucket-level access.
gsutil mb -p "$PROD_PROJECT_ID" -l "$REGION" -b on \
  "gs://gsm-prod-firestore-backups"

# 30-day retention (config committed at deploy/backup-bucket-lifecycle.json):
gsutil lifecycle set deploy/backup-bucket-lifecycle.json \
  "gs://gsm-prod-firestore-backups"

# Grant the backup service account permission to export + write:
gcloud projects add-iam-policy-binding "$PROD_PROJECT_ID" \
  --member "serviceAccount:$GCP_SERVICE_ACCOUNT" --role roles/datastore.importExportAdmin
gsutil iam ch "serviceAccount:$GCP_SERVICE_ACCOUNT:roles/storage.objectAdmin" \
  "gs://gsm-prod-firestore-backups"
```

`tests/tools/test_backup_lifecycle.py` pins the lifecycle to a 30-day Delete rule,
so an accidental unbounded-bucket edit fails CI.

### The daily job
`.github/workflows/firestore-backup.yml` runs `scripts/firestore_export.sh` at
03:17 UTC daily against the `prod` environment. Each run exports to
`gs://<bucket>/scheduled/<UTC-timestamp>/` — a self-contained, restorable snapshot.

- Set the prod-environment secret `BACKUP_BUCKET=gsm-prod-firestore-backups`.
- Until that secret is set, the scheduled run is a **clean no-op** (the `check`
  job skips the export instead of failing), so this can merge before prod exists.
- Manual run: **Actions → "Firestore scheduled backup (prod)" → Run workflow**.
- Local/manual: `./scripts/firestore_export.sh --project <id> --bucket <bucket>`.

Alternative to GitHub's scheduler (if you prefer GCP-native scheduling): a Cloud
Scheduler job hitting the Firestore export Admin API, or
`gcloud firestore databases backup-schedules create` (native scheduled backups).
The GH Actions cron is chosen here to match the repo's WIF-based CI ops.

---

## Restore (one-liner)

From a scheduled export:
```bash
gcloud firestore import "gs://gsm-prod-firestore-backups/scheduled/<TIMESTAMP>" \
  --project "$TARGET_PROJECT_ID"
```
(`import` merges into the target database. To restore cleanly, import into a fresh
database or project, then repoint the service.)

---

## ⚠️ Operator actions summary (run manually — none executed by CI)
1. Enable **PITR** on the prod database.
2. Create the **backups bucket** + apply `deploy/backup-bucket-lifecycle.json`
   (30-day retention) + grant the backup SA export/write IAM.
3. Set the prod-env secret **`BACKUP_BUCKET`** so the daily workflow runs.
4. Verify the first scheduled export lands in the bucket:
   `gsutil ls gs://gsm-prod-firestore-backups/scheduled/`.

Acceptance: PITR on; first scheduled export present in the bucket; restore
procedure documented above.
