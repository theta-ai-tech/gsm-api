"""Ingest an approved venue checkpoint into the ``venues/{venueId}`` collection.

This is the ingest step of the venue-seeding epic. It reads the product-approved
review-checkpoint JSON written by ``tools/normalize_courts.py`` (#386) at
``tools/data/venue_checkpoint.json`` and upserts each row into Firestore keyed on
``venueId``. The write path reuses ``tools/seed_mapping.venue_summary_to_firestore_doc``
so ingested documents are byte-for-byte consistent with the emulator seeder.

Validate-everything-first, write-after
--------------------------------------
The checkpoint is hand-editable, so a row may be malformed. Every row is
validated into :class:`app.models.venue.VenueSummary` **before any write
happens**. A single bad row aborts the whole run with a message naming the
offending index/``venueId`` — bad data never lands partially.

Idempotent upsert
-----------------
Each row is written with ``set(..., merge=False)`` keyed on ``venueId``. Before
writing, the target document is compared against the existing one and classified
as *created* / *updated* / *unchanged*. Unchanged rows are skipped entirely, so
a re-run against an unedited checkpoint performs zero writes and never
duplicates a venue.

Hand-added rows
---------------
Product-added rows (no OSM id) flow through the same path. They normally already
carry a stable ``venueId`` from the manual scheme in ``tools/venue_ids.py``. If a
hand-added row omits ``venueId``, it is derived deterministically with
``venue_id_for_manual(name, area)`` before validation, so the same hand-added
venue always resolves to the same document.

Target
------
Emulator only (``--env=emu``). The real dev/prod write target is out of scope
here (tracked in #340), matching ``tools/seed_firestore.py``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.cloud import firestore
from pydantic import ValidationError

from app.models.venue import VenueSummary

from tools.seed_data import REGION_MAPPING
from tools.seed_mapping import venue_summary_to_firestore_doc
from tools.venue_ids import venue_id_for_manual

logger = logging.getLogger("ingest_venues")

# The product-approved checkpoint written by tools/normalize_courts.py (#386).
DEFAULT_INPUT_PATH = Path(__file__).resolve().parent / "data" / "venue_checkpoint.json"

# Firestore collection curated venues live in (mirrors VenueRepo.COLLECTION).
VENUES_COLLECTION = "venues"

# ``area`` must be one of the metro region strings in REGION_MAPPING. The
# reviewer forward-flag from #386: the checkpoint README documents this, the
# ingest enforces it.
ALLOWED_AREAS: frozenset[str] = frozenset(REGION_MAPPING.values())


class CheckpointValidationError(ValueError):
    """Raised when a checkpoint row is malformed or carries an invalid ``area``."""


@dataclass(frozen=True)
class IngestSummary:
    """Per-run counts of how each row was classified against Firestore."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged


def load_checkpoint(input_path: Path) -> list[dict[str, Any]]:
    """Read the checkpoint JSON as a list of raw (camelCase-aliased) row dicts."""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise CheckpointValidationError(
            f"Checkpoint {input_path} must be a JSON list of venue rows, "
            f"got {type(data).__name__}."
        )
    return data


def _ensure_venue_id(row: dict[str, Any], index: int) -> dict[str, Any]:
    """Return ``row`` with a ``venueId``, deriving one for hand-added rows.

    Product-added rows normally already carry a stable ``venueId``. When one is
    absent (or blank), derive it deterministically from ``name`` + ``area`` via
    the manual scheme so the same hand-added venue always maps to the same doc.
    """
    venue_id = row.get("venueId")
    if isinstance(venue_id, str) and venue_id.strip():
        return row

    name = row.get("name")
    area = row.get("area")
    if not (isinstance(name, str) and name.strip()) or not (
        isinstance(area, str) and area.strip()
    ):
        raise CheckpointValidationError(
            f"Row {index}: missing venueId and cannot derive one — "
            f"need both a non-empty name and area, got name={name!r} area={area!r}."
        )
    derived = venue_id_for_manual(name, area)
    return {**row, "venueId": derived}


