"""Admin authentication dependencies."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import fetch_one
from app.core.security import verify_token

admin_bearer = HTTPBearer()


def get_current_admin(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(admin_bearer)],
) -> dict[str, Any]:
    """Extract and validate admin user from Authorization header.

    Checks that the JWT has type="admin" and the user has is_superadmin=1.
    """
    payload = verify_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin token",
        )

    # Must be an admin token
    if payload.get("type") != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not an admin token",
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = fetch_one(
        "SELECT id, email, name, role, user_type, is_superadmin FROM users WHERE id = ?",
        (user_id,),
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not user["is_superadmin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")

    return user


AdminUser = Annotated[dict[str, Any], Depends(get_current_admin)]
