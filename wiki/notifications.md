# Notification Intents

## Overview

The notification intent contract is a provider-agnostic layer that decouples business-logic events from push notification delivery. When a relevant play state transition occurs, the backend writes a **PlayNotificationIntent** document to a per-user Firestore subcollection. **Delivery is now backend-owned (shipped):** a Cloud Function trigger (`onNotificationIntentCreated`) listens on that subcollection and delivers the push directly via Firebase Cloud Messaging (FCM). The mobile client never has to poll or translate intents to drive push.

The end-to-end path is: an intent doc is written to `users/{uid}/notificationIntents/{intentId}` → the `onNotificationIntentCreated` trigger fires → it reads the target user's `deviceTokens` → sends an FCM multicast via the sender → prunes any invalid tokens → stamps the intent with `deliveredAt` and a terminal `deliveryStatus`. See [Delivery (shipped)](#delivery-shipped) and the [Operator Runbook](#operator-runbook) below.

This approach means:
- The intent contract still decouples business logic from the delivery mechanism — writers only create an intent doc; they never call FCM.
- Notification *creation* logic is testable without a push provider (delivery is exercised separately via the trigger).
- The backend intent write is always **fire-and-forget** — a failure to write never breaks the main transactional flow, and delivery (the trigger) is likewise best-effort and can never roll back the originating transaction.

## Firestore Path

```
users/{uid}/notificationIntents/{intentId}
```

Each document represents one intent for the user identified by `uid`. The `intentId` is an auto-generated Firestore document ID.

## Document Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string (enum) | yes | Intent type. See intent types below. |
| `targetUid` | string | yes | UID of the user this intent is for. |
| `title` | string | yes | Short notification title (localizable by the client). |
| `body` | string | yes | Notification body text (localizable by the client). |
| `dedupeKey` | string | yes | Stable key for deduplication. Format: `{type}:{entityId}:{uid}`. |
| `createdAt` | timestamp | yes | UTC timestamp when the intent was written. |
| `offerId` | string | conditional | Set for `incoming_offer`. |
| `matchId` | string | conditional | Set for `match_scheduled` and `score_confirm_required`. |
| `broadcastId` | string | optional | Source broadcast ID, if applicable. |
| `deliveryStatus` | string (enum) | yes | Delivery-layer state: `pending` (written at creation), `delivered`, `no_tokens`, or `failed`. Stamped by the delivery trigger (PUSH-5) after each send attempt. |
| `deliveredAt` | timestamp | optional | UTC timestamp when the delivery trigger finished handling the intent. Absent until a send attempt completes. Acts as the delivery-layer idempotency guard. |

### Delivery idempotency (PUSH-5)

Cloud Functions triggers are at-least-once, so the delivery trigger
(`functions/notification_triggers/on_notification_intent.py`) may fire more than once for a
single intent write. To avoid duplicate pushes the trigger skips any intent that already
has a non-null `deliveredAt`, and after every terminal outcome it stamps the intent doc with
`deliveredAt` plus a `deliveryStatus` of `delivered`, `no_tokens`, or `failed`. This is
distinct from `dedupeKey`, which dedupes at the creation layer. Stamp writes are best-effort:
a stamp failure is logged but never raised.

## Intent Types

### `incoming_offer`

**When emitted:** After `POST /me/offers` completes successfully — i.e., after the transactional write that creates the offer document.

**Target:** The recipient of the offer (`toUid`).

**Fields set:** `offerId`, optionally `broadcastId`.

**Example document:**

```json
{
  "type": "incoming_offer",
  "targetUid": "user_abc",
  "title": "New match offer",
  "body": "Ignatios C. wants to play with you",
  "offerId": "offer_xyz",
  "broadcastId": "broadcast_123",
  "dedupeKey": "incoming_offer:offer_xyz",
  "createdAt": "2026-05-30T14:00:00Z"
}
```

---

### `match_scheduled`

**When emitted:** After `POST /me/offers/{offerId}/accept` completes — once for every participant in the newly created match (2 for singles, 4 for doubles).

