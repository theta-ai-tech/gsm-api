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
        league = self.leagues_repo.get_by_id(league_id)
        if league is None:
            raise ValueError(f"League {league_id!r} not found")

        if league.status not in (LeagueStatusEnum.OPEN, LeagueStatusEnum.UPCOMING):
            raise ValueError(
                f"Cannot join league with status {league.status!r}; must be OPEN or UPCOMING"
            )

        existing_members = self.leagues_repo.list_members(league_id)
        if any(m.uid == uid for m in existing_members):
            raise ValueError(f"User {uid!r} is already a member of league {league_id!r}")

        if league.max_players is not None and league.current_players is not None:
            if league.current_players >= league.max_players:
                raise ValueError(f"League {league_id!r} is at full capacity")

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
            txn.set(member_ref, member_data)
            league_ref = self.client.collection("leagues").document(league_id)
            txn.update(league_ref, {"currentPlayers": firestore.Increment(1)})

        _join_txn(transaction)

        return LeagueMember(
            uid=uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=now,
            stats=None,
        )
