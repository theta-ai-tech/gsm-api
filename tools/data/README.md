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
| `venue_checkpoint.json` | `tools/normalize_courts.py` | List of `VenueSummary` rows (camelCase): `venueId`, `name`, `coordinates`, `area`, `sports[]`, `courtCount`, `indoor`, `placeId` |

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
   > on load — do not introduce new fields. Also, `area` must be exactly one of
   > the `REGION_MAPPING` metro values (`athens` / `thessaloniki` / `patras`);
   > any other string will not match the `GET /venues` metro filter.

4. **Approve & ingest.** Once the checkpoint is approved, the ingest step (#387)
   reads it and upserts `venues/{venueId}` documents.

## Conventions

- `area` = **metro region string**, lowercase, one of `athens` /
  `thessaloniki` / `patras`. Matches the *values* in `config/regions.mapping`
  (see `REGION_MAPPING` in `tools/seed_data.py`).
- `placeId` is `null` at MVP launch (Places enrichment deferred).
- `courtCount` / `indoor` are populated only where OSM provides a signal, else
  `null`.
