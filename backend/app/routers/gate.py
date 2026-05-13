"""Simple shared-password access gate.

A single shared password protects all API routes. On correct submission,
the backend returns an HMAC-derived token. Clients can present the token
either as a long-lived HttpOnly cookie (preferred — desktop) or as an
`Authorization: Bearer <token>` header (required for browsers that block
cross-site cookies, e.g. iOS Safari / Vivaldi on iOS, Firefox mobile).
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
    """Check if the request has a valid session token via cookie OR Authorization header."""
    if not settings.APP_SECRET:
        return True  # No secret configured — gate disabled
    expected = _compute_token()
    # Cookie path (desktop / same-site)
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie and secrets.compare_digest(cookie, expected):
        return True
    # Bearer-token path (mobile / cross-site cookie blocked)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):].strip()
        if token and secrets.compare_digest(token, expected):
            return True
    return False


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
    # Also return the token so clients on browsers that block cross-site
    # cookies (iOS Safari, mobile Firefox with Total Cookie Protection)
    # can store it client-side and present it as a Bearer header.
    return {"status": "ok", "token": token}


@router.get("/check")
async def check_auth(request: Request) -> dict:
    """Frontend calls this to check if already authenticated."""
    return {"authenticated": is_authenticated(request)}
