from __future__ import annotations

import logging

import resend

from app.core.config import settings

logger = logging.getLogger(__name__)


def _configure_resend() -> None:
    """Set the Resend API key."""
    resend.api_key = settings.RESEND_API_KEY


def send_verification_email(to: str, token: str, base_url: str) -> None:
    """Send an email verification link to the user.

    Args:
        to: Recipient email address.
        token: Email verification token.
        base_url: The client application base URL.
    """
    _configure_resend()
    verification_url = f"{base_url}/verify-email?token={token}"

    try:
        resend.Emails.send(
            {
                "from": "Kodwai <noreply@kodwai.com>",
                "to": [to],
                "subject": "Verify your email - Kodwai",
                "html": f"""
                <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2>Welcome to Kodwai!</h2>
                    <p>Please verify your email address by clicking the link below:</p>
                    <p>
                        <a href="{verification_url}"
                           style="display: inline-block; padding: 12px 24px; background-color: #6366f1;
                                  color: #ffffff; text-decoration: none; border-radius: 6px;">
                            Verify Email
                        </a>
                    </p>
                    <p style="color: #6b7280; font-size: 14px;">
                        If you didn't create a Kodwai account, you can safely ignore this email.
                    </p>
                </div>
                """,
            }
        )
        logger.info("Verification email sent to %s", to)
    except Exception:
        logger.exception("Failed to send verification email to %s", to)


def send_invitation_email(
    to: str,
    org_name: str,
    inviter_name: str,
    invitation_id: str,
    base_url: str,
) -> None:
    """Send a team invitation email.

    Args:
        to: Recipient email address.
        org_name: Name of the inviting organization.
        inviter_name: Name of the person who sent the invite.
        invitation_id: The invitation ID for the accept link.
        base_url: The client application base URL.
    """
    _configure_resend()
    accept_url = f"{base_url}/invitations/{invitation_id}/accept"

    try:
        resend.Emails.send(
            {
                "from": "Kodwai <noreply@kodwai.com>",
                "to": [to],
                "subject": f"You've been invited to {org_name} on Kodwai",
                "html": f"""
                <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2>You're invited!</h2>
                    <p>{inviter_name} has invited you to join <strong>{org_name}</strong> on Kodwai.</p>
                    <p>
                        <a href="{accept_url}"
                           style="display: inline-block; padding: 12px 24px; background-color: #6366f1;
                                  color: #ffffff; text-decoration: none; border-radius: 6px;">
                            Accept Invitation
                        </a>
                    </p>
                    <p style="color: #6b7280; font-size: 14px;">
                        This invitation will expire in 7 days.
                    </p>
                </div>
                """,
            }
        )
        logger.info("Invitation email sent to %s for org %s", to, org_name)
    except Exception:
        logger.exception("Failed to send invitation email to %s", to)
