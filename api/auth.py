"""
Dhandho AI — api/auth.py
Firebase ID Token verification dependency for FastAPI.

Usage in any protected route:
    from api.auth import get_current_user, UserClaims

    @router.get("/protected")
    async def protected(user: UserClaims = Depends(get_current_user)):
        return {"uid": user.uid}
"""

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel
from firebase_admin import auth as firebase_auth

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UserClaims — typed wrapper around the verified Firebase token
# ---------------------------------------------------------------------------
class UserClaims(BaseModel):
    uid: str
    email: Optional[str] = None
    name: Optional[str] = None
    picture: Optional[str] = None
    email_verified: bool = False


# ---------------------------------------------------------------------------
# Dependency: get_current_user
# ---------------------------------------------------------------------------
async def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> UserClaims:
    """
    FastAPI dependency that:
    1. Reads the `Authorization: Bearer <token>` header.
    2. Verifies the Firebase ID token via the Admin SDK.
    3. Returns a ``UserClaims`` object on success.
    4. Raises HTTP 401 on any failure.

    NOTE: firebase_admin must be initialised (via connect_to_firebase) before
    any request arrives, otherwise token verification will fail.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected: 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    id_token = parts[1].strip()
    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is empty.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        decoded = firebase_auth.verify_id_token(id_token)
    except firebase_auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase ID token has expired. Please re-authenticate.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except firebase_auth.RevokedIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase ID token has been revoked. Please re-authenticate.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except firebase_auth.InvalidIdTokenError as exc:
        logger.warning("Invalid Firebase ID token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Firebase ID token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as exc:
        logger.error("Unexpected error verifying Firebase token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UserClaims(
        uid=decoded.get("uid", ""),
        email=decoded.get("email"),
        name=decoded.get("name"),
        picture=decoded.get("picture"),
        email_verified=decoded.get("email_verified", False),
    )


# ---------------------------------------------------------------------------
# Optional variant — does NOT raise 401 if header is absent (guest users)
# ---------------------------------------------------------------------------
async def get_optional_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Optional[UserClaims]:
    """
    Same as get_current_user but returns None instead of raising 401
    when no Authorization header is provided. Use for routes that work
    both anonymously and with a logged-in user.
    """
    if not authorization:
        return None
    try:
        return await get_current_user(authorization=authorization)
    except HTTPException:
        return None
