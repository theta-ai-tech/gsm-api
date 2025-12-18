from typing import Any, Dict

from app.models import (
    CursorBundle,
    JournalEntry,
    JournalEntrySummary,
    League,
    LeagueMember,
    LeagueSummary,
    Match,
    MatchParticipant,
    MatchScore,
    PerSportLevels,
    PerSportRankings,
    PrivateUserProfile,
    SetScore,
    SportRanking,
    UserCompletedMatchSummary,
    UserMatchSummary,
)


def _sport_ranking_to_dict(ranking: SportRanking) -> Dict[str, Any]:
    return {
        "sport": ranking.sport,
        "pts": ranking.pts,
        "globalRanking": ranking.global_ranking,
    }


def _per_sport_rankings_to_dict(rankings: PerSportRankings) -> Dict[str, Any]:
    return {
        "tennis": _sport_ranking_to_dict(rankings.tennis) if rankings.tennis else None,
        "padel": _sport_ranking_to_dict(rankings.padel) if rankings.padel else None,
        "pickleball": _sport_ranking_to_dict(rankings.pickleball) if rankings.pickleball else None,
    }


def _per_sport_levels_to_dict(levels: PerSportLevels) -> Dict[str, Any]:
    return {
        "tennis": levels.tennis.value if levels.tennis else None,
        "padel": levels.padel.value if levels.padel else None,
        "pickleball": levels.pickleball.value if levels.pickleball else None,
    }


def _league_summary_to_dict(summary: LeagueSummary) -> Dict[str, Any]:
    return {
        "leagueId": summary.league_id,
        "name": summary.name,
        "sport": summary.sport,
        "status": summary.status,
        "role": summary.role,
    }


def _user_match_summary_to_dict(summary: UserMatchSummary) -> Dict[str, Any]:
    return {
        "matchId": summary.match_id,
        "sport": summary.sport,
        "scheduledAt": summary.scheduled_at,
        "leagueId": summary.league_id,
        "courtId": summary.court_id,
        "opponents": [{"uid": opp.uid, "name": opp.name} for opp in summary.opponents],
    }


def _user_completed_match_summary_to_dict(summary: UserCompletedMatchSummary) -> Dict[str, Any]:
    return {
        "matchId": summary.match_id,
        "sport": summary.sport,
        "finishedAt": summary.finished_at,
        "result": summary.result,
        "scoreText": summary.score_text,
        "leagueId": summary.league_id,
    }


def _journal_entry_summary_to_dict(summary: JournalEntrySummary) -> Dict[str, Any]:
    return {
        "entryId": summary.entry_id,
        "createdAt": summary.created_at,
        "title": summary.title,
        "matchId": summary.match_id,
        "sport": summary.sport,
    }


def _cursors_to_dict(cursors: CursorBundle | None) -> Dict[str, Any] | None:
    if cursors is None:
        return None
    return {
        "upcomingMatches": cursors.upcoming_matches,
        "completedMatches": cursors.completed_matches,
        "journal": cursors.journal,
    }


def user_to_firestore_doc(user: PrivateUserProfile) -> Dict[str, Any]:
    return {
        "uid": user.uid,
        "name": user.name,
        "email": user.email,
        "profileUrl": user.profile_url,
        "phone": user.phone,
        "rankings": _per_sport_rankings_to_dict(user.rankings),
        "preferences": {
            "area": user.preferences.area,
            "levels": _per_sport_levels_to_dict(user.preferences.levels),
            "sports": user.preferences.sports,
        },
        "leaguesActive": [_league_summary_to_dict(l) for l in user.leagues_active],
        "leaguesCompleted": [_league_summary_to_dict(l) for l in user.leagues_completed],
        "upcomingMatches": [_user_match_summary_to_dict(m) for m in user.upcoming_matches],
        "completedMatches": [_user_completed_match_summary_to_dict(m) for m in user.completed_matches],
        "journalRecent": [_journal_entry_summary_to_dict(j) for j in user.journal_recent],
        "cursors": _cursors_to_dict(user.cursors),
    }


def league_to_firestore_doc(league: League) -> Dict[str, Any]:
    return {
        "name": league.name,
        "sport": league.sport,
        "season": league.season,
        "status": league.status,
        "ownerUid": league.owner_uid,
        "meta": league.meta or {},
    }


def league_member_to_firestore_doc(member: LeagueMember) -> Dict[str, Any]:
    return {
        "uid": member.uid,
        "role": member.role,
        "status": member.status,
        "joinedAt": member.joined_at,
        "stats": member.stats or {},
    }


def _set_score_to_dict(score: SetScore) -> Dict[str, Any]:
    return {
        "p1Games": score.p1_games,
        "p2Games": score.p2_games,
        "tiebreakScore": score.tiebreak_score,
    }


def _match_score_to_dict(score: MatchScore | None) -> Dict[str, Any] | None:
    if score is None:
        return None
    return {
        "sets": [_set_score_to_dict(s) for s in score.sets],
        "winnerUid": score.winner_uid,
        "retired": score.retired,
    }


def _participant_to_dict(p: MatchParticipant) -> Dict[str, Any]:
    return {
        "uid": p.uid,
        "team": p.team,
        "role": p.role,
        "result": p.result,
    }


def match_to_firestore_doc(match: Match) -> Dict[str, Any]:
    return {
        "sport": match.sport,
        "status": match.status,
        "scheduledAt": match.scheduled_at,
        "finishedAt": match.finished_at,
        "leagueId": match.league_id,
        "courtId": match.court_id,
        "participants": [_participant_to_dict(p) for p in match.participants],
        "participantUids": match.participant_uids,
        "resultByUser": match.result_by_user,
        "score": _match_score_to_dict(match.score),
    }


def journal_entry_to_firestore_doc(entry: JournalEntry) -> Dict[str, Any]:
    return {
        "title": entry.title,
        "body": entry.body,
        "tags": entry.tags,
        "createdAt": entry.created_at,
        "matchId": entry.match_id,
        "sport": entry.sport,
        "visibility": entry.visibility,
    }
