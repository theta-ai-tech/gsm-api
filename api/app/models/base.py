from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, EmailStr, HttpUrl, field_validator


class GsmBaseModel(BaseModel):
    """Shared base for GSM models with strict fields and UTC-normalized datetimes."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        from_attributes=True,
    )

    @field_validator("*", mode="before")
    @classmethod
    def _ensure_aware_datetime(cls, value: object) -> object:
        """
        Normalize naive datetimes to UTC so all stored/returned times are timezone-aware.
        Non-datetime values pass through unchanged.
        """
        if isinstance(value, datetime):
            if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
                return value.replace(tzinfo=timezone.utc)
        return value


__all__ = [
    "GsmBaseModel",
    "EmailStr",
    "HttpUrl",
]