**Target:** Each participant UID.

**Fields set:** `matchId`.

**Example document:**

```json
{
  "type": "match_scheduled",
  "targetUid": "user_abc",
  "title": "Match confirmed!",
  "body": "Your match is on Jun 01 at 10:00 UTC",
  "matchId": "match_offer_xyz",
  "dedupeKey": "match_scheduled:match_offer_xyz:user_abc",
  "createdAt": "2026-05-30T14:05:00Z"
}
```

---

### `score_confirm_required`

**When emitted:** After a first score submission (`POST /matches/{matchId}/verify-score` when the match is `scheduled`). Emitted for every non-submitting participant.

- **Singles:** 1 intent — for the opponent.
- **Doubles:** 3 intents — for the 3 players who did not submit.

**Target:** Each non-submitting participant UID.

**Fields set:** `matchId`.

**Example document:**

```json
{
  "type": "score_confirm_required",
  "targetUid": "user_def",
  "title": "Score submitted",
  "body": "Confirm the match result",
  "matchId": "match_offer_xyz",
  "dedupeKey": "score_confirm_required:match_offer_xyz:user_def",
  "createdAt": "2026-05-30T16:30:00Z"
}
```

---

## Delivery (shipped)

Delivery is owned by the backend and runs as a Cloud Function (Gen 2) trigger. The code lives in `functions/notification_triggers/`:

- `on_notification_intent.py` — `deliver_notification_intent()`, the delivery handler.
- `fcm_sender.py` — `send()`, the FCM multicast sender with invalid-token detection.

The trigger is wired in `functions/main.py` as `on_notification_intent_created`, bound to `users/{uid}/notificationIntents/{intentId}` via `@on_document_created`. It ships as part of `firebase deploy --only functions` (see `scripts/deploy_functions.sh`); there is no separate deploy target.

### End-to-end path

1. **Intent written.** A play state transition makes the backend write an intent doc to `users/{uid}/notificationIntents/{intentId}` with `deliveryStatus: pending` and no `deliveredAt` (`api/app/repos/notification_intent_repo.py`).
2. **Trigger fires.** `onNotificationIntentCreated` runs on the create event.
3. **Kill-switch check.** If `GSM_TRIGGERS_ENABLED` is falsy the handler logs `action="ignore"` (`reason="triggers_disabled"`) and returns without sending or stamping.
4. **Idempotency guard.** Cloud Functions are at-least-once. If the intent already has a non-null `deliveredAt`, the handler logs `action="skip"` (`reason="already_delivered"`) and returns — no duplicate push.
5. **Token lookup.** The handler reads `users/{uid}.deviceTokens`. With no tokens it logs `action="skip"` (`reason="no_tokens"`), stamps `deliveryStatus="no_tokens"` + `deliveredAt`, and returns.
6. **FCM multicast.** With tokens, it builds an FCM payload (`title`, `body`, and a string `data` map carrying `type` + any of `offerId`/`matchId`/`broadcastId`) and sends via `fcm_sender.send()`.
7. **Invalid-token pruning.** Tokens that fail with a permanently-invalid error (`UNREGISTERED`, `SenderIdMismatch`, or per-token `INVALID_ARGUMENT`) are pruned from `users/{uid}.deviceTokens`. If a send raises, the handler stamps `deliveryStatus="failed"` and returns.
8. **Stamp + log.** On success it stamps `deliveryStatus="delivered"` + `deliveredAt` and logs `action="deliver"` with `success_count` and `pruned_count`.

`deliveredAt` is the delivery-layer idempotency guard (distinct from `dedupeKey`, which dedupes at the creation layer). All stamp writes are best-effort: a stamp failure is logged (`action="error"`, `reason="stamp_failed"`) but never raised.

## Operator Runbook

Operational reference for the shipped push-delivery pipeline.

### FCM credentials / service account

