"""Lifecycle and account email content, rendered through the shared layout (email_layout).

Every email is a list of blocks (paragraph, command, button link, numbered list, note), so the
plain-text and HTML parts always say the same thing, and every interpolated value is escaped.

Copy rules (tests enforce the mechanical ones): written by Hakan in the first person, like a note
from a person rather than a product; short, varied sentences; one call to action; no em or en
dashes; UTM params (utm_source=email, utm_medium=lifecycle, utm_campaign=<template>) on every
product link; a footer with the reason for receiving, the postal address when
COMPANY_POSTAL_ADDRESS is set, and an unsubscribe link on lifecycle mail. The score is three axes:
Direction, Outcome, Lift (wording from the live site). CLI commands are the real ones from
@kodwai/cli; never invent flags. No upsell: onboarding mail stays non-commercial.

Renderers take keyword arguments only and never touch the database; app.services.lifecycle builds
their context from real DB state.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.email_layout import Block, Cmd, FooterLine, Link, Numbered, P, Small, render
from app.services.email_service import unsubscribe_url, with_utm

__all__ = ["Block", "Cmd", "Link", "Numbered", "P", "Small", "RenderedEmail", "RENDERERS"]

# The three score axes, in the live site's wording (landing Score section).
SCORE_AXES: dict[str, tuple[str, str]] = {
    "direction": ("Direction", "how you steer, verify, and decompose"),
    "outcome": ("Outcome", "what shipped, replayed and stress-tested to prove it holds"),
    "lift": ("Lift", "how far you beat a solo AI, not just that you passed"),
}

CHALLENGE_COMMAND = "npx @kodwai/cli challenge {slug}"
SUBMIT_COMMAND = "npx @kodwai/cli submit"

REASON_SIGNED_UP = "You're getting this because you signed up for kodwai with this address."
REASON_NEWS = "You're getting this because you opted in to product news from kodwai."
REASON_VERIFY = (
    "You're getting this because this address was used to sign up for kodwai. "
    "If that wasn't you, you can ignore this email."
)


@dataclass(frozen=True)
class RenderedEmail:
    template: str
    subject: str
    text: str
    html: str


def _footer_lines(reason: str, unsubscribe: str | None) -> list[FooterLine]:
    lines = [FooterLine(reason)]
    address = settings.COMPANY_POSTAL_ADDRESS.strip()
    if address:
        lines.append(FooterLine(address))
    if unsubscribe:
        lines.append(FooterLine(f"Unsubscribe: {unsubscribe}", href=unsubscribe, link_label="Unsubscribe"))
    return lines


def _compose(
    template: str,
    subject: str,
    name: str | None,
    blocks: list[Block],
    *,
    reason: str,
    unsubscribe: str | None,
    preheader: str,
) -> RenderedEmail:
    text, html = render(
        subject=subject,
        preheader=preheader,
        greeting=f"Hi {name}," if name else "Hi there,",
        blocks=blocks,
        footer=_footer_lines(reason, unsubscribe),
    )
    return RenderedEmail(template=template, subject=subject, text=text, html=html)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def first_name(full_name: str | None) -> str:
    """'Ada Lovelace' -> 'Ada'; empty or missing -> ''."""
    parts = (full_name or "").split()
    return parts[0][:60] if parts else ""


def format_score(score: float | int | None) -> str:
    """Round half up to a whole number, the way the app shows scores (toFixed(0))."""
    if score is None:
        return "0"
    return str(int(math.floor(float(score) + 0.5)))


def app_url(path: str) -> str:
    return f"{settings.CLIENT_URL.rstrip('/')}{path}"


def lifecycle_unsubscribe_url(user_id: str) -> str:
    """unsubscribe_url(), or a visible placeholder when UNSUBSCRIBE_SECRET is unset (previews and
    dry runs before setup; real lifecycle sends refuse without the secret)."""
    if not settings.UNSUBSCRIBE_SECRET:
        return f"{settings.PUBLIC_API_URL.rstrip('/')}/api/email/unsubscribe?u={user_id}&t=UNSUBSCRIBE_SECRET_UNSET"
    return unsubscribe_url(user_id)


def _utm(url: str, template: str) -> str:
    return with_utm(url, template)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# ---------------------------------------------------------------------------
# Section 6 templates
# ---------------------------------------------------------------------------

def verify_reminder(*, user_id: str, name: str, verify_url: str, **_: Any) -> RenderedEmail:
    """Transactional: unverified email signup, 24 to 72 h after signup, once."""
    template = "verify_reminder"
    blocks: list[Block] = [
        P("You signed up for kodwai a little while ago, but your email isn't confirmed yet. "
          "Until it is, signing in stays locked."),
        Link("Confirm my email", _utm(verify_url, template)),
        P("Once that's done, your first challenge is one command away."),
    ]
    return _compose(template, "One click and you're in", name, blocks,
                    reason=REASON_VERIFY, unsubscribe=None,
                    preheader="Confirm your email so you can sign in and start a challenge.")


def welcome(*, user_id: str, name: str, starter_slug: str, starter_title: str | None = None,
            starter_minutes: int | None = None, **_: Any) -> RenderedEmail:
    """Event-driven on verify or new GitHub account; daily backstop within 72 h."""
    template = "welcome"
    challenge = f"the starter challenge, {starter_title}" if starter_title else "the starter challenge"
    timer = f" It has a {starter_minutes}-minute timer, and you" if starter_minutes else " You"
    blocks: list[Block] = [
        P("I'm Hakan, co-founder of kodwai. Thanks for signing up. This early on, every new person "
          "honestly makes my day."),
        P(f"The best way to get a feel for kodwai is {challenge}.{timer} solve it on your own machine "
          "with whatever agent you already use. Open a terminal wherever you want the project to live "
          "and run:"),
        Cmd(CHALLENGE_COMMAND.format(slug=starter_slug)),
        P("The CLI signs you in, asks which agent you're using (Claude Code, Cursor or Codex) and drops "
          f"the problem, starter files and tests into a new folder. When you're done, run {SUBMIT_COMMAND} "
          "from that folder."),
        P("You'll get a score out of 100 across three axes: Direction, Outcome and Lift. The number is "
          "fine, but the breakdown is the part people actually learn from."),
        P("If anything breaks or feels confusing, just hit reply. It comes straight to me."),
    ]
    return _compose(template, "Your first kodwai challenge is one command away", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id),
                    preheader="One command, your own agent, and a score that shows how you work.")


def d1_start(*, user_id: str, name: str, starter_slug: str, free_remaining: int = 0, free_limit: int = 0,
             **_: Any) -> RenderedEmail:
    """24 to 72 h after signup, no CLI login yet."""
    template = "d1_start"
    if free_remaining > 0 and free_remaining == free_limit:
        key_note = (f"Your first {free_remaining} submissions are scored on us. After that, you add your own "
                    "Anthropic API key in Settings. It's encrypted and only ever scores your own work.")
    elif free_remaining > 0:
        key_note = (f"You have {_plural(free_remaining, 'free submission')} left, scored on us. After that, you "
                    "add your own Anthropic API key in Settings. It's encrypted and only ever scores your own work.")
    else:
        key_note = ("Scoring runs on your own Anthropic API key, so add it in Settings before you start. "
                    "It's encrypted and only ever scores your own work.")
    blocks: list[Block] = [
        P("Looks like you haven't started a challenge yet. No pressure at all. When you're ready, this is "
          "the one command that does it:"),
        Cmd(CHALLENGE_COMMAND.format(slug=starter_slug)),
        P("A few things that tend to trip people up on the first run:"),
        Numbered((
            "Install your agent first (Claude Code, Cursor or Codex). The CLI asks which one you use, and "
            "you'll open the challenge folder with it. You'll also need Node.js 20+ and git.",
            key_note,
            f"The CLI makes a kodwai-{starter_slug} folder right where you run it, with PROBLEM.md, starter "
            f"files and tests inside. Run {SUBMIT_COMMAND} from that folder when you're done.",
        )),
        P("If it was something else that stopped you, I'd like to know. Just reply."),
    ]
    return _compose(template, "The one command that starts a kodwai challenge", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id),
                    preheader="Plus the few things that trip people up on the first run.")


def d3_first_submit(*, user_id: str, name: str, starter_slug: str, starter_title: str | None = None,
                    **_: Any) -> RenderedEmail:
    """3 to 6 days after signup, CLI login present, no submission started."""
    template = "d3_first_submit"
    label = f"Open {starter_title}" if starter_title else "Open the starter challenge"
    blocks: list[Block] = [
        P("You've already signed in to the kodwai CLI, so you're most of the way there. No challenge has "
          "started on your account yet, though."),
        P("The starter challenge page shows what it asks for and the exact command to kick it off:"),
        Link(label, _utm(app_url(f"/dev/challenges/{starter_slug}"), template)),
        P("And if something got in the way, tell me. One line is plenty, and it helps more than you'd think."),
    ]
    return _compose(template, "Almost there: your first challenge", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id),
                    preheader="You're signed in. The first challenge is the next step.")


def stalled_submission(*, user_id: str, name: str, challenge_slug: str, challenge_title: str,
                       days_open: int, **_: Any) -> RenderedEmail:
    """A submission in_progress for 48 h to 7 days, nothing scored yet."""
    template = "stalled_submission"
    blocks: list[Block] = [
        P(f"You started {challenge_title} {_plural(days_open, 'day')} ago and it's still open. Happens "
          "to everyone."),
        P(f"If you have a solution, even a half-finished one, submit it from inside the kodwai-{challenge_slug} "
          "folder:"),
        Cmd(SUBMIT_COMMAND),
        P("The timer kept running, so there's a late penalty, but you'll still get the full breakdown across "
          "Direction, Outcome and Lift. If you'd rather start clean, stop the challenge on the Submissions page "
          "in the app and start it again. Only one challenge can be open at a time, so either way you're free "
          "for the next one."),
        P("If the submit throws an error, reply with it and I'll take a look."),
    ]
    return _compose(template, f"{challenge_title} is still open", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id),
                    preheader="Submit what you have, or restart with a fresh timer.")


def first_score(*, user_id: str, name: str, score: float, challenge_title: str, result_url: str,
                is_share_card: bool = False, top_axis: str | None = None, **_: Any) -> RenderedEmail:
    """Milestone: the user's first scored submission."""
    template = "first_score"
    shown = format_score(score)
    blocks: list[Block] = [P(f"Your first kodwai submission just got scored: {shown}/100 on {challenge_title}.")]
    if top_axis in SCORE_AXES:
        label, description = SCORE_AXES[top_axis]
        blocks.append(P(f"Your strongest axis was {label}, which is {description}."))
    if is_share_card:
        blocks.append(P("The full breakdown is on your score card, and it's ready to share if you feel like it:"))
        cta = "See your score card"
    else:
        blocks.append(P("The full breakdown is on your results page, with the evidence behind every signal. "
                        "You can make a public score card from there too."))
        cta = "See your score"
    blocks += [
        Link(cta, _utm(result_url, template)),
        P("If the number doesn't match how the session felt, tell me. I'd rather hear it than guess."),
    ]
    return _compose(template, f"Your kodwai score is in: {shown}/100", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id),
                    preheader="Here's where your points came from, and where they went.")


