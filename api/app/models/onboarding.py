from pydantic import EmailStr, model_validator

from app.models.base import GsmBaseModel
from app.models.common import PerSportLevels
from app.models.enums import SportEnum


class RegisterMeRequest(GsmBaseModel):
    name: str
    email: EmailStr | None = None
    sports: list[SportEnum]
    levels: PerSportLevels
    area: int
    profile_url: str | None = None

    @model_validator(mode="after")
    def levels_cover_sports(self) -> "RegisterMeRequest":
        for sport in self.sports:
            level = getattr(self.levels, sport.value, None)
            if level is None:
                raise ValueError(
                    f"levels.{sport.value} is required when {sport.value} is in sports"
                )
        return self