- The deployed function initializes the Firebase Admin SDK with the default app — `initialize_app()` in `functions/main.py` — with **no explicit credential file**. In Cloud Functions the Admin SDK uses Application Default Credentials from the function's **runtime service account**.
- That service account needs permission to send via FCM (the Firebase Cloud Messaging API must be enabled on the project, and the runtime SA must be able to call it — `roles/firebase.sdkAdminServiceAgent` / the default Firebase Admin SDK service agent covers this).
- **No credential file is shipped in the function source** and none is needed in code. Locally/CI the function source must stay free of `api/app` imports and of any hard-coded service-account JSON.
- If delivery logs show `action="error"` `reason="send_failed"` with auth/permission errors, check that the runtime service account still has FCM send permission and that the FCM API is enabled on the project.

### Stale-token cleanup (auto-prune)

- Invalid device tokens are pruned automatically on send — there is normally **no manual cleanup**. When `fcm_sender.send()` reports invalid tokens, the handler removes them from `users/{uid}.deviceTokens` (`_prune_invalid_tokens`).
- A token is treated as permanently invalid (prunable) when its per-token failure is `UNREGISTERED` (app uninstalled / token expired), `SenderIdMismatch` (token belongs to another FCM sender), or `INVALID_ARGUMENT` (malformed token).
- **All-`INVALID_ARGUMENT` guard:** if *every* token in a multicast fails with `INVALID_ARGUMENT`, the likely cause is a malformed shared payload (title/body/data too large), not the tokens — so nothing is pruned. Watch for `suspected_payload_error=true` in the `PUSH3.fcmSender` `action="send"` log.
- Transient failures (`UNAVAILABLE`, `INTERNAL`, quota, third-party-auth) are never pruned, so those tokens are retried on the next intent rather than dropped.
- Pruning is best-effort: a prune failure logs `action="error"` `reason="prune_failed"` and does not block the delivery stamp.

### Kill switch — `GSM_TRIGGERS_ENABLED`

- Set the environment variable `GSM_TRIGGERS_ENABLED=false` (also accepts `0`/`no`/`off`) on the functions runtime to suppress delivery **without redeploying code**. Backed by `functions/runtime_flags.py` (`triggers_enabled()`); the default when unset is **enabled**.
- While disabled, each intent create logs `action="ignore"` `reason="triggers_disabled"` and is left with `deliveryStatus="pending"` and no `deliveredAt`. The same flag also gates the match-cache triggers.
- To re-enable, set it back to `true` (or unset it). Intents written while the switch was off are **not** retroactively delivered — they remain `pending` unless re-created.

### Verifying delivery in logs

Filter Cloud Functions logs on the trigger name and inspect the `action`:

```
trigger="onNotificationIntentCreated"
```

| `action` | `reason` | Meaning |
|----------|----------|---------|
| `deliver` | — | Push sent. Carries `success_count` and `pruned_count`. |
| `skip` | `no_tokens` | User has no device tokens; stamped `deliveryStatus="no_tokens"`. |
| `skip` | `already_delivered` | At-least-once redelivery suppressed by the `deliveredAt` guard. |
| `ignore` | `triggers_disabled` | Kill switch is off (`GSM_TRIGGERS_ENABLED=false`). |
| `error` | `send_failed` | FCM send raised; stamped `deliveryStatus="failed"`. |
| `error` | `prune_failed` | Invalid-token prune write failed (delivery still stamped). |
| `error` | `stamp_failed` | Best-effort stamp write failed (logged, not raised). |

The FCM sender logs separately under `trigger="PUSH3.fcmSender"` `action="send"` with `tokens_count`, `success_count`, `invalid_count`, `transient_count`, and `suspected_payload_error`.

A credential-free way to confirm the deployed trigger is live is the notification step of `tools/smoke_triggers.py` (run via `scripts/smoke_triggers.sh --env dev --project <id>`): it writes an intent for a tokenless user and asserts the trigger stamps `deliveryStatus="no_tokens"` + `deliveredAt`. Under `--env emu` (Firestore-only, no Functions runtime) that step skips gracefully.
