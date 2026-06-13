# Security Rules

## Firestore Security Rules

### Access Model

GSM uses a REST-only access model (confirmed 2026-06-13):

```
iOS client → FastAPI REST endpoints → Firebase Admin SDK → Firestore
```

- The iOS client never reads or writes Firestore directly via the Firebase SDK.
- All data access goes through the FastAPI API.
- The Firebase Admin SDK bypasses Firestore security rules in both production and emulator.

### Production Rules

`firestore.rules` contains `allow read, write: if false` — deny-all for direct clients.
This is correct because no client ever needs direct Firestore access. The Admin SDK
still works normally.

### When to Update Rules

If direct Firebase SDK access is ever added (e.g. for real-time notification delivery
or live feed, as discussed in issue #329 NTF-2), the rules must be updated before
deploying to include per-collection, per-field grants. At that point, use granular rules
that:
- Allow users to read their own `users/{uid}` doc and subcollections
- Block writes to server-authoritative fields: `rankings.*`, `registrationTier`, `playTab`, `stats`
- Allow users to read `leagues/*` and `matches/*` they participate in (by UID membership)

### Dev Rules and Smoke Testing

`firestore.rules.dev` contains allow-all rules for local debugging. `firebase.smoke.json`
references it so the emulator can be started with those rules for smoke test runs:

```bash
# Start emulator with allow-all rules — use this when running smoke tests:
make emu-smoke

# Start emulator with deny-all rules — use this for all other dev work:
make emu-all
```

Smoke scripts (`tests/smoke/pr-*.sh`) make direct Firestore REST calls for test setup and
teardown. These calls hit `/v1/...` which enforces security rules. With deny-all rules active
(`make emu-all`), setup calls return `PERMISSION_DENIED`. Use `make emu-smoke` instead when
running smoke scripts.

Integration tests (`make test`) are unaffected — they use `google.cloud.firestore.Client`
which bypasses rules in the emulator regardless of which rules file is active.

### Verification

```bash
# After make emu-all is running (deny-all rules active):
bash scripts/verify_firestore_rules.sh
```

### Deployment

```bash
# Deploy rules to dev project:
make deploy-rules-dev

# Deploy rules to prod (manual, with care):
firebase deploy --only firestore:rules --project gsm-prod
```
