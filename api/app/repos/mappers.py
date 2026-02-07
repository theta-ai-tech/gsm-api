from __future__ import annotations

from typing import Any, List, Optional

from app.models import (
    AvailabilityEnum,
    Broadcast,
    BroadcastLocation,
    BroadcastStatusEnum,
    CourtStatusEnum,
    CursorBundle,
    GeoLocation,
    JournalEntry,
    JournalEntrySummary,
    JournalVisibilityEnum,
    League,
    LeagueMember,
    LeagueMemberStatusEnum,
    LeagueRoleEnum,
    LeagueStatusEnum,
    LeagueSummary,
    LevelEnum,
    Match,
    MatchOpponentSummary,
    MatchParticipant,
    MatchResultEnum,
    MatchScore,
    MatchStatusEnum,
    Offer,
    OfferStatusEnum,
    ParticipantRoleEnum,
    PerSportLevels,
    PerSportRankings,
    PrivateUserProfile,
    PublicUserProfile,
    SetScore,
    SportEnum,
    SportRanking,
    UserCompletedMatchSummary,
    UserMatchSummary,
    UserPreferences,
)


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data or data.get(key) is None:
        raise ValueError(f"Missing required field: {key}")
    return data[key]


def _parse_sport_ranking(data: Optional[dict[str, Any]]) -> Optional[SportRanking]:
    if not data:
        return None
    sport_val = _require(data, "sport")
    return SportRanking(
        sport=SportEnum(sport_val), pts=data.get("pts", 0), global_ranking=data.get("globalRanking")
    )


def _parse_per_sport_rankings(data: dict[str, Any]) -> PerSportRankings:
    return PerSportRankings(
        tennis=_parse_sport_ranking(data.get("tennis")),
        padel=_parse_sport_ranking(data.get("padel")),
        pickleball=_parse_sport_ranking(data.get("pickleball")),
    )


def _parse_per_sport_levels(data: dict[str, Any]) -> PerSportLevels:
    def _lvl(val: Any) -> Optional[LevelEnum]:
        return LevelEnum(val) if val else None

    return PerSportLevels(
        tennis=_lvl(data.get("tennis")),
        padel=_lvl(data.get("padel")),
        pickleball=_lvl(data.get("pickleball")),
    )


def _parse_user_preferences(data: dict[str, Any]) -> UserPreferences:
    levels = _parse_per_sport_levels(data.get("levels", {}) or {})
    sports = [SportEnum(s) for s in data.get("sports", [])]
    return UserPreferences(area=data.get("area", 0), levels=levels, sports=sports)


def _parse_league_summary(data: dict[str, Any]) -> LeagueSummary:
    role = data.get("role")
    return LeagueSummary(
        league_id=str(_require(data, "leagueId")),
        name=data.get("name", ""),
        sport=SportEnum(_require(data, "sport")),
        status=LeagueStatusEnum(_require(data, "status")),
        role=LeagueRoleEnum(role) if role else None,
    )


def _parse_match_opponents(items: list[dict[str, Any]]) -> List[MatchOpponentSummary]:
    return [MatchOpponentSummary(uid=item.get("uid", ""), name=item.get("name")) for item in items]


def _parse_user_match_summary(data: dict[str, Any]) -> UserMatchSummary:
    return UserMatchSummary(
        match_id=str(_require(data, "matchId")),
        sport=SportEnum(_require(data, "sport")),
        scheduled_at=_require(data, "scheduledAt"),
        league_id=data.get("leagueId"),
        court_id=data.get("courtId"),
        opponents=_parse_match_opponents(data.get("opponents", [])),
    )


def _parse_user_completed_match_summary(data: dict[str, Any]) -> UserCompletedMatchSummary:
    result = data.get("result")
    return UserCompletedMatchSummary(
        match_id=str(_require(data, "matchId")),
        sport=SportEnum(_require(data, "sport")),
        finished_at=_require(data, "finishedAt"),
        result=MatchResultEnum(result) if result else None,
        score_text=data.get("scoreText"),
        league_id=data.get("leagueId"),
    )


