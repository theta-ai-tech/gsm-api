from __future__ import annotations

import argparse
import os
import socket
import sys
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]
from google.cloud.firestore_v1.field_path import FieldPath  # type: ignore[import-untyped]

RPC_TIMEOUT_SECONDS = 20
DEFAULT_BATCH_SIZE = 400


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill missing fields on users/{uid}/journalEntries documents."
    )
    parser.add_argument("--env", choices=["emu", "dev"], required=True)
    parser.add_argument("--uid", help="Backfill a single user.")
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


def _backfill_updates(data: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {}

    if not data.get("entryType"):
        updates["entryType"] = "match"
    if "trainingFocus" not in data:
        updates["trainingFocus"] = []
    if "durationMinutes" not in data:
        updates["durationMinutes"] = None
    if "reflection" not in data:
        updates["reflection"] = None
    if "scoreText" not in data:
        updates["scoreText"] = None
    if "result" not in data:
        updates["result"] = None
    if "tags" not in data:
        updates["tags"] = []
    if "body" not in data:
        updates["body"] = ""
    if "title" not in data:
        updates["title"] = ""
    if "visibility" not in data:
        updates["visibility"] = "private"
    if "clientRequestId" not in data:
        updates["clientRequestId"] = None
    if "isDeleted" not in data:
        updates["isDeleted"] = False
    if "deletedAt" not in data:
        updates["deletedAt"] = None

    return updates


def _user_ids(client: firestore.Client, uid: str | None) -> list[str]:
    if uid:
        return [uid]
    docs = (
        client.collection("users")
        .order_by(FieldPath.document_id())
        .stream(timeout=RPC_TIMEOUT_SECONDS)
    )
    return [doc.id for doc in docs]


def _entry_docs(client: firestore.Client, uid: str):
    return (
        client.collection("users")
        .document(uid)
        .collection("journalEntries")
        .order_by(FieldPath.document_id())
        .stream(timeout=RPC_TIMEOUT_SECONDS)
    )


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

    for uid in _user_ids(client, args.uid):
        for doc in _entry_docs(client, uid):
            scanned_docs += 1
            data = doc.to_dict() or {}
            updates = _backfill_updates(data)
            if not updates:
                continue

            changed_docs += 1
            path = f"users/{uid}/journalEntries/{doc.id}"
            fields = ",".join(sorted(updates.keys()))
            if args.dry_run:
                print(f"[DRY-RUN] {path} -> fields={fields}")
                continue

            batch.update(doc.reference, updates)
            writes_in_batch += 1
            print(f"[UPDATED] {path} -> fields={fields}")
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
