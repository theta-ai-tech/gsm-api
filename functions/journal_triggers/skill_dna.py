from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.logging_utils import log_event

_TRIGGER_UPSERT = "onJournalEntryWrite.D4.1"
_TRIGGER_DELETE = "onJournalEntryWrite.D4.2"

# Module-level taxonomy cache — one Firestore read per cold start.
_tag_map_cache: dict[str, str] | None = None


def load_tag_map(client: firestore.Client) -> dict[str, str]:
    """Return tagMap from config/skillTaxonomy. Cached for the process lifetime."""
    global _tag_map_cache
    if _tag_map_cache is not None:
        return _tag_map_cache
    doc = client.collection("config").document("skillTaxonomy").get()
    _tag_map_cache = {} if not doc.exists else (doc.to_dict() or {}).get("tagMap") or {}
    return _tag_map_cache


# ---------------------------------------------------------------------------
# Pure helpers (fully testable without Firestore)
# ---------------------------------------------------------------------------


def make_sig(went_well: list[str], went_wrong: list[str]) -> str:
    """Deterministic signature for a set of reflection tags (used for idempotency)."""
    return ",".join(sorted(went_well)) + "|" + ",".join(sorted(went_wrong))


def parse_sig(sig: str) -> tuple[list[str], list[str]]:
    """Parse a stored signature back to (went_well, went_wrong) lists."""
    parts = sig.split("|", 1)
    well = [t for t in parts[0].split(",") if t]
    wrong = [t for t in (parts[1] if len(parts) > 1 else "").split(",") if t]
    return well, wrong


def tags_to_axis_counts(
    went_well: list[str],
    went_wrong: list[str],
    tag_map: dict[str, str],
) -> dict[str, dict[str, int]]:
    """Map reflection tags → per-axis positive/negative counts via tag_map."""
    counts: dict[str, dict[str, int]] = {}
    for tag in went_well:
        axis = tag_map.get(tag)
        if axis:
            counts.setdefault(axis, {"positive": 0, "negative": 0})["positive"] += 1
    for tag in went_wrong:
        axis = tag_map.get(tag)
        if axis:
            counts.setdefault(axis, {"positive": 0, "negative": 0})["negative"] += 1
    return counts


def compute_score(positive: int, negative: int) -> int:
    """round(positive / total * 100); returns 0 if fewer than 3 data points."""
    total = positive + negative
    if total < 3:
        return 0
    return round(positive / total * 100)


def apply_skill_dna_delta(
    current: dict[str, Any],
    old_sig: str | None,
    new_sig: str | None,
    tag_map: dict[str, str],
    entry_id: str,
    now: datetime,
) -> dict[str, Any]:
    """
    Pure function. Apply an old_sig → new_sig delta to a sport's Skill DNA map.

    old_sig = None, new_sig set  → first-time create
    old_sig set, new_sig set     → update (diff)
    old_sig set, new_sig = None  → delete
    """
    dna = dict(current)
    sigs: dict[str, str] = dict(dna.get("entrySignatures") or {})

    old_counts: dict[str, dict[str, int]] = {}
    if old_sig is not None:
        old_well, old_wrong = parse_sig(old_sig)
        old_counts = tags_to_axis_counts(old_well, old_wrong, tag_map)

    new_counts: dict[str, dict[str, int]] = {}
    if new_sig is not None:
        new_well, new_wrong = parse_sig(new_sig)
        new_counts = tags_to_axis_counts(new_well, new_wrong, tag_map)

    for axis in set(old_counts) | set(new_counts):
        old_p = old_counts.get(axis, {}).get("positive", 0)
        old_n = old_counts.get(axis, {}).get("negative", 0)
        new_p = new_counts.get(axis, {}).get("positive", 0)
        new_n = new_counts.get(axis, {}).get("negative", 0)
        cur = dna.get(axis) or {"positive": 0, "negative": 0, "score": 0}
        final_p = max(0, int(cur.get("positive", 0)) + (new_p - old_p))
        final_n = max(0, int(cur.get("negative", 0)) + (new_n - old_n))
        dna[axis] = {
            "positive": final_p,
            "negative": final_n,
            "score": compute_score(final_p, final_n),
        }

    total = int(dna.get("totalReflections") or 0)
    if old_sig is None and new_sig is not None:
        total += 1
    elif old_sig is not None and new_sig is None:
        total = max(0, total - 1)
    dna["totalReflections"] = total

    if new_sig is not None:
        sigs[entry_id] = new_sig
    else:
        sigs.pop(entry_id, None)
    dna["entrySignatures"] = sigs
    dna["lastUpdated"] = now
    return dna


