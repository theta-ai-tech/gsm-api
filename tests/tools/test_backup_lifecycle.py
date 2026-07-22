"""Guard: the GCS backup-bucket lifecycle config is valid and enforces retention."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE_PATH = REPO_ROOT / "deploy" / "backup-bucket-lifecycle.json"


def test_lifecycle_parses_and_deletes_after_30_days():
    data = json.loads(LIFECYCLE_PATH.read_text(encoding="utf-8"))
    rules = data.get("rule")
    assert isinstance(rules, list) and rules, "lifecycle must define at least one rule"
    delete_rules = [r for r in rules if r.get("action", {}).get("type") == "Delete"]
    assert delete_rules, "lifecycle must delete old backups"
    # 30-day retention per the issue (guards against an accidental unbounded bucket).
    assert any(r.get("condition", {}).get("age") == 30 for r in delete_rules), (
        "expected a Delete rule with age == 30 days"
    )
