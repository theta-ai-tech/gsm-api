# Deployment (dev / prod)

This doc covers how the GSM API service (Cloud Run) and the Firebase Functions
deploy to **two environments** — `dev` and `prod` — and how to promote and roll
back each one.

Core principle: **build once, promote the same artifact.** The dev pipeline
builds an immutable container image and deploys it to dev automatically. Prod is
a manually-approved promotion of that *already-built* image — prod never rebuilds
from source.

---

## Topology

| Concern | dev | prod |
|---|---|---|
| Cloud Run service | auto-deploy on push to `main` | manual, approval-gated promotion |
| Firebase Functions | auto-deploy on push to `main` | manual, approval-gated deploy |
| Image source | built by `deploy.yml` | **same digest** promoted by `promote-prod.yml` |
| Approval | none | GitHub Environment `prod` required reviewers |
| Functions rev log | `deploy/last_good_revision_dev.txt` | `deploy/last_good_revision_prod.txt` |

Workflows:
- `.github/workflows/deploy.yml` — build image + deploy to **dev** Cloud Run (push to main).
- `.github/workflows/promote-prod.yml` — promote an already-built image to **prod** Cloud Run (manual).
- `.github/workflows/functions-deploy.yml` — functions deploy: dev on push to main, prod on manual dispatch.
- `.github/workflows/functions-rollback.yml` — functions rollback, per environment.

---

## How the split works (secrets & environments)

GitHub **Environment secrets** override repo secrets when a job declares
`environment: <name>`. We rely on that to point the same workflow at different
GCP projects:

**Per-environment secrets** (defined under Settings → Environments → `dev` / `prod`):

| Secret | Meaning |
|---|---|
| `GCP_PROJECT_ID` | The Firebase/GCP runtime project for that env |
| `SERVICE_NAME` | Cloud Run service name (defaults to `gsm-api`) |
| `GCP_REGION` | Cloud Run + AR region (e.g. `europe-west8`) |
| `GCP_WIF_PROVIDER` | Workload Identity Federation provider for that env |
| `GCP_SERVICE_ACCOUNT` | Deployer service account for that env |

**Repo-level secrets** (shared across envs, Settings → Secrets → Actions):

| Secret | Meaning |
|---|---|
| `AR_PROJECT_ID` | Project that hosts the shared Artifact Registry. **Required** for prod promotion — dev and prod must pull from the *same* registry so the identical digest is promoted. If unset, the dev build falls back to `GCP_PROJECT_ID` (single-env dev works, but prod promotion cannot find the image). |
| `AR_REPO` | Artifact Registry repository name (defaults to `gsm-api`). |

---

## Promote to prod (Cloud Run)

1. A push to `main` runs `deploy.yml`: it builds `…/gsm-api:<sha>`, pushes it to
   the shared registry, resolves the immutable digest, and deploys that digest to
   **dev**. Note the `<sha>` (it is the commit SHA).
2. Go to **Actions → "Promote to Cloud Run (prod)" → Run workflow**.
3. Enter `image_sha` = the commit SHA you want to promote (defaults to the current
   `main` SHA). The workflow verifies the image exists (fails loudly if that SHA
   was never built) and resolves it to a digest.
4. Because the job targets the `prod` Environment, GitHub **pauses for approval**.
   A required reviewer approves.
5. The job deploys the exact same image digest to the **prod** Cloud Run service.

---

## Roll back

### Cloud Run (either env)
Cloud Run keeps every revision. Roll back by shifting traffic — no rebuild:

```bash
# List revisions
gcloud run revisions list --service <SERVICE_NAME> --region <REGION> --project <PROJECT_ID>

# Send 100% traffic to a known-good revision
gcloud run services update-traffic <SERVICE_NAME> \
  --region <REGION> --project <PROJECT_ID> \
  --to-revisions <GOOD_REVISION>=100
```

(For prod, run against the prod `PROJECT_ID`/`SERVICE_NAME`; approval is not
required for a traffic split, but coordinate per your change policy.)

### Firebase Functions (either env)
Use the rollback workflow, which redeploys a known-good git revision from the
matching `deploy/last_good_revision_<env>.txt`:

**Actions → "Rollback Firebase Functions (manual)" → Run workflow**, choose
`environment` (`dev`/`prod`) and optionally a specific `revision`. Prod is
approval-gated.

Locally (dev):
```bash
./scripts/rollback_functions.sh --project <dev-project> --env dev
```

---

## ⚠️ Operator actions required (run manually — not automated by CI)

These provision real cloud + GitHub resources and are **intentionally not run by
this change**. Do them once per environment before the workflows can succeed.

### 1. Create the GitHub Environments + approval gate
```bash
# dev — no reviewers
gh api -X PUT repos/theta-ai-tech/gsm-api/environments/dev

# prod — require manual approval (replace REVIEWER_USER_ID with a real user id;
# get it via: gh api users/<login> --jq .id)
gh api -X PUT repos/theta-ai-tech/gsm-api/environments/prod \
  -f 'reviewers[][type=User]' -F 'reviewers[][id]=REVIEWER_USER_ID' \
  -F 'deployment_branch_policy[protected_branches]=true' \
  -F 'deployment_branch_policy[custom_branch_policies]=false'
```
Or via UI: Settings → Environments → New environment → `prod` → enable
"Required reviewers".

### 2. Add the per-environment secrets
```bash
# Repeat for dev and prod with their respective values
gh secret set GCP_PROJECT_ID     --env prod --body "gsm-prod-xxxxx"
gh secret set SERVICE_NAME       --env prod --body "gsm-api"
gh secret set GCP_REGION         --env prod --body "europe-west8"
gh secret set GCP_WIF_PROVIDER   --env prod --body "projects/<num>/locations/global/workloadIdentityPools/<pool>/providers/<provider>"
gh secret set GCP_SERVICE_ACCOUNT --env prod --body "gsm-deployer@gsm-prod-xxxxx.iam.gserviceaccount.com"

# Shared registry (repo scope)
gh secret set AR_PROJECT_ID --body "gsm-dev-f70d0"   # or a dedicated artifacts project
gh secret set AR_REPO       --body "gsm-api"
```

### 3. Provision the prod GCP project
- Create the prod project + Firestore (Native mode) in the prod region.
- Create the Cloud Run runtime SA: `gsm-api-runtime@<prod>.iam.gserviceaccount.com`.
- Create the deployer SA + WIF provider bound to this repo (mirror the dev setup
  in `docs/operations/credentials.md`).
- Grant the prod Cloud Run runtime SA **read** on the shared Artifact Registry so
  it can pull the promoted image:
  ```bash
  gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" \
    --project "$AR_PROJECT_ID" --location "$REGION" \
    --member "serviceAccount:gsm-api-runtime@<prod>.iam.gserviceaccount.com" \
    --role roles/artifactregistry.reader
  ```
- Grant the prod deployer SA `roles/run.admin` + `roles/iam.serviceAccountUser`
  on the prod project, and `roles/artifactregistry.reader` on the shared registry.
- Ensure the **dev** deployer SA has `roles/artifactregistry.writer` on the shared
  registry (it builds and pushes the image that prod later promotes).

---

## Functions deploy internals (unchanged mechanics)

`scripts/deploy_functions.sh` and `scripts/rollback_functions.sh` now take an
`--env <dev|prod>` flag that selects the `deploy/last_good_revision_<env>.txt`
log. Prod skips the post-deploy smoke by default (it writes synthetic data);
set `FORCE_SMOKE=1` to run it anyway. Everything else (revision stamping,
worktree-based rollback, smoke on dev) works as before.
