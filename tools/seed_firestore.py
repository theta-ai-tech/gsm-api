"""
Manual test:
1) Start Firestore emulator (e.g., `firebase emulators:start --only firestore`).
2) Ensure FIRESTORE_EMULATOR_HOST and GOOGLE_CLOUD_PROJECT are set.
3) Run `make seed-emu`.
4) Inspect emulator UI: users, leagues, matches collections, and journalEntries subcollections exist.
"""

import argparse
import os
import sys

from google.cloud import firestore

from tools.seed_data import (
    REGION_MAPPING,
    SAMPLE_BROADCASTS,
    SAMPLE_JOURNAL_ENTRIES,
    SAMPLE_LEADERBOARDS,
    SAMPLE_LEAGUE_MEMBERS,
    SAMPLE_LEAGUE_TEAMS,
    SAMPLE_LEAGUES,
    SAMPLE_MATCHES,
    SAMPLE_POINT_HISTORY,
    SAMPLE_SCOUTING_PROFILES,
    SAMPLE_TICKER_EVENTS,
    SAMPLE_USERS,
    SKILL_TAXONOMY,
    TIER_AVERAGES,
    TIER_CONFIG,
    utc,
)
from tools.seed_mapping import (
    journal_entry_to_firestore_doc,
    leaderboard_snapshot_to_firestore_doc,
    league_member_to_firestore_doc,
    league_team_to_firestore_doc,
    league_to_firestore_doc,
    match_to_firestore_doc,
    point_history_entry_to_firestore_doc,
    region_config_to_firestore_doc,
    scouting_profile_to_firestore_doc,
    skill_taxonomy_to_firestore_doc,
    ticker_event_to_firestore_doc,
    tier_averages_to_firestore_doc,
    tier_config_to_firestore_doc,
    user_to_firestore_doc,
    venue_summary_to_firestore_doc,
)
from tools.seed_venues import SAMPLE_VENUES


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Firestore emulator with GSM data (C2).")
    parser.add_argument(
        "--env",
        default="emu",
        choices=["emu"],
        help="Environment to seed; only 'emu' (Firestore emulator) is supported.",
    )
    return parser.parse_args()


def seed_all(client: firestore.Client) -> None:
    for user in SAMPLE_USERS:
        doc_ref = client.collection("users").document(user.uid)
        doc_ref.set(user_to_firestore_doc(user))

    for league in SAMPLE_LEAGUES:
        doc_ref = client.collection("leagues").document(league.league_id)
        doc_ref.set(league_to_firestore_doc(league))
        for existing in doc_ref.collection("members").stream():
            existing.reference.delete()
        for member in SAMPLE_LEAGUE_MEMBERS.get(league.league_id, []):
            member_ref = doc_ref.collection("members").document(member.uid)
            member_ref.set(league_member_to_firestore_doc(member))
        for existing in doc_ref.collection("teams").stream():
            existing.reference.delete()
        for team in SAMPLE_LEAGUE_TEAMS.get(league.league_id, []):
            team_ref = doc_ref.collection("teams").document(team.team_id)
            team_ref.set(league_team_to_firestore_doc(team))

    for match in SAMPLE_MATCHES:
        doc_ref = client.collection("matches").document(match.match_id)
        doc_ref.set(match_to_firestore_doc(match))

    for broadcast_id, broadcast_doc in SAMPLE_BROADCASTS:
        doc_ref = client.collection("broadcasts").document(broadcast_id)
        doc_ref.set(broadcast_doc)

    for entry in SAMPLE_JOURNAL_ENTRIES:
        doc_ref = (
            client.collection("users")
            .document(entry.uid)
            .collection("journalEntries")
            .document(entry.entry_id)
        )
        doc_ref.set(journal_entry_to_firestore_doc(entry))

    for uid, entries in SAMPLE_POINT_HISTORY:
        for entry in entries:
            doc_ref = (
                client.collection("users")
                .document(uid)
                .collection("pointHistory")
                .document(entry.entry_id)
            )
            doc_ref.set(point_history_entry_to_firestore_doc(entry))

    # Leaderboard snapshots
    for snapshot in SAMPLE_LEADERBOARDS:
        doc_id = f"{snapshot.region}_{snapshot.sport.value}"
        doc_ref = client.collection("leaderboards").document(doc_id)
        doc_ref.set(leaderboard_snapshot_to_firestore_doc(snapshot))

    # Scouting profiles
    for profile in SAMPLE_SCOUTING_PROFILES:
        doc_ref = client.collection("scouting").document(profile.uid)
        doc_ref.set(scouting_profile_to_firestore_doc(profile))

    # Config documents
    client.collection("config").document("tiers").set(
        tier_config_to_firestore_doc(TIER_CONFIG)
    )
    client.collection("config").document("skillTaxonomy").set(
        skill_taxonomy_to_firestore_doc(SKILL_TAXONOMY)
    )
    client.collection("config").document("tierAverages").set(
        tier_averages_to_firestore_doc(TIER_AVERAGES)
    )
    client.collection("config").document("regions").set(
        region_config_to_firestore_doc(REGION_MAPPING)
    )

    # Ticker events
    for event in SAMPLE_TICKER_EVENTS:
        doc_ref = client.collection("ticker").document(event.event_id)
        doc_ref.set(ticker_event_to_firestore_doc(event))

    # Venues
    for venue in SAMPLE_VENUES:
        doc_ref = client.collection("venues").document(venue.venue_id)
        doc_ref.set(venue_summary_to_firestore_doc(venue))

    # Venue suggestions — pending moderation queue for demo/review flow
    _venue_suggestions = [
        {
            "name": "Kifissia Padel Club",
            "coordinates": {"lat": 38.0733, "lng": 23.8142},
            "sport": "padel",
            "notes": "New padel courts in Kifissia, 4 courts, indoor",
            "suggestedBy": "user_ignatios",
            "createdAt": utc(2026, 3, 20, 10, 0),
            "status": "pending",
        },
        {
            "name": "Maroussi Sports Center",
            "coordinates": {"lat": 38.0567, "lng": 23.8091},
            "sport": "tennis",
            "notes": None,
            "suggestedBy": "user_alice",
            "createdAt": utc(2026, 3, 22, 14, 30),
            "status": "pending",
        },
    ]
    for i, suggestion in enumerate(_venue_suggestions):
        doc_ref = client.collection("venueSuggestions").document(f"suggestion-seed-{i + 1}")
        doc_ref.set(suggestion)


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
    seed_all(client)
    total_ph = sum(len(entries) for _, entries in SAMPLE_POINT_HISTORY)
    print(
        "Seeded "
        f"{len(SAMPLE_USERS)} users, "
        f"{len(SAMPLE_LEAGUES)} leagues, "
        f"{len(SAMPLE_MATCHES)} matches, "
        f"{len(SAMPLE_BROADCASTS)} broadcasts, "
        f"{len(SAMPLE_JOURNAL_ENTRIES)} journal entries, "
        f"{total_ph} point history entries, "
        f"{len(SAMPLE_LEADERBOARDS)} leaderboard snapshots, "
        f"{len(SAMPLE_SCOUTING_PROFILES)} scouting profiles, "
        f"{len(SAMPLE_TICKER_EVENTS)} ticker events, "
        f"{len(SAMPLE_VENUES)} venues, "
        f"2 venue suggestions, "
        f"1 tier config, "
        f"1 skill taxonomy, "
        f"1 tier averages, "
        f"1 region config "
        f"into Firestore emulator project {project_id}."
    )


if __name__ == "__main__":
    main()