def d7_scored(*, user_id: str, name: str, score: float, challenge_title: str, harder_slug: str,
              harder_title: str, harder_difficulty: str, harder_minutes: int | None = None,
              most_missed_axis: str | None = None, **_: Any) -> RenderedEmail:
    """7 to 10 days after signup, at least one scored submission, no second one started."""
    template = "d7_scored"
    blocks: list[Block] = [
        P(f"You scored {format_score(score)}/100 on {challenge_title}. If you haven't looked yet, your results "
          "page shows what moved the number. Every signal points to the actual evidence in your transcript, "
          "commits and test runs."),
    ]
    if most_missed_axis in SCORE_AXES:
        blocks.append(P(f"Most of the points you missed were in {SCORE_AXES[most_missed_axis][0]}, so I'd "
                        "start there."))
    detail = f"{harder_difficulty}, {harder_minutes} minutes" if harder_minutes else harder_difficulty
    blocks += [
        P(f"Feel like something harder? {harder_title} ({detail}) is a good next step:"),
        Link(f"Try {harder_title}", _utm(app_url(f"/dev/challenges/{harder_slug}"), template)),
    ]
    return _compose(template, "What moved your score, and a harder one to try", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id),
                    preheader="Every signal cites its evidence. Worth a quick look.")


def d7_not_scored(*, user_id: str, name: str, **_: Any) -> RenderedEmail:
    """7 to 10 days after signup, nothing scored. The one CTA is a reply."""
    template = "d7_not_scored"
    blocks: list[Block] = [
        P("You signed up for kodwai about a week ago and haven't gotten a score yet. That's completely fine. "
          "I'm just curious what got in the way. Was it setup, time, the challenges themselves, or something "
          "else?"),
        P("A one-line reply is plenty. I read every one, and they really do shape what I build next."),
    ]
    return _compose(template, "Can I ask what got in the way?", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id),
                    preheader="A one-line reply is plenty.")


