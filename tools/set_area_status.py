"""Flip a region's venue ``status`` in bulk (e.g. launching a not-yet-live area).

Ingest writes ``status="hidden"`` on every venue whose ``area`` is outside
:data:`tools.ingest_venues.LIVE_AREAS`. When that region launches, this tool
flips its venues from ``hidden`` to ``live`` so ``VenueRepo``'s client-visible
query (``status in ["live", "unverified"]``) starts returning them.

``--from`` matters: filtering on both ``area`` AND ``status == from_status``
means launching a region only touches the rows explicitly in that state — a
pre-existing ``unverified`` row in the same area (a real court flagged for
user confirmation) is left untouched, exactly as it should be.

Target
------
Emulator only (``--env=emu``), matching ``tools/ingest_venues.py``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from google.cloud import firestore

from app.models.enums import VenueStatusEnum

logger = logging.getLogger("set_area_status")

# Firestore collection curated venues live in (mirrors VenueRepo.COLLECTION).
VENUES_COLLECTION = "venues"

# Firestore batch writes cap at 500 operations; commit in smaller chunks to
# stay safely under that limit.
_BATCH_CHUNK_SIZE = 400


def set_area_status(
    client: firestore.Client,
    area: str,
    from_status: str,
    to_status: str,
    collection: str = VENUES_COLLECTION,
) -> int:
    """Flip every ``{collection}`` doc in ``area`` with ``status == from_status``.

    Only rows matching BOTH ``area`` and ``status == from_status`` are
    touched — a row in the same area with a different status (e.g.
    ``unverified``) is left as-is. Writes are batched. Returns the number of
    documents updated.
    """
    query = client.collection(collection).where("area", "==", area).where(
        "status", "==", from_status
    )
    updated = 0
    batch = client.batch()
    for doc in query.stream():
        batch.update(doc.reference, {"status": to_status})
        updated += 1
        if updated % _BATCH_CHUNK_SIZE == 0:
            batch.commit()
            batch = client.batch()
    if updated % _BATCH_CHUNK_SIZE != 0:
        batch.commit()
    return updated


def _parse_args() -> argparse.Namespace:
    status_choices = [e.value for e in VenueStatusEnum]
    parser = argparse.ArgumentParser(
        description="Flip a region's venue status in bulk (emulator only)."
    )
    parser.add_argument("--area", required=True, help="Area slug to flip, e.g. 'lavrio'.")
    parser.add_argument(
        "--from",
        dest="from_status",
        required=True,
        choices=status_choices,
        help="Current status to match.",
    )
    parser.add_argument(
        "--to",
        dest="to_status",
        required=True,
        choices=status_choices,
        help="Status to flip matched rows to.",
    )
    parser.add_argument(
        "--env",
        default="emu",
        choices=["emu"],
        help="Environment to write to; only 'emu' (Firestore emulator) is supported.",
    )
    args = parser.parse_args()
    if args.from_status == args.to_status:
        parser.error("--from and --to must be different statuses.")
    return args


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
            "Refusing to run set_area_status: FIRESTORE_EMULATOR_HOST is not "
            "pointing at localhost.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not project_id:
        print("Refusing to run: GOOGLE_CLOUD_PROJECT is not set.", file=sys.stderr)
        sys.exit(1)

    client = firestore.Client(project=project_id)
    updated = set_area_status(client, args.area, args.from_status, args.to_status)
    if updated == 0:
        logger.info(
            "No venues in area=%r with status=%r; nothing to update.",
            args.area,
            args.from_status,
        )
    else:
        logger.info(
            "Flipped %d venue(s) in area=%r from status=%r to status=%r.",
            updated,
            args.area,
            args.from_status,
            args.to_status,
        )


if __name__ == "__main__":
    main()
