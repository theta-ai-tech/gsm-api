# Push Notification Delivery Design

**Status:** Implemented. This file is the design decision record for the backend-owned delivery
architecture. For the live API/trigger contract and operator runbook, see
[`../api/notifications.md`](../api/notifications.md).
**Epic:** [#329 (NTF-2)](https://github.com/theta-ai-tech/gsm-api/issues/329).
**Child issues:** PUSH-1 … PUSH-7 (label `push-notifications`), now landed.

This is the design record for turning the **notification-intent contract** into actual push
notifications delivered to phones. It is intentionally architectural; operational details and exact
field behavior live in the API documentation.

---

## 1. Goal & decision record

### The gap

The backend writes a `PlayNotificationIntent` document on every notification-worthy event
(`api/app/repos/notification_intent_repo.py` → `users/{uid}/notificationIntents/{intentId}`). Before
NTF-2, intents were durable but not delivered: no device token was stored on the user, and no code
called FCM. The launch-readiness eval (2026-06-01) flagged this gap.

### The decision: backend-owned delivery (option b)

NTF-2 posed two options:

- **(a)** Treat intents as a client contract: iOS listens on `users/{uid}/notificationIntents` and
  surfaces notifications itself. Document it and close.
- **(b)** Build a delivery slice: store device tokens on the user, add a Firestore-triggered Cloud
  Function that calls FCM when an intent is written.

**We chose (b).** A client-side Firestore listener only runs while the app is **open / foregrounded**.
The entire value of a push notification ("you got a match offer!", "confirm the score") is that it
reaches the user when the app is **closed or backgrounded** — exactly when a listener is dead. Only a
server calling FCM/APNs can wake a backgrounded device. Option (a) would document the gap as
intentional rather than close it. Option (b) closes it server-side and leaves iOS a single, small job:
register its device token.

### Scope & sequencing

Delivery now exists in the backend. iOS still owns acquiring the APNs/FCM token and registering it
with the backend via the device-token API.

---

## 2. Architecture

```
 ┌─────────────────────────────┐
 │ Business event              │   POST /me/offers, accept offer,
 │ (play / match services)     │   first verify-score …
 └──────────────┬──────────────┘
                │ writes (fire-and-forget, already exists today)
                ▼
 ┌─────────────────────────────────────────────┐
 │ users/{uid}/notificationIntents/{intentId}  │  PlayNotificationIntent
 │   type, title, body, dedupeKey, targetUid,  │  (title/body already human-readable)
 │   offerId | matchId, createdAt              │
 └──────────────┬──────────────────────────────┘
                │ @on_document_created  (PUSH-4)
                ▼
 ┌─────────────────────────────────────────────┐
 │ notification_triggers handler               │
 │  1. kill switch (GSM_TRIGGERS_ENABLED)      │
 │  2. idempotency guard (deliveredAt unset)   │  PUSH-5
 │  3. read users/{uid}.deviceTokens           │  PUSH-1
 │  4. build messaging.MulticastMessage        │
 │  5. messaging.send_each_for_multicast(...)  │  PUSH-3
 │  6. prune UNREGISTERED / invalid tokens     │  PUSH-1 + PUSH-3
 │  7. stamp intent deliveredAt / status       │  PUSH-5
 │  8. log_event(trigger=…, sent, pruned)      │
 └──────────────┬──────────────────────────────┘
                ▼
         FCM  ──►  APNs / Android  ──►  device
```

Device tokens arrive separately, from the client:

```
 iOS app ──POST /me/device-tokens {token, platform}──►  users/{uid}.deviceTokens[]   (PUSH-2)
 iOS app ──DELETE /me/device-tokens {token} on logout─►  removed                      (PUSH-2)
```

The intent write path (left of the trigger) is **unchanged** — it already exists and is
fire-and-forget. Everything new hangs off the trigger and the token store.

---

## 3. Device token model (PUSH-1)

Stored on the user document `users/{uid}`:

```jsonc
"deviceTokens": [
  {
    "token":     "fcm-registration-token-string",
    "platform":  "ios",          // ios | android
    "createdAt": "2026-06-16T10:00:00Z",
    "lastSeenAt":"2026-06-16T10:00:00Z"
  }
]
```

Rules:
- **Dedupe by `token`.** Re-registering an existing token refreshes `lastSeenAt`, does not duplicate.
- A user may have **multiple** tokens (multiple devices). Delivery fans out to all of them.
- Initialised to `[]` at onboarding (`onboarding_service.py` builds the user doc).
- `PrivateUserProfile` (`api/app/models/user.py`) gains an optional `deviceTokens` field so the shape
  is typed and documented. Tokens are **private** — never returned on any public profile.

`UsersRepo` (`api/app/repos/users_repo.py`) gains:
- `upsert_device_token(uid, token, platform)` — idempotent; refresh `lastSeenAt` if present.
- `remove_device_token(uid, token)` — logout / prune.
- `list_device_tokens(uid) -> list[...]` — used by the trigger.

> The trigger runs in `functions/` (separate from the API package). It will read tokens straight from
> the Firestore user doc rather than importing `UsersRepo`, mirroring how existing triggers read docs
> directly (`functions/league_triggers/`). The repo methods serve the API-side registration endpoints
> and pruning calls that originate API-side.

---

## 4. Token registration API (PUSH-2)

A **dedicated** pair of endpoints, not an extension of ONB-1's `RegisterMeRequest`:

| Method & path | Body | Behaviour |
| --- | --- | --- |
| `POST /me/device-tokens` | `{ "token": str, "platform": "ios"\|"android", "appVersion"?: str }` | Idempotent upsert into `deviceTokens`; refresh `lastSeenAt`. `201`/`200`. |
| `DELETE /me/device-tokens` | `{ "token": str }` | Remove on logout / token rotation. `204`. |

Why a dedicated endpoint rather than capturing the token in onboarding:
- **Tokens rotate.** APNs/FCM tokens change (reinstall, OS refresh, restore). A one-shot onboarding
  capture would go stale; the app must be able to refresh at any time.
- **Onboarding happens once**, push permission may be granted later, and the token must be updatable
  on every login. A standalone endpoint is the natural home.

Auth: standard `get_current_user`; a user can only register tokens for themselves. Endpoint documented
in [`../api/endpoints.md`](../api/endpoints.md).

---

## 5. Delivery trigger (PUSH-4)

New package `functions/notification_triggers/`, mirroring `functions/league_triggers/` structure
(`main.py` entrypoint + handler module). Wired in `functions/main.py` with:

```python
@on_document_created(document="users/{uid}/notificationIntents/{intentId}")
```

Handler steps (in order):
1. **Kill switch** — bail if `GSM_TRIGGERS_ENABLED` is off (`functions/runtime_flags.triggers_enabled()`).
2. **Idempotency** — skip if the intent already has `deliveredAt` set (PUSH-5).
3. **Read tokens** — `users/{uid}.deviceTokens`. If empty → log `no_tokens`, stamp delivered, return.
4. **Build payload** — `messaging.Notification(title=intent.title, body=intent.body)`; `data` map
   carries `type`, and `offerId`/`matchId` so the app can deep-link.
5. **Send** — `messaging.send_each_for_multicast(MulticastMessage(tokens=[...], ...))` (PUSH-3).
6. **Prune** — remove tokens FCM reports `UNREGISTERED` / `INVALID_ARGUMENT` (PUSH-1 + PUSH-3).
7. **Stamp** — set `deliveredAt` / `deliveryStatus` on the intent (PUSH-5).
8. **Log** — `log_event(trigger="onNotificationIntentCreate.NTF.1", sent=…, pruned=…, ...)`.

Failure semantics: delivery is **best-effort and fully decoupled**. The intent is already durably
written by the business transaction; a send failure logs and (optionally) leaves `deliveredAt` unset
for a retry, but **never** touches the originating business flow.

---

## 6. Idempotency & dedupe (PUSH-5)

Two distinct concerns:
- **`dedupeKey`** (already on the intent, e.g. `match_scheduled:{matchId}:{uid}`) dedupes at the
  *intent-creation* layer / on the client.
- **`deliveredAt` / `deliveryStatus`** (on the intent doc) dedupes at the *delivery* layer:
  Cloud Functions guarantee at-least-once invocation, so the trigger can fire twice for one write. The
  guard in step 2 ensures we don't double-send. `deliveryStatus` ∈ `{ pending, delivered, no_tokens,
  failed }`.

---

## 7. Invalid-token pruning (PUSH-1 + PUSH-3)

`send_each_for_multicast` returns a per-token `BatchResponse`. For each failed token whose error code
is `UNREGISTERED` (app uninstalled) or `INVALID_ARGUMENT` (malformed/stale), remove that token from
`users/{uid}.deviceTokens`. This keeps the token list clean and avoids repeatedly sending to dead
endpoints. Transient errors (e.g. `UNAVAILABLE`) are **not** pruned.

---

## 8. iOS contract (cross-stream dependency — gates the sprint)

iOS must, before this backend slice is useful:
1. Request notification permission and obtain the **APNs token**, exchanged for an **FCM registration
   token** via the Firebase iOS SDK.
2. `POST /me/device-tokens { token, platform: "ios", appVersion }` on **login** and on every **token
   refresh** callback.
3. `DELETE /me/device-tokens { token }` on **logout**.
4. Handle the incoming push `data` (`type`, `offerId`/`matchId`) to deep-link into the right screen.

Without steps 1–3, `deviceTokens` is empty and the trigger stamps intents as `no_tokens`.

---

## 9. Testing strategy

- **Unit (API):** repo CRUD dedupe/refresh; endpoint auth + idempotent upsert; request validation.
- **Unit (functions):** handler with `messaging.send_each_for_multicast` **mocked** — assert one send
  per valid token, correct payload mapping, kill switch suppresses, `no_tokens` path, idempotency
  guard, invalid-token pruning from the mocked `BatchResponse`.
- **Integration (emulator):** writing an intent doc triggers exactly one send per valid token; invalid
  tokens pruned; `deliveredAt` stamped; second invocation of the same intent does not re-send.
- FCM is **always mocked** — never call the real provider in tests.

---

## 10. Issue map

| Issue | Scope | Key files | Depends on |
| --- | --- | --- | --- |
| **PUSH-1** | Device token storage: model field, onboarding init, `UsersRepo` CRUD, dedupe | `models/user.py`, `services/onboarding_service.py`, `repos/users_repo.py`, `docs/data/data-dictionary.md` | — |
| **PUSH-2** | `POST`/`DELETE /me/device-tokens` endpoints + service | `routers/`, `models/`, `services/`, `docs/api/endpoints.md` | PUSH-1 |
| **PUSH-3** | FCM sender wrapper + invalid-token detection (mockable) | `functions/notification_triggers/fcm_sender.py` | — |
| **PUSH-4** | `@on_document_created` trigger → deliver via FCM; wire in `functions/main.py` | `functions/notification_triggers/`, `functions/main.py`, `docs/architecture/triggers.md` | PUSH-1, PUSH-3 |
| **PUSH-5** | Delivery idempotency: `deliveredAt`/`deliveryStatus`, retry guard | `models/notification.py`, `repos/notification_intent_repo.py`, trigger | PUSH-4 |
| **PUSH-6** | Integration + smoke proof with mocked FCM | `tests/integration/`, `tests/smoke/` | PUSH-4, PUSH-5 |
| **PUSH-7** | Deploy wiring + ops runbook + live delivery docs | `scripts/deploy_functions.sh`, `scripts/smoke_triggers.sh`, `docs/api/notifications.md`, `docs/operations/runbook.md` | PUSH-1…6 |

Dependency order: **PUSH-1 → (PUSH-2 ∥ PUSH-3) → PUSH-4 → PUSH-5 → PUSH-6 → PUSH-7.** Whole epic gated
on iOS shipping token registration.

---

## 11. See also

- [`../api/notifications.md`](../api/notifications.md) — the live intent and delivery contract.
- `api/app/repos/notification_intent_repo.py`, `api/app/models/notification.py` — the existing intent
  write path.
- `functions/league_triggers/` — the Firestore-trigger handler pattern this delivery trigger mirrors.
- `functions/runtime_flags.py`, `functions/logging_utils.py` — kill switch + structured logging
  conventions.
