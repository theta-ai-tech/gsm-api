"""Guard: the committed Cloud Monitoring policy files are valid and well-formed.

Catches a malformed alert policy before an operator tries to `gcloud monitoring
policies create` it against a live project.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MON_DIR = REPO_ROOT / "monitoring"

POLICY_FILES = sorted(MON_DIR.glob("*.json"))


def test_monitoring_dir_has_policies():
    names = {p.name for p in POLICY_FILES}
    expected = {
        "alert-5xx-rate.json",
        "alert-p95-latency.json",
        "alert-function-failures.json",
        "alert-firestore-quota.json",
        "alert-uptime.json",
    }
    assert expected.issubset(names), f"missing policy files: {expected - names}"


@pytest.mark.parametrize("policy_file", POLICY_FILES, ids=lambda p: p.name)
def test_policy_is_valid(policy_file: Path):
    data = json.loads(policy_file.read_text(encoding="utf-8"))
    assert data.get("displayName"), f"{policy_file.name}: missing displayName"
    assert data.get("combiner"), f"{policy_file.name}: missing combiner"
    conditions = data.get("conditions")
    assert isinstance(conditions, list) and conditions, (
        f"{policy_file.name}: needs at least one condition"
    )
    # Every alert must route to the notification channel placeholder.
    assert data.get("notificationChannels") == ["${NOTIFICATION_CHANNEL}"], (
        f"{policy_file.name}: notificationChannels must be the substitutable placeholder"
    )
    for cond in conditions:
        threshold = cond.get("conditionThreshold", {})
        assert threshold.get("filter"), f"{policy_file.name}: condition missing filter"
        assert threshold.get("comparison"), (
            f"{policy_file.name}: condition missing comparison"
        )
