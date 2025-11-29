from fastapi import Depends, FastAPI, Path
from fastapi.middleware.cors import CORSMiddleware

from app.deps import get_current_user
from app.security import CurrentUser, require_self
from app.settings import get_settings

app = FastAPI(title="GSM API", version="0.1.0")

settings = get_settings()

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/users/{uid}")
def get_user(
    uid: str = Path(..., min_length=1),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_self(uid, current_user)
    return {
        "uid": current_user.uid,
        "email": current_user.email,
        "picture": current_user.picture,
    }
