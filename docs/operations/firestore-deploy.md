# Firestore rules & indexes deployment

`firestore.rules` and `firestore.indexes.json` live in the repo but, before this
pipeline, nothing deployed them — so index/rules drift between the repo and a live
project stayed invisible until a query 500'd in production. This doc covers the
delivery pipe that keeps a target project's rules + indexes in sync with the repo.

---

## What deploys, and where from

| File | Purpose | Deployed to |
|---|---|---|
| `firestore.rules` | **Deny-all** security rules (the canonical, prod rules) | dev **and** prod |
| `firestore.indexes.json` | Composite index definitions | dev **and** prod |
| `firestore.rules.dev` | Permissive rules for **local emulator only** | never deployed |

The access model is API-only: iOS → FastAPI → Firebase Admin SDK → Firestore. The
Admin SDK bypasses security rules, so **deny-all is the correct rule set for both
live environments** — there is no per-environment rules file. `firestore.rules.dev`
is a local convenience for direct emulator pokes and is never shipped.

---

## The pipeline

Workflow: `.github/workflows/firestore-deploy.yml`, gated exactly like the service
deploy (see `deployment.md`):

- **push to `main`** touching `firestore.rules` / `firestore.indexes.json` /
  `firebase.json` → auto-deploys to **dev**.
- **workflow_dispatch (dev)** → manual deploy to dev.
- **workflow_dispatch (prod)** → deploys to prod, **gated by the `prod` GitHub
  Environment's required reviewers** (manual approval).

Each run:
1. Validates `firestore.indexes.json` (`tools/verify_firestore_indexes.py`) — the
   file must parse and must still declare the broadcasts-feed composite index
   (#290). A malformed or regressed indexes file fails **before** touching a live
   project.
2. Runs `firebase deploy --only firestore:rules,firestore:indexes`. Firebase
   compiles the rules server-side and exits non-zero on a compile error, so an
   invalid `firestore.rules` **fails the job loudly**.

---

## One command to bring a project in sync

Local (requires ADC / `gcloud auth application-default login` and Firebase CLI):

```bash
# Dev
make deploy-firestore-dev

# Prod (prefer the gated workflow; this is the break-glass local path)
make deploy-firestore-prod PROD_PROJECT_ID=gsm-prod-xxxxx
```

Validate the indexes file without deploying anything:

```bash
make verify-indexes
```

---

## broadcasts-feed composite index (#290)

The Play-tab broadcasts feed queries `broadcasts` by `status == "open"` ordered by
`createdAt DESC`, which needs a composite index. It is declared in
`firestore.indexes.json` as:

```json
{ "collectionGroup": "broadcasts", "queryScope": "COLLECTION",
  "fields": [ { "fieldPath": "status",    "mode": "ASCENDING"  },
              { "fieldPath": "createdAt", "mode": "DESCENDING" } ] }
```

`tools/verify_firestore_indexes.py` asserts this specific index is present, so a
future edit that drops it fails CI (`tests/tools/test_firestore_indexes.py`) and
the deploy workflow rather than surfacing as a 500 in prod. (#290 remains the
tracking issue for *declaring* the index; this pipeline is the *delivery*.)

---

## ⚠️ Operator actions required (run manually)

- The `prod` GitHub Environment + required reviewers must exist for the prod path
  to be gated (shared with the service-deploy setup — see
  `deployment.md`).
- The deployer service account for each environment needs
  `roles/datastore.indexAdmin` and `roles/firebaserules.admin` (or
  `roles/cloudfirestore.admin`) on its project to deploy indexes + rules.