def _parse_journal_entry_summary(data: dict[str, Any]) -> JournalEntrySummary:
    sport = data.get("sport")
    return JournalEntrySummary(
        entry_id=str(_require(data, "entryId")),
        created_at=_require(data, "createdAt"),
        title=data.get("title", ""),
        match_id=data.get("matchId"),
        sport=SportEnum(sport) if sport else None,
    )


def _parse_cursors(data: dict[str, Any] | None) -> Optional[CursorBundle]:
    if not data:
        return None
    return CursorBundle(
        upcoming_matches=data.get("upcomingMatches"),
        completed_matches=data.get("completedMatches"),
        journal=data.get("journal"),
    )


def to_public_user_profile(doc: dict[str, Any]) -> PublicUserProfile:
    rankings = _parse_per_sport_rankings(doc.get("rankings", {}) or {})

    def _league_summary_list(key: str) -> List[LeagueSummary]:
        return [_parse_league_summary(item) for item in doc.get(key, [])]

    return PublicUserProfile(
        uid=str(doc.get("uid") or doc.get("id") or ""),
        name=doc.get("name", ""),
        profile_url=doc.get("profileUrl"),
        rankings=rankings,
        leagues_active=_league_summary_list("leaguesActive"),
        leagues_completed=_league_summary_list("leaguesCompleted"),
    )


def to_private_user_profile(doc: dict[str, Any]) -> PrivateUserProfile:
    public = to_public_user_profile(doc)

    def _list_or_empty(key: str) -> list[Any]:
        return doc.get(key, []) or []

    return PrivateUserProfile(
        **public.model_dump(),
        email=doc.get("email", ""),
        phone=doc.get("phone"),
        preferences=_parse_user_preferences(doc.get("preferences", {}) or {}),
        upcoming_matches=[
            _parse_user_match_summary(item) for item in _list_or_empty("upcomingMatches")
        ],
        completed_matches=[
            _parse_user_completed_match_summary(item) for item in _list_or_empty("completedMatches")
        ],
        journal_recent=[
            _parse_journal_entry_summary(item) for item in _list_or_empty("journalRecent")
        ],
        cursors=_parse_cursors(doc.get("cursors")),
    )


def _parse_participant(data: dict[str, Any]) -> MatchParticipant:
    role = data.get("role")
    result = data.get("result")
    return MatchParticipant(
        uid=str(data.get("uid", "")),
        team=data.get("team"),
        role=ParticipantRoleEnum(role) if role else ParticipantRoleEnum.PLAYER,
        result=MatchResultEnum(result) if result else None,
    )


def _parse_score(score: dict[str, Any]) -> Optional[MatchScore]:
    if not score:
        return None
    sets_raw = score.get("sets", []) or []
    sets = [
        SetScore(
            p1_games=item.get("p1Games", 0),
            p2_games=item.get("p2Games", 0),
            tiebreak_score=item.get("tiebreakScore"),
        )
        for item in sets_raw
    ]
    return MatchScore(
        sets=sets, winner_uid=score.get("winnerUid"), retired=score.get("retired", False)
    )


def to_match(doc: dict[str, Any], match_id: str | None = None) -> Match:
    participants = [_parse_participant(p) for p in doc.get("participants", [])]
    result_by_user = doc.get("resultByUser") or None
    if result_by_user:
        result_by_user = {uid: MatchResultEnum(val) for uid, val in result_by_user.items()}

    sport_val = _require(doc, "sport")
    status_val = _require(doc, "status")

    return Match(
        match_id=match_id or doc.get("match_id") or doc.get("id") or "",
        sport=SportEnum(sport_val),
        status=MatchStatusEnum(status_val),
        scheduled_at=doc.get("scheduledAt"),
        finished_at=doc.get("finishedAt"),
        league_id=doc.get("leagueId"),
        court_id=doc.get("courtId"),
        score=_parse_score(doc.get("score", {})),
        result_by_user=result_by_user,
        participants=participants,
        participant_uids=doc.get("participantUids", []),
    )


