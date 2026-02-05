# /me/state Modes (Tab 1)

This page defines the mode enum, the response envelope, and the intended high-level meaning for Tab 1.
It is the source of truth for the UI-router contract.

## Enum
`PlayTabStateEnum` values:
- `DISCOVERY`
- `BROADCAST_ACTIVE`
- `OUTGOING_OFFER_PENDING`
- `INCOMING_OFFER_PENDING`
- `MATCH_SCHEDULED`
- `POST_MATCH_LOG_AVAILABLE`
- `POST_MATCH_WAITING_OPPONENT`
- `POST_MATCH_CONFIRM_REQUIRED`
- `MATCH_DISPUTED`

## Mode intent
- `DISCOVERY`: default browse state; map + challengable player list.
- `BROADCAST_ACTIVE`: user has an active availability broadcast. Incoming offers queue up and are included in the payload.
- `OUTGOING_OFFER_PENDING`: user sent an offer and is waiting for response before expiry.
- `INCOMING_OFFER_PENDING`: user received an offer (no active broadcast) and must respond before expiry.
- `MATCH_SCHEDULED`: a confirmed upcoming match is the primary focus.
- `POST_MATCH_LOG_AVAILABLE`: match time passed; user can submit/log result.
- `POST_MATCH_WAITING_OPPONENT`: user logged result and is waiting for opponent action.
- `POST_MATCH_CONFIRM_REQUIRED`: opponent logged result and this user must confirm/reject.
- `MATCH_DISPUTED`: conflicting post-match submissions requiring dispute resolution flow.

## Response envelope

Every call to `GET /me/state` returns this stable shape. The `payload` contents vary by mode.

```json
{
  "mode": "<PlayTabStateEnum>",
  "serverTime": "2026-02-03T10:00:00Z",
  "primary": {
    "broadcastId": "<string | null>",
    "matchId": "<string | null>",
    "activeOfferIds": ["<offerId>"]
  },
  "payload": { },
  "annotations": { },
  "uiEvents": []
}
```

### Field definitions

| Field | Type | Description |
|---|---|---|
| `mode` | string | Current `PlayTabStateEnum` value. |
| `serverTime` | ISO 8601 UTC | Server timestamp; the client should use this for countdown/expiry calculations. |
| `primary.broadcastId` | string / null | Active broadcast doc ID (set in BROADCAST_ACTIVE). |
| `primary.matchId` | string / null | Active match doc ID (set from MATCH_SCHEDULED through post-match states). |
| `primary.activeOfferIds` | array\<string> | IDs of offers relevant to the current state (pending incoming or outgoing). |
| `payload` | object | Mode-specific data. See `spec/tab1-play-payloads.md` for full examples per mode. |
| `annotations` | object | Discovery-only UI hints (e.g., pinned card, nearby count). Empty for non-discovery modes. |
| `uiEvents` | array\<object> | Transient notices about events since last poll (e.g., offer expired). Not modes. |

### uiEvents shape

```json
{
  "type": "offer_expired",
  "message": "Offer from Sam expired.",
  "meta": { "offerId": "o_1" }
}
```

Known event types: `offer_expired`, `offer_declined`, `broadcast_expired`, `match_completed`.

## Freshness reconciliation

The persisted `playTab.state` on the user doc is the fast-path read. However, time-based transitions (broadcast/offer expiry, match scheduledAt) require correction on read.

When the API detects a stale state (e.g., `BROADCAST_ACTIVE` but `broadcast.expiresAt < now`), it:
1. Corrects the `playTab` fields on the user doc
2. Updates the broadcast/offer doc status if needed
3. Returns the corrected state to the client

This means the client always sees an accurate state regardless of whether background jobs have run.

See `arch/me_state_machine.md` for the state diagram and transition rules.
