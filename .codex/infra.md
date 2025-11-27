
# GSM – Infra Defaults (Dev Phase)

- **Project (dev):** `gsm-dev-f70d0`
- **Region:** `europe-west8` for Cloud Run, Firestore, Artifact Registry, Functions
- **Service Accounts**
  - Runtime (Cloud Run): `gsm-api-runtime@<PROJECT>.iam.gserviceaccount.com`  
    - Grant when needed: `roles/datastore.user`
  - Deployer (CI/CD): `gsm-api-deployer@<PROJECT>.iam.gserviceaccount.com`  
    - Roles: `roles/run.admin`, `roles/artifactregistry.writer`; and `roles/iam.serviceAccountUser` on runtime SA
- **CI/CD:** GitHub Actions (CI on PRs; Deploy on push to `main` via WIF)
- **Scaling (Cloud Run):** `min=0`, `max=10`, `concurrency=80`, `cpu=1`, `memory=512Mi`
- **Ingress:** public (dev); protection done at route level (Firebase ID token)
- **Config/Secrets:** env vars for non-secrets; **Secret Manager** for secrets (later)
- **Handy**
  - Service URL: `gcloud run services describe gsm-api --region europe-west8 --format='value(status.url)'`
  - Update scaling: `gcloud run services update gsm-api --region europe-west8 --concurrency 80 --cpu 1 --memory 512Mi --min-instances 0 --max-instances 10`

## Run with Firestore emulator

Terminal A:

```bash
make emu-firestore
```

Terminal B:

```bash
make api-dev-emu
# Health: http://localhost:8000/health
```

## Docker (optional)

```bash
make docker-build        # or: make docker-build-amd64 (Apple Silicon)
make docker-run          # http://127.0.0.1:8080/health
```

## Env vars (emulator)

* `FIRESTORE_EMULATOR_HOST=127.0.0.1:8082`
* `GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0`