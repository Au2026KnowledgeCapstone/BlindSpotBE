from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, current_user, get_token_verifier
from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import register_exception_handlers
from app.core.observability import RequestIdMiddleware, configure_logging

configure_logging("api")
# Eagerly construct the configured TokenVerifier so a misconfigured
# DevTokenVerifier refuses to start the process, not just the first request.
get_token_verifier()

settings = get_settings()

app = FastAPI(title="BlindSpot Backend")
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
register_exception_handlers(app)


@app.get("/")
def liveness(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/me")
def me(user: AuthenticatedUser = Depends(current_user)) -> dict:
    return {"user_id": user.user_id, "email": user.email}
