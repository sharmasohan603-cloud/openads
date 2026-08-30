"""JWT-based authentication for the OpenAds API.

Credentials are loaded from environment variables (never hardcoded):
  - ADMIN_USERNAME  (required)
  - ADMIN_PASSWORD  (required)
  - JWT_SECRET_KEY  (required — HARD FAIL if missing, no random fallback)

The random fallback was removed because it silently invalidates all active
sessions on every process restart, making the system appear to work while
actually breaking login for all users.

Usage in routes:
    from auth import require_auth
    @router.get("/protected")
    async def protected(user: str = Depends(require_auth)):
        ...
"""

import os
import time
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import jwt  # PyJWT

# ── Configuration (from env — all required in production) ─────────────────
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

# HARD FAIL if JWT_SECRET_KEY is not set — no silent random fallback.
# A random fallback would mean every restart invalidates all tokens.
_raw_secret = os.environ.get("JWT_SECRET_KEY", "")
if not _raw_secret:
    raise RuntimeError(
        "JWT_SECRET_KEY environment variable is required but not set. "
        "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )
JWT_SECRET = _raw_secret

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "24"))

_bearer_scheme = HTTPBearer(auto_error=False)


# ── Token helpers ─────────────────────────────────────────────────────────
def create_token(username: str) -> str:
    """Create a signed JWT token that expires after JWT_EXPIRE_HOURS."""
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRE_HOURS * 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[str]:
    """Verify a JWT and return the username, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


# ── FastAPI dependency ────────────────────────────────────────────────────
async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency: extracts and validates the Bearer token.

    Returns the username on success, raises 401 on failure.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = verify_token(credentials.credentials)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


def authenticate_user(username: str, password: str) -> Optional[str]:
    """Validate credentials and return a JWT token, or None if invalid."""
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        return create_token(username)
    return None
