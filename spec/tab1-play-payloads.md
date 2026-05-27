# Tab 1 PLAY — /me/state Payload Examples

Full JSON response examples for each `PlayTabStateEnum` mode.
See `wiki/me-state.md` for the envelope definition.

---

## DISCOVERY

Default browse state. No active broadcast, offer, or match.

```json
{
  "mode": "DISCOVERY",
  "serverTime": "2026-02-03T10:00:00Z",
  "primary": {
    "broadcastId": null,
    "matchId": null,
    "activeOfferIds": []
  },
  "payload": {},
  "annotations": {},
  "uiEvents": []
}
```

---

## BROADCAST_ACTIVE

User has an active availability broadcast. Offers queue up and are included in the payload.

```json
{
  "mode": "BROADCAST_ACTIVE",
  "serverTime": "2026-02-03T10:00:00Z",
  "primary": {
    "broadcastId": "broadcast_abc",
    "matchId": null,
    "activeOfferIds": ["offer_1", "offer_2"]
  },
  "payload": {
    "broadcast_id": "broadcast_abc",
    "sport": "tennis",
    "match_type": "singles",
    "broadcast_type": "find_opponent",
    "partner_uid": null,
    "availability": "today",
    "court_status": "have_court",
    "court_location": "Central Court, Athens",
    "venue_ref": {
      "venueId": "ten_twenty_club",
      "placeId": null,
      "name": "Ten Twenty Club",
      "coordinates": {"lat": 37.8362, "lng": 23.7627}
    },
    "expires_at": "2026-02-03T16:00:00Z",
    "created_at": "2026-02-03T08:00:00Z",
    "pending_offers": [
      {
        "offerId": "offer_1",
        "fromUid": "user_456",
        "fromName": "Sam",
        "fromRanking": {"sport": "tennis", "pts": 1100},
        "proposedTime": "2026-02-03T18:00:00Z",
        "message": "Up for a game?",
        "expiresAt": "2026-02-03T10:05:00Z",
        "createdAt": "2026-02-03T10:00:00Z"
      },
      {
        "offerId": "offer_2",
        "fromUid": "user_789",
        "fromName": "Jamie",
        "fromRanking": {"sport": "tennis", "pts": 950},
        "proposedTime": "2026-02-03T17:00:00Z",
        "message": null,
        "expiresAt": "2026-02-03T10:04:00Z",
        "createdAt": "2026-02-03T09:59:00Z"
      }
    ]
  },
  "annotations": {},
  "uiEvents": []
}
```

### Doubles variant (find_fourth broadcast)

```json
{
  "mode": "BROADCAST_ACTIVE",
  "serverTime": "2026-02-03T10:00:00Z",
  "primary": {
    "broadcastId": "broadcast_dbl_abc",
    "matchId": null,
    "activeOfferIds": []
  },
  "payload": {
    "broadcast_id": "broadcast_dbl_abc",
    "sport": "padel",
    "match_type": "doubles",
    "broadcast_type": "find_fourth",
    "partner_uid": "user_partner_1",
    "partner_name": "Chris",
    "availability": "today",
    "court_status": "have_court",
    "court_location": "Flisvos Padel Academy",
    "venue_ref": {
      "venueId": "venue_flisvos",
      "placeId": "ChIJFlisvos",
      "name": "Flisvos Padel Academy",
      "coordinates": {"lat": 37.93, "lng": 23.68}
    },
    "expires_at": "2026-02-03T16:00:00Z",
    "created_at": "2026-02-03T08:00:00Z",
    "pending_offers": []
  },
  "annotations": {},
  "uiEvents": []
}
```

---

## OUTGOING_OFFER_PENDING

User sent a challenge and is waiting for the recipient to respond.

```json
{
  "mode": "OUTGOING_OFFER_PENDING",
  "serverTime": "2026-02-03T10:05:00Z",
  "primary": {
    "broadcastId": null,
    "matchId": null,
    "activeOfferIds": ["offer_123"]
  },
  "payload": {
    "offerId": "offer_123",
    "toUid": "user_789",
    "toName": "Jamie",
    "toRanking": {"sport": "tennis", "pts": 950},
    "sport": "tennis",
    "proposedTime": "2026-02-03T18:00:00Z",
    "courtLocation": "Central Court, Athens",
    "message": "Let's play!",
    "expiresAt": "2026-02-03T10:10:00Z",
    "createdAt": "2026-02-03T10:05:00Z"
  },
  "annotations": {},
  "uiEvents": []
}
```

---

## INCOMING_OFFER_PENDING

User received a direct challenge (no active broadcast) and must respond.

```json
{
  "mode": "INCOMING_OFFER_PENDING",
  "serverTime": "2026-02-03T10:01:00Z",
  "primary": {
    "broadcastId": null,
    "matchId": null,
    "activeOfferIds": ["offer_456"]
  },
  "payload": {
    "offerId": "offer_456",
    "fromUid": "user_456",
    "fromName": "Sam",
    "fromRanking": {"sport": "tennis", "pts": 1100},
    "sport": "tennis",
    "proposedTime": "2026-02-03T18:00:00Z",
    "courtLocation": "Central Court, Athens",
    "message": "Up for a game?",
    "expiresAt": "2026-02-03T10:06:00Z",
    "createdAt": "2026-02-03T10:01:00Z"
  },
  "annotations": {},
  "uiEvents": []
}
```

---

## MATCH_SCHEDULED

A confirmed upcoming match is the primary focus. Discovery UI is replaced by the logistics card.

