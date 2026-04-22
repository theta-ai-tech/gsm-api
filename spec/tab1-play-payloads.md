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
    "broadcastId": "broadcast_abc",
    "sport": "tennis",
    "availability": "today",
    "courtStatus": "have_court",
    "courtLocation": "Central Court, Athens",
    "venueRef": {
      "venueId": "ten_twenty_club",
      "placeId": null,
      "name": "Ten Twenty Club",
      "coordinates": {"lat": 37.8362, "lng": 23.7627}
    },
    "expiresAt": "2026-02-03T16:00:00Z",
    "createdAt": "2026-02-03T08:00:00Z",
    "pendingOffers": [
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
