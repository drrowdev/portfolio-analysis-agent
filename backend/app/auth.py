"""Microsoft personal account (MSAL) token validation.

This module validates ID tokens issued by the Microsoft identity platform
for personal Microsoft accounts (consumers tenant). It is designed to be
used as an optional FastAPI dependency — routes can add it when auth
enforcement is desired, but it is NOT applied globally so local
development continues to work without authentication.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, Request

from app.config import settings

logger = logging.getLogger(__name__)

# Microsoft personal-accounts ("consumers") tenant
JWKS_URL = "https://login.microsoftonline.com/consumers/discovery/v2.0/keys"
ISSUER = "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0"


@lru_cache(maxsize=1)
def _get_jwks() -> dict[str, Any]:
    """Fetch Microsoft's public signing keys (cached in-process)."""
    resp = httpx.get(JWKS_URL, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _clear_jwks_cache() -> None:
    """Clear the JWKS cache — useful if key rotation causes validation errors."""
    _get_jwks.cache_clear()


async def get_current_user(request: Request) -> dict[str, Any]:
    """Validate the Bearer token and return the decoded claims.

    Intended for use as a FastAPI dependency:

        @router.get("/protected")
        async def protected(user: dict = Depends(get_current_user)):
            ...
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")

    token = auth_header.split(" ", 1)[1]
    client_id = settings.MSAL_CLIENT_ID

    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="MSAL_CLIENT_ID not configured on the server",
        )

    try:
        jwks = _get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        matching_key = next(
            (k for k in jwks["keys"] if k["kid"] == kid), None
        )
        if matching_key is None:
            # Key may have rotated — clear cache and retry once
            _clear_jwks_cache()
            jwks = _get_jwks()
            matching_key = next(
                (k for k in jwks["keys"] if k["kid"] == kid), None
            )
            if matching_key is None:
                raise ValueError(f"No matching signing key for kid={kid}")

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(matching_key)

        payload: dict[str, Any] = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=ISSUER,
        )
        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as exc:
        logger.warning("Token validation failed: %s", exc)
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
    except Exception as exc:
        logger.exception("Unexpected auth error")
        raise HTTPException(status_code=401, detail=f"Auth error: {exc}")
