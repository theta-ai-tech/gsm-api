from app.models.base import GsmBaseModel
from app.models.enums import SportEnum


class ShareCardData(GsmBaseModel):
    """Client-side model — not served by API, just documents the data shape.

    The 'Share Your Grind' card is rendered entirely from data already cached
    on the client (JournalEntry + UserStats).  This model exists so the client
    team has a typed reference and backend can validate if a share endpoint is
    added later.
    """

    result_text: str  # "VICTORY" / "DEFEAT"
    score_text: str  # "6-4 7-5"
    opponent_name: str
    sport: SportEnum
    rating_delta: int  # +100
    rank: int | None = None  # #42
    streak: str | None = None  # "5W"
    date: str  # "February 16, 2026"
