from pydantic import Field

from app.models.base import GsmBaseModel
from app.models.enums import PlatformEnum


class RegisterDeviceTokenRequest(GsmBaseModel):
    token: str = Field(min_length=1)
    platform: PlatformEnum
    app_version: str | None = Field(default=None, alias="appVersion")


class DeleteDeviceTokenRequest(GsmBaseModel):
    token: str = Field(min_length=1)
