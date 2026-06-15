# Operator Playbook — GSM Launch / Demo

Quick reference for running a demo, seeding data, managing leagues, and operating smoke tests.
Target read time: under 2 minutes.

> **OPS-1 note:** OPS-1 will expand demo scenarios (additional match states, edge-case users).
> Update the [Demo Scenarios](#4-demo-scenarios) section when it merges.

All commands run from **repo root** (`gsm-api/`) unless noted.

---

## 1. Prerequisites

| Process | Terminal | Command |
|---------|----------|---------|
| Firestore + Auth emulators | Terminal 1 | `make emu-all` |
| GSM API (emulator-backed, auth enabled) | Terminal 2 | `make api-dev-emu-auth` |

The API listens on `http://localhost:8000`.

---

## 2. Quick Start: Seed Demo Environment

Starting from a clean state (or after a reset):

```bash
# Terminal 1
make emu-all

# Terminal 2 — wait for "Emulator Hub running" before continuing
make seed-emu          # Seeds all collections: users, matches, leagues, venues, …
make api-dev-emu-auth  # Start API

# Terminal 3 — get an emulator auth token for the seeded user_ignatios
TOKEN=$(./scripts/get_emu_token.sh user_ignatios -t)
```

`make seed-emu` is idempotent — running it twice is safe (upserts by document ID).

---

## 3. Demo Users

These UIDs exist in **Firestore only** (not in Firebase Auth). They are suitable for browsing
user profiles and league data. To make authenticated API calls you need an emulator Auth token
(see the [Auth token](#auth-token) section below).

| UID | Name | Area | Sports | Tier | Key data |
|-----|------|------|--------|------|----------|
| `user_ignatios` | Ignatios | athens (101) | padel, tennis | Amateur | padel 980 pts · tennis 620 pts |
| `user_alice` | Alice | thessaloniki (202) | tennis | Amateur | tennis 820 pts |
| `user_bob` | Bob | london (303) | padel, pickleball | Amateur | padel 540 pts · pickleball 300 pts |

### Auth token

The helper script defaults to `user_1`; always pass the seeded UID explicitly so the token matches the Firestore data:

```bash
# Option 1 — helper script (authenticates as a seeded user)
TOKEN=$(./scripts/get_emu_token.sh user_ignatios -t)

# Option 2 — direct Auth emulator call (authenticates as user_ignatios)
# The "Authorization: Bearer owner" header lets the emulator create a user
# with a specific UID that matches the seeded Firestore document.
TOKEN=$(curl -s -X POST \
  "http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1/accounts:signUp?key=fake-api-key" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer owner" \
  -d '{"localId":"user_ignatios","email":"user_ignatios@gsm.local","password":"test_pass_123"}' \
  > /dev/null && \
  curl -s -X POST \
  "http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=fake-api-key" \
  -H "Content-Type: application/json" \
  -d '{"email":"user_ignatios@gsm.local","password":"test_pass_123","returnSecureToken":true}' \
  | jq -r '.idToken')
```

Use the token in API calls: `-H "Authorization: Bearer $TOKEN"`

---

## 4. Demo Scenarios

| Scenario | Data | Endpoint(s) |
|----------|------|-------------|
| View play state (upcoming matches) | `user_ignatios` | `GET /me/state` |
| Score confirmation flow | `match_pending` (PENDING_CONFIRMATION tennis, Alice vs Ignatios) | `POST /matches/match_pending/verify-score` |
| League browse | `padel-local-2025` (ACTIVE), `tennis-local-2025` (OPEN) | `GET /leagues` |
| League detail | `padel-local-2025` | `GET /leagues/padel-local-2025` |
| League join | `tennis-local-2025` (OPEN, 2/16 members) | `POST /leagues/tennis-local-2025/join` |
| Completed league | `tennis-completed-2024` | `GET /leagues/tennis-completed-2024` |
| Rankings / leaderboard | Athens padel leaderboard | `GET /me/lab/leaderboard?sport=padel` |
| Venue list | 16 Athens venues | `GET /venues?sport=padel` |

> `match_pending` uses an **underscore**, not a hyphen. `GET /venues` requires the `sport` query parameter.

---

## 5. Venues

### Seeded venues (Athens)

| Tier | Venue IDs |
|------|-----------|
| Padel — Tier 1 | `ten_twenty_club`, `flisvos_padel_academy`, `athens_padel_club_glyfada` |
| Padel — Tier 2 | `golden_point_padel_club`, `la_bandeja_sports_club`, `halandri_athletic_club`, `arena_padel_club_marousi`, `renti_arena_padel`, `greek_padel_academy`, `northpoint_padel_club` |
| Tennis | `athens_tennis_club`, `glyfada_tennis_club`, `kifisia_tennis_club`, `paleo_faliro_tennis_club`, `marousi_sports_club` |
| Multi-sport | `voula_sports_complex` |

### Add a venue (manual — no API endpoint)

Venue creation and suggestion promotion are Firestore direct writes.

```bash
# Add a venue document
curl -X PATCH \
  "http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents/venues/my_new_venue" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "venueId":  {"stringValue": "my_new_venue"},
      "name":     {"stringValue": "My New Club"},
      "sport":    {"stringValue": "padel"},
      "area":     {"stringValue": "athens"},
      "tier":     {"integerValue": "2"},
      "verified": {"booleanValue": true}
    }
  }'
```

### Review a pending venue suggestion

```bash
# 1. Read the suggestion
curl "http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents/venueSuggestions/{suggestionId}"

# 2. Promote it — set status to "approved" and copy fields into venues collection
curl -X PATCH \
  "http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents/venueSuggestions/{suggestionId}" \
  -H "Content-Type: application/json" \
  -d '{"fields": {"status": {"stringValue": "approved"}}}'
# Then write a new venues doc as shown above.
```

---

## 6. Leagues

### Seeded leagues

| ID | Name | Sport | Status | Region | Capacity |
|----|------|-------|--------|--------|---------|
| `padel-local-2025` | Local Padel Ladder 2025 | padel | ACTIVE | athens | 3 / 12 |
| `tennis-local-2025` | Local Tennis Series 2025 | tennis | OPEN | thessaloniki | 2 / 16 |
| `tennis-completed-2024` | Tennis Series 2024 | tennis | COMPLETED | thessaloniki | 2 / 8 |

### Create a league manually (no API endpoint)

```bash
curl -X PATCH \
  "http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents/leagues/my-league-id" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "leagueId":       {"stringValue": "my-league-id"},
      "name":           {"stringValue": "My League"},
      "sport":          {"stringValue": "padel"},
      "season":         {"stringValue": "Spring 2026"},
      "status":         {"stringValue": "open"},
      "ownerUid":       {"stringValue": "user_ignatios"},
      "region":         {"stringValue": "athens"},
      "maxPlayers":     {"integerValue": "12"},
      "currentPlayers": {"integerValue": "0"},
      "startDate":      {"timestampValue": "2026-06-01T00:00:00Z"},
      "endDate":        {"timestampValue": "2026-08-31T00:00:00Z"},
      "tier":           {"stringValue": "intermediate"}
    }
  }'
```

Valid values:
- `status`: `open` · `active` · `completed`
- `sport`: `padel` · `tennis` · `pickleball`
- `tier`: `amateur` · `intermediate` · `advanced` · `competitive`

---

## 7. Disputed Matches — Resolution Runbook

When a score confirmation disagrees (the second `verify-score` caller names a different winner),
the match moves to `status="disputed"` and **no scoring happens**. There is **no API endpoint to
transition a match out of `disputed` at MVP** — this is a deliberate scope cut for the Athens beta
(OPS-DISPUTE-1): disputes are rare, and building an authenticated admin mutation endpoint is out of
scope for launch. Until that endpoint exists, an operator resolves disputes by writing Firestore
directly using the procedure below. Revisit post-beta if dispute volume warrants automation.

> **Releasing a participant requires TWO fields**, not one. `/me/state` derives `mode` from the
> stored `playTab.state` and, for `MATCH_DISPUTED`, loads the match via `playTab.activeMatchId`.
> A participant is only fully released when **both** `playTab.state="DISCOVERY"` **and**
> `playTab.activeMatchId=null` are set.
>
> **Singles vs doubles divergence:** a singles dispute writes only the match doc — participant
> `playTab` is untouched, so those users already read `DISCOVERY`. A doubles dispute also sets every
> participant `playTab.state="MATCH_DISPUTED"` (but does **not** clear `activeMatchId`). The reset
> below is written to cover both: run it for every uid regardless of each field's current value.

All REST calls below target the Firestore emulator. The `-H "Authorization: Bearer owner"` header
makes the emulator bypass security rules (the same owner bypass used for the Auth emulator in §3).
In **production**, perform the identical field writes via the Firebase console or an Admin SDK
script (the Admin SDK bypasses rules automatically — no owner header needed).

### Step 0 — Inspect the match

Read the disputed match to confirm its status and find every uid that must be released
(`participantUids`: 2 for singles, 4 for doubles).

```bash
curl -s -H "Authorization: Bearer owner" \
  "http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents/matches/{matchId}"
# Expect: fields.status.stringValue == "disputed"
#         fields.matchType.stringValue == "singles" | "doubles"
#         fields.participantUids.arrayValue.values == [ {stringValue: ...}, ... ]
```

The operator resets **every** uid in `participantUids`.

### Outcome A — Void the match (default, recommended for launch)

No winner, no points awarded, no ranking/pts fields change. Use this unless ops has decided the
correct result.

**Step 1 — mark the match cancelled** (`cancelled` is the terminal `MatchStatusEnum` value):

```bash
curl -s -X PATCH -H "Authorization: Bearer owner" -H "Content-Type: application/json" \
  "http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents/matches/{matchId}?updateMask.fieldPaths=status" \
  -d '{"fields": {"status": {"stringValue": "cancelled"}}}'
```

**Step 2 — release each participant.** Run once per uid in `participantUids`, regardless of the
field's current value. The nested `updateMask.fieldPaths=playTab.state` /
`playTab.activeMatchId` form updates only those two keys and leaves the rest of `playTab` intact:

```bash
curl -s -X PATCH -H "Authorization: Bearer owner" -H "Content-Type: application/json" \
  "http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents/users/{uid}?updateMask.fieldPaths=playTab.state&updateMask.fieldPaths=playTab.activeMatchId" \
  -d '{"fields": {"playTab": {"mapValue": {"fields": {
        "state":         {"stringValue": "DISCOVERY"},
        "activeMatchId": {"nullValue": null}
      }}}}}'
```

No ranking or `pts` fields change. After both steps, `GET /me/state` for each participant returns
`mode == "DISCOVERY"`.

**Production equivalent** (Admin SDK):

```python
match_ref.update({"status": "cancelled"})
for uid in participant_uids:
    db.collection("users").document(uid).update(
        {"playTab.state": "DISCOVERY", "playTab.activeMatchId": None}
    )
```

### Outcome B — Adjudicate a winner (preserve points)

Use when ops decides the correct result and wants points awarded. This **reuses the audited scoring
path** — no manual pts math, no manual `pointHistory` writes.

**Step 1 — reopen the match for confirmation.** Set `status="pending_confirmation"`, write the
agreed `score` (with the correct `winnerUid`), and set `resultSubmittedBy` to a **single-element**
array holding only the *first* submitter's uid. This matters: `verify-score` rejects a confirmation
from a uid already present in `resultSubmittedBy`, so leaving only the first submitter lets the
**opposing** participant confirm.

```bash
curl -s -X PATCH -H "Authorization: Bearer owner" -H "Content-Type: application/json" \
  "http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents/matches/{matchId}?updateMask.fieldPaths=status&updateMask.fieldPaths=resultSubmittedBy" \
  -d '{"fields": {
        "status":           {"stringValue": "pending_confirmation"},
        "resultSubmittedBy": {"arrayValue": {"values": [{"stringValue": "{firstSubmitterUid}"}]}}
      }}'
# Also set the agreed score/winnerUid on the match doc the same way.
```

**Step 2 — the opposing participant confirms the agreed winner:**

```bash
curl -s -X POST -H "Authorization: Bearer $OPPOSING_TOKEN" -H "Content-Type: application/json" \
  "http://localhost:8000/matches/{matchId}/verify-score" \
  -d '{"winner_uid": "{agreedWinnerUid}", "score": {"sets": [{"p1_games": 6, "p2_games": 4}], "winner_uid": "{agreedWinnerUid}"}}'
```

The existing scoring path then runs: points are awarded, `pointHistory` is written, the match moves
to `completed`, and **all participants are auto-released to `DISCOVERY`** — no manual user-doc
writes needed for Outcome B.

---

## 8. Smoke Tests

| Script | What it covers | How to run | Requires |
|--------|---------------|-----------|---------|
| `scripts/smoke_play.sh` | Tab 1 PLAY — broadcast / offer / match flow end-to-end | `./scripts/smoke_play.sh` | `make emu-all` + `make api-dev-emu-auth` |
| `scripts/smoke_improve.sh` | Tab 2 IMPROVE — journal, leaderboard, scouting | `./scripts/smoke_improve.sh` | Same as above |
| `scripts/smoke_triggers.sh` | Cloud Function trigger cache behavior | `./scripts/smoke_triggers.sh --env emu` | Firestore emulator |
| `tests/smoke/pr-{N}.sh` | Per-PR endpoint regression for PR #N | `bash tests/smoke/pr-{N}.sh` | `make emu-all` + API on correct port |

Per-PR smoke scripts default to port `8000 + N` (e.g. PR #284 → port 8284).

Run `make smoke-functions` for a lightweight HTTP ping check on deployed Cloud Functions.

For detailed tool guidance see [wiki/tools.md](tools.md).

---

## 9. Reset / Re-seed

```bash
# Stop the emulator (Ctrl-C in Terminal 1)
# Restart it
make emu-all

# Re-seed once the emulator is ready
make seed-emu
```

The emulator does not persist data between restarts unless `--export-on-exit` / `--import` flags
are configured. A bare `make emu-all` always starts clean.

---

## 10. Manual vs Automated

| Operation | Manual / Automated | Notes |
|-----------|--------------------|-------|
| Seed demo data | **Manual** — `make seed-emu` | Run once after emulator starts |
| Reset demo data | **Manual** — restart emulator + `make seed-emu` | No incremental wipe command |
| Create demo user (Auth) | **Manual** — `./scripts/get_emu_token.sh` or `signUp` REST call | UIDs `user_*` are Firestore-only |
| Add / promote a venue | **Manual** — Firestore REST PATCH | No `POST /venues` endpoint yet |
| Create a league | **Manual** — Firestore REST PATCH | No `POST /leagues` endpoint yet |
| Resolve a disputed match | **Manual** — Firestore REST PATCH | No API endpoint at MVP (OPS-DISPUTE-1) |
| Running smoke tests | **Manual** — `./scripts/smoke_*.sh` or `bash tests/smoke/pr-N.sh` | Auto-triggered in QA gate for open PRs |
| Lint / type checks | **Automated** — GitHub Actions CI on every PR push | Also run locally: `make fmt format type` |
| API deployment | **Automated** — GitHub Actions deploy on `main` merge | Manual dispatch also available |
| Cache rebuild | **Manual** — `make rebuild-caches-emu` | Repair/backfill only; not a routine step |
