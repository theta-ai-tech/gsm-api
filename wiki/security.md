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

### Dev Rules

`firestore.rules.dev` contains allow-all rules for reference. The emulator admin REST
endpoint (`http://127.0.0.1:8082/emulator/v1/...`) provides unrestricted emulator access
without needing to swap rule files.

### Verification

```bash
# After make emu-all is running:
bash scripts/verify_firestore_rules.sh
```

### Deployment

```bash
# Deploy rules to dev project:
make deploy-rules-dev

# Deploy rules to prod (manual, with care):
firebase deploy --only firestore:rules --project gsm-prod
```
