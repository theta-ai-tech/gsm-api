"""Integration tests for D7 tier averages computation against Firestore emulator."""

from __future__ import annotations

import pytest
from google.cloud import firestore

from functions.scoring_triggers.tier_averages import compute_and_write_tier_averages

pytestmark = pytest.mark.integration

_AXES = ("serve", "power", "net_play", "stamina", "mental")


def _seed_user(
    client: firestore.Client,
    uid: str,
    sport: str,
    tier: str,
    axes: dict[str, int],
) -> None:
    dna_axes: dict = {
        axis: {"positive": 5, "negative": 2, "score": score}
        for axis, score in axes.items()
    }
    dna_axes["totalReflections"] = 3
    client.collection("users").document(uid).set(
        {
            "uid": uid,
            "name": uid,
            "rankings": {sport: {"sport": sport, "pts": 1000, "tier": tier}},
            "skillDna": {sport: dna_axes},
        }
    )


@pytest.fixture(autouse=True)
def _cleanup_tier_averages(db: firestore.Client):
    yield
    db.collection("config").document("tierAverages").delete()
    for doc in db.collection("users").stream():
        db.collection("users").document(doc.id).delete()


class TestComputeAndWriteTierAverages:
    def test_basic_computation_writes_to_firestore(self, db: firestore.Client) -> None:
        _seed_user(db, "u1", "tennis", "amateur", {"serve": 60, "power": 40})
        _seed_user(db, "u2", "tennis", "amateur", {"serve": 80, "power": 50})

        result = compute_and_write_tier_averages(db)

        assert result["amateur"]["tennis"]["serve"] == 70
        assert result["amateur"]["tennis"]["power"] == 45
        assert "updatedAt" in result

        doc = db.collection("config").document("tierAverages").get()
        assert doc.exists
        data = doc.to_dict() or {}
        assert data["amateur"]["tennis"]["serve"] == 70

    def test_multiple_tiers_and_sports(self, db: firestore.Client) -> None:
        _seed_user(db, "u1", "tennis", "amateur", {"serve": 40})
        _seed_user(db, "u2", "padel", "intermediate", {"serve": 80})

        result = compute_and_write_tier_averages(db)

        assert result["amateur"]["tennis"]["serve"] == 40
        assert result["intermediate"]["padel"]["serve"] == 80

    def test_no_users_writes_empty_doc(self, db: firestore.Client) -> None:
        result = compute_and_write_tier_averages(db)

        assert "updatedAt" in result
        doc = db.collection("config").document("tierAverages").get()
        assert doc.exists
        data = doc.to_dict() or {}
        for tier in ("amateur", "intermediate", "advanced", "competitive"):
            assert tier not in data

    def test_user_without_skill_dna_is_excluded(self, db: firestore.Client) -> None:
        db.collection("users").document("u_no_dna").set(
            {
                "uid": "u_no_dna",
                "rankings": {
                    "tennis": {"sport": "tennis", "pts": 1000, "tier": "amateur"}
                },
            }
        )
        _seed_user(db, "u1", "tennis", "amateur", {"serve": 50})

        result = compute_and_write_tier_averages(db)

        assert result["amateur"]["tennis"]["serve"] == 50

    def test_overwrites_previous_doc(self, db: firestore.Client) -> None:
        _seed_user(db, "u1", "tennis", "amateur", {"serve": 40})
        compute_and_write_tier_averages(db)

        db.collection("users").document("u1").delete()
        _seed_user(db, "u2", "tennis", "amateur", {"serve": 80})
        result = compute_and_write_tier_averages(db)

        assert result["amateur"]["tennis"]["serve"] == 80

    def test_all_five_axes(self, db: firestore.Client) -> None:
        axes = {"serve": 10, "power": 20, "net_play": 30, "stamina": 40, "mental": 50}
        _seed_user(db, "u1", "tennis", "amateur", axes)

        result = compute_and_write_tier_averages(db)

        for axis, expected in axes.items():
            assert result["amateur"]["tennis"][axis] == expected
