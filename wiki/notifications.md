# Notification Intents

## Overview

The notification intent contract is a provider-agnostic layer that decouples business-logic events from push notification delivery. When a relevant play state transition occurs, the backend writes a **PlayNotificationIntent** document to a per-user Firestore subcollection. The mobile client (or a Cloud Function listener) reads this document and decides how to surface it — FCM push, in-app banner, or badge count. The backend never calls a push provider directly.

This approach means:
- Notification logic is testable without a push provider.
- Mobile can evolve its notification UI without backend changes.
- The backend write is always **fire-and-forget** — a failure to write never breaks the main transactional flow.

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

## Provider-Agnostic Design

The backend only writes the intent document. It does **not** call FCM, APNs, or any other push provider. A Cloud Function or the mobile SDK should listen on `users/{uid}/notificationIntents` (using `onWrite` or real-time listeners) and translate the intent into a platform notification.

This separation means:
- The backend can run without Firebase Messaging credentials.
- Mobile teams can change their notification strategy (e.g. silent push vs. visible alert) without touching the API.
- The same intent document can be used to drive both push notifications and in-app notification centers.

## Delivery (planned — option b)

> **Status:** designed, not yet implemented. Intents are written today but **not delivered** to any
> device. Real push (reaching a backgrounded/closed app) requires a server to call FCM — a client-side
> Firestore listener only runs while the app is foregrounded.

The chosen target is **backend-owned delivery**: device tokens are stored on the user, and a
Firestore-triggered Cloud Function calls FCM whenever a `notificationIntents` doc is created. This
closes the "intents written but never delivered" gap server-side; iOS only has to register its device
token (`POST /me/device-tokens`).

Full architecture, device-token model, registration API, trigger design, idempotency/pruning rules,
and the iOS contract are specified in
**[`plans/plan-push-notifications.md`](../plans/plan-push-notifications.md)**. This work is tracked by
epic [#329 (NTF-2)](https://github.com/theta-ai-tech/gsm-api/issues/329) and decomposed into issues
**PUSH-1 … PUSH-7** (label `push-notifications`), scheduled for a post-iOS sprint. This section will be
updated to describe live behaviour once that sprint lands.
