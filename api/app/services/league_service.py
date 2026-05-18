from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models import LeagueMember
from app.models.enums import LeagueMemberStatusEnum, LeagueRoleEnum, LeagueStatusEnum
from app.repos.leagues_repo import LeaguesRepo


class LeagueService:
    def __init__(self, leagues_repo: LeaguesRepo, firestore_client: firestore.Client):
        self.leagues_repo = leagues_repo
        self.client = firestore_client

    def join_league(self, league_id: str, uid: str) -> LeagueMember:
        # Fast pre-checks (non-transactional — stable data)
        league = self.leagues_repo.get_by_id(league_id)
        if league is None:
            raise ValueError(f"League {league_id!r} not found")

        if league.status not in (LeagueStatusEnum.OPEN, LeagueStatusEnum.UPCOMING):
            raise ValueError(
                f"Cannot join league with status {league.status!r}; must be OPEN or UPCOMING"
            )

        now = datetime.now(timezone.utc)
        member_data = {
            "role": LeagueRoleEnum.PLAYER.value,
            "status": LeagueMemberStatusEnum.ACTIVE.value,
            "joinedAt": now,
            "stats": None,
        }

        transaction = self.client.transaction()

        @firestore.transactional
        def _join_txn(txn: firestore.Transaction) -> None:
            member_ref = (
                self.client.collection("leagues")
                .document(league_id)
                .collection("members")
                .document(uid)
            )
            league_ref = self.client.collection("leagues").document(league_id)

            # Reads must come before writes in a Firestore transaction
            member_doc = member_ref.get(transaction=txn)
            league_doc = league_ref.get(transaction=txn)

            if member_doc.exists:
                raise ValueError(f"User {uid!r} is already a member of league {league_id!r}")

            if league_doc.exists:
                data = league_doc.to_dict() or {}
                status_val = data.get("status")
                if status_val not in (LeagueStatusEnum.OPEN.value, LeagueStatusEnum.UPCOMING.value):
                    raise ValueError(
                        f"Cannot join league with status {status_val!r}; must be OPEN or UPCOMING"
                    )
                current = data.get("currentPlayers")
                max_p = data.get("maxPlayers")
                if current is not None and max_p is not None and current >= max_p:
                    raise ValueError(f"League {league_id!r} is at full capacity")

            txn.set(member_ref, member_data)
            txn.update(league_ref, {"currentPlayers": firestore.Increment(1)})

        _join_txn(transaction)

        return LeagueMember(
            uid=uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=now,
            stats=None,
        )