```json
{
  "mode": "MATCH_SCHEDULED",
  "serverTime": "2026-02-03T12:00:00Z",
  "primary": {
    "broadcastId": null,
    "matchId": "match_789",
    "activeOfferIds": []
  },
  "payload": {
    "matchId": "match_789",
    "sport": "tennis",
    "scheduledAt": "2026-02-03T18:00:00Z",
    "courtId": "court_4",
    "courtName": "Central Court",
    "courtGeo": {"lat": 37.9838, "lng": 23.7275},
    "opponent": {
      "uid": "user_456",
      "name": "Sam",
      "profileUrl": "https://example.com/sam.png",
      "ranking": {"sport": "tennis", "pts": 1100}
    }
  },
  "annotations": {},
  "uiEvents": []
}
```

### Doubles variant

`match_type` is `doubles` and `participants` contains 4 entries — 2 per team. Use `participants`
for rendering team labels; `opponent` still carries the lead opponent for singles-style "vs."
display.

```json
{
  "mode": "MATCH_SCHEDULED",
  "serverTime": "2026-02-03T12:00:00Z",
  "primary": {
    "broadcastId": null,
    "matchId": "match_dbl_999",
    "activeOfferIds": []
  },
  "payload": {
    "matchId": "match_dbl_999",
    "sport": "padel",
    "match_type": "doubles",
    "scheduledAt": "2026-02-03T18:00:00Z",
    "venue_ref": {
      "venueId": "venue_flisvos",
      "placeId": "ChIJFlisvos",
      "name": "Flisvos Padel Academy",
      "coordinates": {"lat": 37.93, "lng": 23.68}
    },
    "opponent": {
      "uid": "user_456",
      "name": "Sam",
      "profileUrl": null,
      "ranking": {"sport": "padel", "pts": 1100}
    },
    "participants": [
      {"uid": "user_123", "name": "Alex", "team": "A", "role": "player"},
      {"uid": "user_partner_1", "name": "Chris", "team": "A", "role": "player"},
      {"uid": "user_456", "name": "Sam", "team": "B", "role": "player"},
      {"uid": "user_789", "name": "Jordan", "team": "B", "role": "player"}
    ]
  },
  "annotations": {},
  "uiEvents": []
}
```

---

## POST_MATCH_LOG_AVAILABLE

Match time has passed. User can submit their result via the score dial.

```json
{
  "mode": "POST_MATCH_LOG_AVAILABLE",
  "serverTime": "2026-02-03T18:35:00Z",
  "primary": {
    "broadcastId": null,
    "matchId": "match_789",
    "activeOfferIds": []
  },
  "payload": {
    "matchId": "match_789",
    "sport": "tennis",
    "scheduledAt": "2026-02-03T18:00:00Z",
    "opponent": {
      "uid": "user_456",
      "name": "Sam"
    }
  },
  "annotations": {},
  "uiEvents": []
}
```

### Doubles fields

For doubles matches, the payload also includes `match_type: "doubles"` and a `participants` list
(same shape as MATCH_SCHEDULED). The base envelope is otherwise identical.

---

## POST_MATCH_WAITING_OPPONENT

User has submitted their result and is waiting for the opponent to confirm.

```json
{
  "mode": "POST_MATCH_WAITING_OPPONENT",
  "serverTime": "2026-02-03T20:10:00Z",
  "primary": {
    "broadcastId": null,
    "matchId": "match_789",
    "activeOfferIds": []
  },
  "payload": {
    "matchId": "match_789",
    "submittedScore": {
      "sets": [{"p1Games": 6, "p2Games": 4}, {"p1Games": 6, "p2Games": 3}],
      "winnerUid": "user_123"
    },
    "opponent": {
      "uid": "user_456",
      "name": "Sam"
    }
  },
  "annotations": {},
  "uiEvents": []
}
```

### Doubles fields

For doubles matches, the payload also includes `match_type: "doubles"` and a `participants` list
(same shape as MATCH_SCHEDULED). The base envelope is otherwise identical.

---

## POST_MATCH_CONFIRM_REQUIRED

Opponent submitted their result first. This user must confirm or reject.

```json
{
  "mode": "POST_MATCH_CONFIRM_REQUIRED",
  "serverTime": "2026-02-03T20:15:00Z",
  "primary": {
    "broadcastId": null,
    "matchId": "match_789",
    "activeOfferIds": []
  },
  "payload": {
    "matchId": "match_789",
    "opponentScore": {
      "sets": [{"p1Games": 6, "p2Games": 4}, {"p1Games": 6, "p2Games": 3}],
      "winnerUid": "user_456"
    },
    "opponent": {
      "uid": "user_456",
      "name": "Sam"
    }
  },
  "annotations": {},
  "uiEvents": []
}
```

### Doubles fields

For doubles matches, the payload also includes `match_type: "doubles"` and a `participants` list
(same shape as MATCH_SCHEDULED). The base envelope is otherwise identical.

---

## MATCH_DISPUTED

Conflicting post-match submissions. Requires dispute resolution.

```json
{
  "mode": "MATCH_DISPUTED",
  "serverTime": "2026-02-03T20:20:00Z",
  "primary": {
    "broadcastId": null,
    "matchId": "match_789",
    "activeOfferIds": []
  },
  "payload": {
    "matchId": "match_789",
    "myScore": {
      "sets": [{"p1Games": 6, "p2Games": 4}, {"p1Games": 6, "p2Games": 3}],
      "winnerUid": "user_123"
    },
    "opponentScore": {
      "sets": [{"p1Games": 4, "p2Games": 6}, {"p1Games": 6, "p2Games": 3}, {"p1Games": 7, "p2Games": 5}],
      "winnerUid": "user_456"
    },
    "opponent": {
      "uid": "user_456",
      "name": "Sam"
    }
  },
  "annotations": {},
  "uiEvents": []
}
```
