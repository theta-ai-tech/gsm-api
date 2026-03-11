from pydantic import Field

from app.models.base import GsmBaseModel


class SkillTaxonomy(GsmBaseModel):
    axes: list[str]
    tag_map: dict[str, str] = Field(alias="tagMap")
    version: int
