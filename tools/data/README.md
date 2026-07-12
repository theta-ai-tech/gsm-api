# Venue-seeding data artifacts

This directory holds the offline artifacts of the **venue-seeding** pipeline.
Nothing here is written to Firestore automatically — the checkpoint JSON is a
human review gate that product signs off on before ingest.

## Pipeline

```
Overpass (OpenStreetMap)
        │  tools/fetch_courts_osm.py            (#385)
        ▼
osm_courts_raw.json          raw candidates, one per OSM element
        │  tools/normalize_courts.py            (#386)
        ▼
venue_checkpoint.json        VenueSummary-shaped rows, human-reviewed
        │  ingest (Firestore upsert)            (#387)
        ▼
venues/{venueId}             curated Firestore collection
```

## Files

| File | Written by | Shape |
|------|-----------|-------|
| `osm_courts_raw.json` | `tools/fetch_courts_osm.py` | List of raw candidates: `name`, `lat`, `lng`, `sports[]`, `osm_type`, `osm_id`, `courts`, `surface`, `building`, `indoor` |
| `venue_checkpoint.json` | `tools/normalize_courts.py` | List of `VenueSummary` rows (camelCase): `venueId`, `name`, `coordinates`, `area`, `sports[]`, `courtCount`, `indoor`, `placeId`, `status` (optional, default `"live"`) |

## Review → edit → approve flow

1. **Fetch** raw candidates:

   ```bash
   python -m tools.fetch_courts_osm
   ```

2. **Normalise** them into the review checkpoint:

   ```bash
   python -m tools.normalize_courts
   ```

   Each raw candidate becomes a `VenueSummary`-shaped row, or is dropped with a
   logged reason (missing name, missing coordinates, coordinates outside every
   metro box, or no supported sport). `area` is the metro string
   (`athens`/`thessaloniki`/`patras`) derived from which metro bounding box the
   coordinates fall in. Multi-sport venues collapse into a single row with a
   `sports[]` array. `venueId` is deterministic (`tools/venue_ids.py`), so
   re-running the pipeline upserts in place and never duplicates a given OSM
   element.

   > ⚠️ **Near-duplicate rows the registry cannot catch.** OSM often models the
   > same physical facility as both a `leisure=sports_centre` way *and* its
   > child pitch nodes/ways. Those carry distinct OSM ids, so they derive
   > distinct `venueId`s and slip past the `venueId` collision registry as
   > separate rows — even though they are the same real venue. **Human
   > reviewers must manually spot and dedupe these near-duplicates during
   > checkpoint review** (e.g. matching by name/coordinates) before approving.

3. **Review & edit** `venue_checkpoint.json` by hand. It is indented and sorted
   by `venueId` for stable diffs. A reviewer may:
   - fix a `name`, correct an `area`, set a `courtCount`/`indoor` value;
   - delete whole rows for venues that should not be seeded (including the
     near-duplicates described above).

   It is plain JSON — no code changes are needed to curate it, and hand-edits do
   not break downstream ingest as long as each row keeps the `VenueSummary`
   field shape.

   > ℹ️ **Stay within the `VenueSummary` schema.** The model uses
   > `extra="forbid"`, so any extra/unknown keys added by hand are **rejected**
   > on load — do not introduce new fields. `area` may be any non-empty,
   > already-lowercase slug, but a row whose `area` is not one of the launch
   > metros (`athens` / `thessaloniki` / `patras`) MUST set `status: "hidden"` —
   > otherwise ingest rejects it. `unverified` is never allowed outside a
   > launch metro (it would leak an unlaunched region past the client-visible
   > `GET /venues` filter). Rows in a launch metro may carry any `status`.

4. **Approve & ingest.** Once the checkpoint is approved, the ingest step (#387)
   reads it and upserts `venues/{venueId}` documents:

   ```bash
   python -m tools.ingest_venues --env=emu
   ```

   `tools/ingest_venues.py` validates **every** row into `VenueSummary` before it
   writes anything (validate-all, write-after); ALL per-row violations are
   collected and raised together, naming the offending index/`venueId` for each
   — bad data never lands partially and a reviewer sees every problem in one
   pass. It also rejects two rows that resolve to the same `venueId` (naming
   both) so a copy-pasted or slug-colliding duplicate aborts before any write.
   It enforces the live-regions invariant: `area` may be any non-empty
   lowercase slug, but `area not in LIVE_AREAS` (`athens` / `thessaloniki` /
   `patras`) requires `status: "hidden"` — the legacy `london` fixture entry in
   `REGION_MAPPING` is intentionally excluded from `LIVE_AREAS`. Each row
   is upserted with `set(..., merge=False)` keyed on `venueId` (writing `status`
   on every doc) and classified as **created / updated / unchanged** against the
   existing document; unchanged rows are skipped, so a re-run against an
   unedited checkpoint performs zero writes and never duplicates a venue.
   Hand-added rows without a `venueId` get one derived deterministically via
   `venue_id_for_manual(name, area)`. Emulator only (`--env=emu`); the real
   dev/prod write target is out of scope (#340).

   When a hidden region launches, flip its venues with
   `python -m tools.set_area_status --area=<slug> --from=hidden --to=live
   --env=emu` — it only touches rows matching both `area` and `status ==
   hidden`, so any `unverified` row in the same area is left untouched.

   > ℹ️ **Renaming a hand-added row leaves a stale doc.** A derived `venueId` is a
   > function of `name` + `area`, so renaming a hand-added venue (or changing its
   > metro) mints a *new* `venueId` and ingests a fresh `venues/{venueId}`
   > document. The old document is not touched and lingers behind — pruning it is
   > a manual step for now.

## Conventions

- `area` = **metro region string**, lowercase, any non-empty slug. For a
  launch metro this matches the *values* in `config/regions.mapping` (see
  `REGION_MAPPING` in `tools/seed_data.py`) — currently `athens` /
  `thessaloniki` / `patras`.
- `status` = venue lifecycle enum (`live` / `hidden` / `unverified`), optional
  on the checkpoint (default `"live"`). Invariant: `area not in LIVE_AREAS`
  (the launch metros above) requires `status: "hidden"`; `unverified` is only
  valid in a launch metro. `hidden` venues never reach clients; `unverified`
  venues are returned but flagged for user confirmation.
- `placeId` is `null` at MVP launch (Places enrichment deferred).
- `courtCount` / `indoor` are populated only where OSM provides a signal, else
  `null`.
