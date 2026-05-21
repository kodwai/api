from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.core.admin_deps import AdminUser
from app.core.database import fetch_one
from app.core.security import create_access_token, verify_password

router = APIRouter(tags=["admin-auth"])


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def admin_login(body: AdminLoginRequest) -> dict:
    """Admin login — verifies credentials and is_superadmin flag, returns admin JWT."""
    user = fetch_one(
        "SELECT id, email, password_hash, name, is_superadmin, email_verified FROM users WHERE email = ?",
        (body.email,),
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user["is_superadmin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an admin")

    # Create admin JWT with type claim
    token = create_access_token({"sub": user["id"], "type": "admin"})

    return {
        "access_token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
        },
    }


@router.get("/me")
def admin_me(current_admin: AdminUser) -> dict:
    """Get current admin user info."""
    return {
        "id": current_admin["id"],
        "email": current_admin["email"],
        "name": current_admin["name"],
        "is_superadmin": current_admin["is_superadmin"],
    }
