from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one
from app.core.deps import AdminUser, CurrentUser
from app.schemas.organization import (
    InvitationCreate,
    InvitationResponse,
    MemberResponse,
    MemberRoleUpdate,
    OrgResponse,
    OrgUpdate,
)
from app.services.email_service import send_invitation_email

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/me", response_model=OrgResponse)
def get_my_organization(current_user: CurrentUser) -> OrgResponse:
    """Get the current user's organization."""
    org = fetch_one(
        "SELECT id, name, logo_url, created_at FROM organizations WHERE id = ?",
        (current_user["organization_id"],),
    )
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return OrgResponse(**org)


@router.put("/me", response_model=OrgResponse)
def update_my_organization(body: OrgUpdate, current_user: AdminUser) -> OrgResponse:
    """Update the current user's organization (admin only)."""
    org_id = current_user["organization_id"]

    updates: list[str] = []
    params: list[str] = []
    if body.name is not None:
        updates.append("name = ?")
        params.append(body.name)
    if body.logo_url is not None:
        updates.append("logo_url = ?")
        params.append(body.logo_url)

    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    params.append(org_id)
    execute(f"UPDATE organizations SET {', '.join(updates)} WHERE id = ?", tuple(params))

    org = fetch_one(
        "SELECT id, name, logo_url, created_at FROM organizations WHERE id = ?",
        (org_id,),
    )
    return OrgResponse(**org)  # type: ignore[arg-type]


@router.get("/me/members", response_model=list[MemberResponse])
def list_members(current_user: CurrentUser) -> list[MemberResponse]:
    """List all members of the current user's organization."""
    members = fetch_all(
        "SELECT id, email, name, role, email_verified, created_at FROM users WHERE organization_id = ? ORDER BY created_at",
        (current_user["organization_id"],),
    )
    return [MemberResponse(**m) for m in members]


@router.post("/me/invitations", response_model=InvitationResponse, status_code=201)
def create_invitation(body: InvitationCreate, current_user: AdminUser) -> InvitationResponse:
    """Invite a new member to the organization (admin only)."""
    org_id = current_user["organization_id"]

    # Check if user already exists in this org
    existing = fetch_one(
        "SELECT id FROM users WHERE email = ? AND organization_id = ?",
        (body.email, org_id),
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this organization",
        )

    # Check for pending invitation
    pending = fetch_one(
        "SELECT id FROM invitations WHERE email = ? AND organization_id = ? AND status = 'pending'",
        (body.email, org_id),
    )
    if pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An invitation is already pending for this email",
        )

    invitation_id = secrets.token_hex(16)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    execute(
        """INSERT INTO invitations (id, organization_id, email, role, invited_by, expires_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (invitation_id, org_id, body.email, body.role, current_user["id"], expires_at),
    )

    # Get org name for the email
    org = fetch_one("SELECT name FROM organizations WHERE id = ?", (org_id,))
    org_name = org["name"] if org else "Unknown"

    send_invitation_email(
        to=body.email,
        org_name=org_name,
        inviter_name=current_user["name"],
        invitation_id=invitation_id,
        base_url=settings.CLIENT_URL,
    )

    invitation = fetch_one(
        "SELECT id, email, role, status, invited_by, created_at, expires_at FROM invitations WHERE id = ?",
        (invitation_id,),
    )
    return InvitationResponse(**invitation)  # type: ignore[arg-type]


@router.post("/me/invitations/{invitation_id}/accept", response_model=MemberResponse)
def accept_invitation(invitation_id: str, current_user: CurrentUser) -> MemberResponse:
    """Accept an organization invitation."""
    invitation = fetch_one(
        "SELECT id, organization_id, email, role, status, expires_at FROM invitations WHERE id = ?",
        (invitation_id,),
    )
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")

    if invitation["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invitation is no longer pending")

    if invitation["email"] != current_user["email"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This invitation is not for you")

    # Check expiry
    expires_at = datetime.fromisoformat(invitation["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        execute("UPDATE invitations SET status = 'expired' WHERE id = ?", (invitation_id,))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invitation has expired")

    # Move user to the new organization
    execute(
        "UPDATE users SET organization_id = ?, role = ? WHERE id = ?",
        (invitation["organization_id"], invitation["role"], current_user["id"]),
    )
    execute("UPDATE invitations SET status = 'accepted' WHERE id = ?", (invitation_id,))

    user = fetch_one(
        "SELECT id, email, name, role, email_verified, created_at FROM users WHERE id = ?",
        (current_user["id"],),
    )
    return MemberResponse(**user)  # type: ignore[arg-type]


@router.put("/me/members/{member_id}", response_model=MemberResponse)
def update_member_role(member_id: str, body: MemberRoleUpdate, current_user: AdminUser) -> MemberResponse:
    """Update a team member's role (admin only)."""
    org_id = current_user["organization_id"]

    member = fetch_one(
        "SELECT id, organization_id FROM users WHERE id = ? AND organization_id = ?",
        (member_id, org_id),
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    if member_id == current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role",
        )

    execute("UPDATE users SET role = ? WHERE id = ?", (body.role, member_id))

    updated = fetch_one(
        "SELECT id, email, name, role, email_verified, created_at FROM users WHERE id = ?",
        (member_id,),
    )
    return MemberResponse(**updated)  # type: ignore[arg-type]


@router.delete("/me/members/{member_id}", status_code=204)
def remove_member(member_id: str, current_user: AdminUser):
    """Remove a member from the organization (admin only)."""
    org_id = current_user["organization_id"]

    if member_id == current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove yourself from the organization",
        )

    member = fetch_one(
        "SELECT id FROM users WHERE id = ? AND organization_id = ?",
        (member_id, org_id),
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    execute("DELETE FROM users WHERE id = ? AND organization_id = ?", (member_id, org_id))
    return None
