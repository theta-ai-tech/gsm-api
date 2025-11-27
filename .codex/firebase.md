# GSM – API Auth (Firebase ID Token)

## Contract
- Read header: `Authorization: Bearer <ID_TOKEN>`
- Verify via `firebase_admin.auth.verify_id_token(token)`
- On success: attach `request.state.uid = decoded['uid']`
- On failure: return `401` with `WWW-Authenticate: Bearer`

## Notes
- Initialize `firebase_admin.initialize_app()` **once** at import
- SDK caches Google JWKS and handles rotation/clock skew
- Never log raw tokens; log minimal context only

## Example
```bash
curl -i -H "Authorization: Bearer <ID_TOKEN>" https://<service-url>/health
# 200 OK when valid; 401 when missing/invalid