def to_league(doc: dict[str, Any], league_id: str | None = None) -> League:
    sport_val = _require(doc, "sport")
    status_val = _require(doc, "status")
    return League(
        league_id=league_id or doc.get("id") or "",
        name=doc.get("name", ""),
        sport=SportEnum(sport_val),
        season=doc.get("season"),
        status=LeagueStatusEnum(status_val),
        owner_uid=doc.get("ownerUid", ""),
        meta=doc.get("meta"),
    )


def to_league_member(doc: dict[str, Any], uid: str | None = None) -> LeagueMember:
    role_val = _require(doc, "role")
    status_val = _require(doc, "status")
    return LeagueMember(
        uid=uid or doc.get("uid", ""),
        role=LeagueRoleEnum(role_val),
        status=LeagueMemberStatusEnum(status_val),
        joined_at=_require(doc, "joinedAt"),
        stats=doc.get("stats"),
    )


def to_journal_entry(
    doc: dict[str, Any], entry_id: str | None = None, uid: str | None = None
) -> JournalEntry:
    visibility = _require(doc, "visibility")
    sport = doc.get("sport")
    return JournalEntry(
        entry_id=entry_id or doc.get("id") or "",
        uid=uid or doc.get("uid") or "",
        created_at=_require(doc, "createdAt"),
        title=doc.get("title", ""),
        body=doc.get("body", ""),
        tags=doc.get("tags", []),
        match_id=doc.get("matchId"),
        sport=SportEnum(sport) if sport else None,
        visibility=JournalVisibilityEnum(visibility),
    )


def _parse_geo_location(data: dict[str, Any] | None) -> Optional[GeoLocation]:
    if not data:
        return None
    return GeoLocation(lat=data.get("lat", 0.0), lng=data.get("lng", 0.0))


def _parse_broadcast_location(data: dict[str, Any]) -> BroadcastLocation:
    return BroadcastLocation(
        area=data.get("area"),
        geo=_parse_geo_location(data.get("geo")),
        radius_km=data.get("radiusKm"),
    )


def to_broadcast(doc: dict[str, Any], broadcast_id: str | None = None) -> Broadcast:
    sport_val = _require(doc, "sport")
    availability_val = _require(doc, "availability")
    court_status_val = _require(doc, "courtStatus")
    status_val = _require(doc, "status")
    owner_ranking = _parse_sport_ranking(doc.get("ownerRanking"))

    return Broadcast(
        broadcast_id=broadcast_id or doc.get("id") or "",
        owner_uid=_require(doc, "ownerUid"),
        owner_name=doc.get("ownerName", ""),
        owner_ranking=owner_ranking,
        sport=SportEnum(sport_val),
        availability=AvailabilityEnum(availability_val),
        court_status=CourtStatusEnum(court_status_val),
        court_location=doc.get("courtLocation"),
        status=BroadcastStatusEnum(status_val),
        expires_at=_require(doc, "expiresAt"),
        created_at=_require(doc, "createdAt"),
        location=_parse_broadcast_location(doc.get("location", {}) or {}),
    )


def to_offer(doc: dict[str, Any], offer_id: str | None = None) -> Offer:
    sport_val = _require(doc, "sport")
    status_val = _require(doc, "status")
    from_ranking = _parse_sport_ranking(doc.get("fromRanking"))
    to_ranking = _parse_sport_ranking(doc.get("toRanking"))

    return Offer(
        offer_id=offer_id or doc.get("id") or "",
        from_uid=_require(doc, "fromUid"),
        from_name=doc.get("fromName", ""),
        from_ranking=from_ranking,
        to_uid=_require(doc, "toUid"),
        to_name=doc.get("toName", ""),
        to_ranking=to_ranking,
        sport=SportEnum(sport_val),
        proposed_time=_require(doc, "proposedTime"),
        court_location=doc.get("courtLocation"),
        message=doc.get("message"),
        status=OfferStatusEnum(status_val),
        expires_at=_require(doc, "expiresAt"),
        created_at=_require(doc, "createdAt"),
        match_id=doc.get("matchId"),
    )
