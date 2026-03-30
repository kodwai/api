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
    verification_url = f"{base_url}/verify?token={token}"

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


def send_session_invitation_email(
    to: str,
    candidate_name: str,
    project_title: str,
    session_id: str,
    session_token: str,
    time_limit: int,
    base_url: str,
) -> None:
    """Send a session invitation email to a candidate.

    Includes CLI commands to start the interview session.

    Args:
        to: Candidate email address.
        candidate_name: Name of the candidate.
        project_title: Title of the project/assessment.
        session_id: The session ID for the CLI start command.
        time_limit: Time limit in minutes.
        base_url: The application base URL.
    """
    _configure_resend()

    try:
        resend.Emails.send(
            {
                "from": "Kodwai <noreply@kodwai.com>",
                "to": [to],
                "subject": f"You're invited to a coding assessment - {project_title}",
                "html": f"""
                <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2>Hi {candidate_name},</h2>
                    <p>You've been invited to complete a coding assessment for <strong>{project_title}</strong>.</p>
                    <div style="background-color: #f3f4f6; padding: 16px; border-radius: 8px; margin: 16px 0;">
                        <p style="margin: 0 0 8px 0;"><strong>Time Limit:</strong> {time_limit} minutes</p>
                    </div>
                    <h3>Getting Started</h3>
                    <p>Run the following command in your terminal to begin:</p>
                    <div style="background-color: #1e1e1e; color: #d4d4d4; padding: 16px; border-radius: 8px;
                                font-family: monospace; margin: 12px 0;">
                        npx @kodwai/cli start {session_id} --token {session_token}
                    </div>
                    <p style="color: #6b7280; font-size: 14px; margin-top: 16px;">
                        <strong>Alternative install methods:</strong>
                    </p>
                    <div style="background-color: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 8px;
                                font-family: monospace; font-size: 13px; margin: 8px 0;">
                        # macOS / Linux<br/>
                        curl -fsSL https://kodwai.com/install.sh | sh<br/><br/>
                        # Windows (PowerShell)<br/>
                        irm https://kodwai.com/install.ps1 | iex
                    </div>
                    <p style="color: #6b7280; font-size: 14px; margin-top: 16px;">
                        The timer will start once you run the command. Good luck!
                    </p>
                </div>
                """,
            }
        )
        logger.info("Session invitation email sent to %s for session %s", to, session_id)
    except Exception:
        logger.exception("Failed to send session invitation email to %s", to)