def reengage(*, user_id: str, name: str, new_count: int, newest_title: str | None = None,
             **_: Any) -> RenderedEmail:
    """30 days inactive after at least one score; at most 2 sends 14 days apart, then sunset."""
    template = "reengage"
    challenges = _plural(new_count, "new challenge")
    lead = f"It's been a little while. Since your last kodwai run, {challenges} went live"
    lead += f", including {newest_title}." if newest_title else "."
    blocks: list[Block] = [
        P(lead),
        P("Curious how you'd do on them?"),
        Link("See the new challenges", _utm(app_url("/dev/challenges"), template)),
    ]
    return _compose(template, f"{challenges} since your last run", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id),
                    preheader="New problems to point your agent at.")


def news(*, user_id: str, name: str, headline: str, body: str, url: str, link_label: str = "Read more",
         **_: Any) -> RenderedEmail:
    """Stub for product news (marketing, consent only). Never auto-scheduled by the runner."""
    template = "news"
    blocks: list[Block] = [P(paragraph) for paragraph in body.split("\n\n") if paragraph.strip()]
    blocks.append(Link(link_label, _utm(url, template)))
    return _compose(template, f"New on kodwai: {headline}", name, blocks,
                    reason=REASON_NEWS, unsubscribe=lifecycle_unsubscribe_url(user_id),
                    preheader=headline)