# ---------------------------------------------------------------------------
# Transactional Firestore writer
# ---------------------------------------------------------------------------


def _write_skill_dna(
    client: firestore.Client,
    uid: str,
    entry_id: str,
    sport: str,
    new_sig: str | None,
    tag_map: dict[str, str],
    now: datetime,
) -> bool:
    user_ref = client.collection("users").document(uid)
    txn = client.transaction()

    @firestore.transactional
    def _apply(t: firestore.Transaction) -> bool:
        snap = user_ref.get(transaction=t)
        if not snap.exists:
            return False
        data = snap.to_dict() or {}
        skill_dna: dict[str, Any] = dict(data.get("skillDna") or {})
        sport_dna: dict[str, Any] = dict(skill_dna.get(sport) or {})
        old_sig: str | None = (sport_dna.get("entrySignatures") or {}).get(entry_id)

        # Idempotency: same signature → already processed this exact version.
        if old_sig == new_sig:
            return False

        updated = apply_skill_dna_delta(
            current=sport_dna,
            old_sig=old_sig,
            new_sig=new_sig,
            tag_map=tag_map,
            entry_id=entry_id,
            now=now,
        )
        skill_dna[sport] = updated
        t.update(user_ref, {"skillDna": skill_dna})
        return True

    return _apply(txn)


# ---------------------------------------------------------------------------
# Trigger entry points
# ---------------------------------------------------------------------------


def handle_skill_dna_upsert(
    client: firestore.Client,
    uid: str,
    entry_id: str,
    after: dict[str, Any],
    tag_map: dict[str, str] | None = None,
) -> bool:
    """Aggregate reflection tags into skillDna on create or update (D4.1)."""
    trigger = _TRIGGER_UPSERT
    sport: str | None = after.get("sport")
    if not sport:
        log_event(trigger=trigger, action="ignore", uid=uid, entryId=entry_id, reason="no_sport")
        return False

    reflection = after.get("reflection") or {}
    went_well: list[str] = reflection.get("wentWell") or []
    went_wrong: list[str] = reflection.get("wentWrong") or []
    if not went_well and not went_wrong:
        log_event(
            trigger=trigger,
            action="ignore",
            uid=uid,
            entryId=entry_id,
            reason="no_reflection_tags",
        )
        return False

    if tag_map is None:
        tag_map = load_tag_map(client)

    now = datetime.now(tz=timezone.utc)
    new_sig = make_sig(went_well, went_wrong)
    changed = _write_skill_dna(
        client=client,
        uid=uid,
        entry_id=entry_id,
        sport=sport,
        new_sig=new_sig,
        tag_map=tag_map,
        now=now,
    )
    log_event(
        trigger=trigger,
        action="upsert",
        uid=uid,
        entryId=entry_id,
        sport=sport,
        changed=changed,
        writes_count=1 if changed else 0,
    )
    return changed


def handle_skill_dna_delete(
    client: firestore.Client,
    uid: str,
    entry_id: str,
    before: dict[str, Any],
    tag_map: dict[str, str] | None = None,
) -> bool:
    """Remove a deleted entry's contribution from skillDna (D4.2)."""
    trigger = _TRIGGER_DELETE
    sport: str | None = before.get("sport")
    if not sport:
        log_event(trigger=trigger, action="ignore", uid=uid, entryId=entry_id, reason="no_sport")
        return False

    if tag_map is None:
        tag_map = load_tag_map(client)

    now = datetime.now(tz=timezone.utc)
    changed = _write_skill_dna(
        client=client,
        uid=uid,
        entry_id=entry_id,
        sport=sport,
        new_sig=None,
        tag_map=tag_map,
        now=now,
    )
    log_event(
        trigger=trigger,
        action="remove",
        uid=uid,
        entryId=entry_id,
        sport=sport,
        changed=changed,
        writes_count=1 if changed else 0,
    )
    return changed
