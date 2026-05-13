"""Simple cookie-based access gate.

A single shared password protects all API routes. On correct submission,
a long-lived secure cookie is set. Subsequent requests are validated by
checking the cookie value matches a HMAC of the secret.
"""

import hashlib
import hmac
import secrets

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "paa_session"
COOKIE_MAX_AGE = 365 * 24 * 3600  # 1 year


def _compute_token() -> str:
    """Derive a cookie token from the secret (deterministic)."""
    return hmac.new(
        key=b"portfolio-analysis-agent",
        msg=settings.APP_SECRET.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


def is_authenticated(request: Request) -> bool:
    """Check if the request has a valid session cookie."""
    if not settings.APP_SECRET:
        return True  # No secret configured — gate disabled
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return False
    return secrets.compare_digest(cookie, _compute_token())


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginRequest, response: Response) -> dict:
    if not settings.APP_SECRET:
        return {"status": "ok", "message": "No gate configured"}

    if not secrets.compare_digest(body.password, settings.APP_SECRET):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid password"},
        )

    token = _compute_token()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="none",
    )
    return {"status": "ok"}


@router.get("/check")
async def check_auth(request: Request) -> dict:
    """Frontend calls this to check if already authenticated."""
    return {"authenticated": is_authenticated(request)}
