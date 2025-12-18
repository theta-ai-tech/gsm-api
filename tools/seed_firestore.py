import argparse
import os
import sys

from google.cloud import firestore


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Firestore emulator with GSM data (C2).")
    parser.add_argument(
        "--env",
        default="emu",
        choices=["emu"],
        help="Environment to seed; only 'emu' (Firestore emulator) is supported.",
    )
    return parser.parse_args()


def main() -> None:
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
            "Refusing to run seed script: FIRESTORE_EMULATOR_HOST is not pointing at localhost.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not project_id:
        print("Refusing to run: GOOGLE_CLOUD_PROJECT is not set.", file=sys.stderr)
        sys.exit(1)

    client = firestore.Client(project=project_id)
    print(f"Connected to Firestore emulator for project {project_id} (no data seeded yet).")


if __name__ == "__main__":
    main()
