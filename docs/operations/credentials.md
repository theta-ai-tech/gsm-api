# Credentials & Environments

This repo intentionally avoids committing any JSON service account keys or `.env.local` files. How credentials are provided depends on where you run:

- **Local dev (Firestore emulator) – `make api-dev`**  
  - Sets `FIREBASE_PROJECT_ID`, `GOOGLE_CLOUD_PROJECT`, `FIRESTORE_EMULATOR_HOST`.  
  - Firestore/Auth traffic goes to the emulator only; no JSON key is needed or used.

- **Local dev (real Firestore, optional) – `make api-dev-real`**  
  - Expects `FIREBASE_PROJECT_ID`/`GOOGLE_CLOUD_PROJECT`.  
  - You must provide Application Default Credentials: either run `gcloud auth application-default login` or set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/your-sa.json` in your shell. The path is your choice and never committed.

- **CI (GitHub Actions)**  
  - Starts the Firestore emulator and sets `FIRESTORE_EMULATOR_HOST`, `GOOGLE_CLOUD_PROJECT`, `FIREBASE_PROJECT_ID`.  
  - No JSON keys; tests hit the emulator only.

- **Prod (Cloud Run)**  
  - Uses Application Default Credentials via Workload Identity on the service account configured for the service.  
  - Set `FIREBASE_PROJECT_ID` (and `GOOGLE_CLOUD_PROJECT` if desired) in service config. No JSON key files in the container.

Summary: emulator flows (local + CI) never need keys; prod uses Workload Identity ADC; real-Firestore local runs require you to supply ADC yourself via `gcloud auth application-default login` or a local `GOOGLE_APPLICATION_CREDENTIALS` path.***