def validate_row(row: dict[str, Any], index: int) -> VenueSummary:
    """Validate one raw checkpoint row into a ``VenueSummary``.

    Derives a ``venueId`` for hand-added rows first, then validates the model and
    enforces ``area`` membership. Raises :class:`CheckpointValidationError` with
    the offending index/``venueId`` on any failure.
    """
    if not isinstance(row, dict):
        raise CheckpointValidationError(
            f"Row {index}: expected a JSON object, got {type(row).__name__}."
        )
    prepared = _ensure_venue_id(row, index)
    try:
        venue = VenueSummary.model_validate(prepared)
    except ValidationError as exc:
        raise CheckpointValidationError(
            f"Row {index} (venueId={prepared.get('venueId')!r}) failed "
            f"VenueSummary validation: {exc}"
        ) from exc
    if venue.area not in ALLOWED_AREAS:
        raise CheckpointValidationError(
            f"Row {index} (venueId={venue.venue_id!r}) has invalid area "
            f"{venue.area!r}; expected one of {sorted(ALLOWED_AREAS)}."
        )
    return venue


def validate_rows(rows: list[dict[str, Any]]) -> list[VenueSummary]:
    """Validate every row before any write happens (validate-all, write-after)."""
    return [validate_row(row, index) for index, row in enumerate(rows)]


def classify_change(existing: dict[str, Any] | None, target: dict[str, Any]) -> str:
    """Classify a target doc against the existing one as created/updated/unchanged."""
    if existing is None:
        return "created"
    if existing == target:
        return "unchanged"
    return "updated"


def ingest_venues(
    client: firestore.Client,
    venues: list[VenueSummary],
    collection: str = VENUES_COLLECTION,
) -> IngestSummary:
    """Upsert validated venues into ``{collection}/{venueId}`` idempotently.

    Each row is compared against its existing document and only written when it
    is new or changed; unchanged rows are skipped so re-runs perform zero writes.
    """
    created = 0
    updated = 0
    unchanged = 0
    for venue in venues:
        doc_ref = client.collection(collection).document(venue.venue_id)
        target = venue_summary_to_firestore_doc(venue)
        snapshot = doc_ref.get()
        existing = snapshot.to_dict() if snapshot.exists else None
        change = classify_change(existing, target)
        if change == "created":
            created += 1
            doc_ref.set(target, merge=False)
        elif change == "updated":
            updated += 1
            doc_ref.set(target, merge=False)
        else:
            unchanged += 1
    return IngestSummary(created=created, updated=updated, unchanged=unchanged)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest an approved venue checkpoint into venues/{venueId} (emulator only)."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Approved checkpoint JSON (default: tools/data/venue_checkpoint.json).",
    )
    parser.add_argument(
        "--env",
        default="emu",
        choices=["emu"],
        help="Environment to ingest into; only 'emu' (Firestore emulator) is supported.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args()
    if args.env != "emu":
        print("Error: only --env=emu (Firestore emulator) is supported.", file=sys.stderr)
        sys.exit(1)

    emulator_host = os.getenv("FIRESTORE_EMULATOR_HOST")
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")

    # Safety: refuse to run unless clearly pointing at the emulator on localhost.
    if not emulator_host:
        print("Refusing to run: FIRESTORE_EMULATOR_HOST is not set.", file=sys.stderr)
        sys.exit(1)
    if not (emulator_host.startswith("localhost") or emulator_host.startswith("127.0.0.1")):
        print(
            "Refusing to run ingest: FIRESTORE_EMULATOR_HOST is not pointing at localhost.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not project_id:
        print("Refusing to run: GOOGLE_CLOUD_PROJECT is not set.", file=sys.stderr)
        sys.exit(1)

    rows = load_checkpoint(args.input)
    # Validate everything before writing anything — a bad row aborts the run.
    venues = validate_rows(rows)

    client = firestore.Client(project=project_id)
    summary = ingest_venues(client, venues)
    logger.info(
        "Ingested %d venue rows from %s: %d created, %d updated, %d unchanged.",
        summary.total,
        args.input,
        summary.created,
        summary.updated,
        summary.unchanged,
    )


if __name__ == "__main__":
    main()
