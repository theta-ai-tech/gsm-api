import os
from functools import lru_cache
from typing import List

from pydantic import BaseModel


class Settings(BaseModel):
    project_id: str
    cors_origins: List[str] = []
    auth_emulator_host: str | None = None

    @property
    def issuer(self) -> str:
        return f"https://securetoken.google.com/{self.project_id}"


@lru_cache
def get_settings() -> Settings:
    project_id = os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise RuntimeError(
            "Set FIREBASE_PROJECT_ID (or GOOGLE_CLOUD_PROJECT) for Firebase Auth checks"
        )

    cors_raw = os.getenv("CORS_ORIGINS", "")
    cors_origins = [origin.strip() for origin in cors_raw.split(",") if origin.strip()]

    return Settings(
        project_id=project_id,
        cors_origins=cors_origins,
        auth_emulator_host=os.getenv("FIREBASE_AUTH_EMULATOR_HOST"),
    )
