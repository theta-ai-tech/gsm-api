from __future__ import annotations

import argparse
import os
import socket
import sys

from google.cloud import firestore  # type: ignore[import-untyped]
from google.cloud.firestore_v1.field_path import FieldPath  # type: ignore[import-untyped]

RPC_TIMEOUT_SECONDS = 20
DEFAULT_BATCH_SIZE = 400


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill participantPair field on matches/{matchId} documents."
    )
    parser.add_argument("--env", choices=["emu", "dev"], required=True)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print intended updates without writing."
    )
    parser.add_argument("--project", help="Project id (required for dev if env var not set).")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Maximum writes per batch commit.",
    )
    return parser.parse_args()


def _project_id(args: argparse.Namespace) -> str:
    project = args.project or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("FIREBASE_PROJECT_ID")
    if not project:
        raise RuntimeError("Missing project id. Use --project or set GOOGLE_CLOUD_PROJECT.")
    return project


def _validate_env(args: argparse.Namespace) -> None:
    if args.env != "emu":
        return
    host = os.getenv("FIRESTORE_EMULATOR_HOST")
    if not host:
        raise RuntimeError("FIRESTORE_EMULATOR_HOST must be set for --env emu.")
    if not (host.startswith("localhost") or host.startswith("127.0.0.1")):
        raise RuntimeError("Refusing --env emu: FIRESTORE_EMULATOR_HOST must point to localhost.")
    host_name, sep, port_raw = host.partition(":")
    if not sep or not port_raw.isdigit():
        raise RuntimeError("FIRESTORE_EMULATOR_HOST must be in host:port format.")
    sock = socket.socket()
    sock.settimeout(1.5)
    try:
        sock.connect((host_name, int(port_raw)))
    except OSError as exc:
        raise RuntimeError(
            f"Firestore emulator not reachable at {host}. Start it with: make emu-firestore"
        ) from exc
    finally:
        sock.close()


def _compute_participant_pair(uids: list[str]) -> str | None:
    if len(uids) != 2:
        return None
    return "_".join(sorted(uids))


def main() -> int:
    args = _parse_args()
    if args.batch_size <= 0 or args.batch_size > 500:
        print("Error: --batch-size must be between 1 and 500.", file=sys.stderr)
        return 1

    try:
        _validate_env(args)
        project = _project_id(args)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    client = firestore.Client(project=project)
    scanned_docs = 0
    changed_docs = 0
    writes_in_batch = 0
    batch = client.batch()

    docs = (
        client.collection("matches")
        .order_by(FieldPath.document_id())
        .stream(timeout=RPC_TIMEOUT_SECONDS)
    )

    for doc in docs:
        scanned_docs += 1
        data = doc.to_dict() or {}

        if data.get("participantPair") is not None:
            continue

        uids = data.get("participantUids") or []
        pair = _compute_participant_pair(uids)
        if pair is None:
            print(f"[SKIP] matches/{doc.id} — {len(uids)} participant(s), cannot compute pair")
            continue

        changed_docs += 1
        if args.dry_run:
            print(f"[DRY-RUN] matches/{doc.id} -> participantPair={pair}")
            continue

        batch.update(doc.reference, {"participantPair": pair})
        writes_in_batch += 1
        print(f"[UPDATED] matches/{doc.id} -> participantPair={pair}")
        if writes_in_batch >= args.batch_size:
            batch.commit()
            batch = client.batch()
            writes_in_batch = 0

    if not args.dry_run and writes_in_batch > 0:
        batch.commit()

    action = "would update" if args.dry_run else "updated"
    print(f"Done: scanned={scanned_docs}, {action}={changed_docs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
