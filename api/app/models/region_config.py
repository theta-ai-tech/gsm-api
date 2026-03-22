from app.models.base import GsmBaseModel


class RegionConfig(GsmBaseModel):
    mapping: dict[str, str]
    version: int