# ---------------------------------------------------------------------------
# Account mail (transactional)
# ---------------------------------------------------------------------------

def verify_email(*, name: str | None, verify_url: str, **_: Any) -> RenderedEmail:
    """Email verification link, sent at signup and by POST /auth/resend-verification."""
    blocks: list[Block] = [
        P("Welcome to kodwai. One quick thing before you start: confirm this is your email."),
        Link("Confirm my email", verify_url),
        Small("If the button doesn't work, copy this link into your browser:\n" + verify_url),
    ]
    return _compose("verify_email", "Verify your email for kodwai", first_name(name), blocks,
                    reason="If you didn't create a kodwai account, you can safely ignore this email.",
                    unsubscribe=None, preheader="One click and you're in.")


def password_reset(*, reset_url: str, **_: Any) -> RenderedEmail:
    """Password reset link (expires in 1 hour)."""
    blocks: list[Block] = [
        P("Someone (hopefully you) asked to reset the password on your kodwai account. This link works for "
          "the next hour:"),
        Link("Choose a new password", reset_url),
        Small("If you didn't ask for this, you can ignore this email. Your password stays the same."),
    ]
    return _compose("password_reset", "Reset your kodwai password", None, blocks,
                    reason="You're getting this because a password reset was requested for this address.",
                    unsubscribe=None, preheader="The link works for the next hour.")


def org_invitation(*, org_name: str, inviter_name: str, accept_url: str, **_: Any) -> RenderedEmail:
    """Team invitation to join an organization (expires in 7 days)."""
    blocks: list[Block] = [
        P(f"{inviter_name} invited you to join {org_name} on kodwai, where teams run coding interviews that "
          "let candidates work with their own AI agent."),
        Link("Accept the invitation", accept_url),
        Small("The invitation expires in 7 days."),
    ]
    text, html = render(
        subject=f"{inviter_name} invited you to {org_name} on kodwai",
        preheader=f"Join {org_name} on kodwai.",
        greeting="Hi there,",
        blocks=blocks,
        footer=[FooterLine("You're getting this because someone invited this address to a team on kodwai.")],
        signature=None,
    )
    return RenderedEmail("org_invitation", f"{inviter_name} invited you to {org_name} on kodwai", text, html)


def session_invitation(*, candidate_name: str, project_title: str, session_id: str, session_token: str,
                       time_limit: int, **_: Any) -> RenderedEmail:
    """A candidate's invitation to a timed coding assessment."""
    blocks: list[Block] = [
        P(f"You've been invited to a coding assessment for {project_title}. You'll work on your own machine, "
          "with the AI coding agent you normally use."),
        P(f"You have {time_limit} minutes, and the timer starts when you run this command in your terminal:"),
        Cmd(f"npx @kodwai/cli start {session_id} --token {session_token}"),
        Small("You'll need Node.js 20 or newer and git installed. The command is personal to you, so please "
              "don't share it."),
        P("Good luck. Take a breath before you hit enter."),
    ]
    subject = f"Your coding assessment for {project_title}"
    text, html = render(
        subject=subject,
        preheader=f"{time_limit} minutes, your own machine, your own agent.",
        greeting=f"Hi {first_name(candidate_name)}," if first_name(candidate_name) else "Hi there,",
        blocks=blocks,
        footer=[FooterLine("You're getting this because a hiring team invited this address to an assessment on kodwai.")],
        signature=None,
    )
    return RenderedEmail("session_invitation", subject, text, html)


RENDERERS: dict[str, Callable[..., RenderedEmail]] = {
    "verify_reminder": verify_reminder,
    "welcome": welcome,
    "d1_start": d1_start,
    "d3_first_submit": d3_first_submit,
    "stalled_submission": stalled_submission,
    "first_score": first_score,
    "d7_scored": d7_scored,
    "d7_not_scored": d7_not_scored,
    "reengage": reengage,
    "news": news,
}
