"""Lifecycle and account email content: plain text first, with a minimal escaped HTML part.

Every email is built from a list of blocks (paragraph, command, link, numbered list), so the text
and HTML parts always say the same thing, and every interpolated value is escaped in the HTML.

Copy rules (tests enforce the mechanical ones): founder voice, first person from Hakan; one call to
action; no em or en dashes; UTM params (utm_source=email, utm_medium=lifecycle,
utm_campaign=<template>) on every product link; a footer with the reason for receiving, the postal
address when COMPANY_POSTAL_ADDRESS is set, and an unsubscribe link on lifecycle mail. The score is
three axes: Direction, Outcome, Lift (wording from the live site). CLI commands are the real ones
from @kodwai/cli; never invent flags. No upsell: onboarding mail stays non-commercial.

Renderers take keyword arguments only and never touch the database; app.services.lifecycle builds
their context from real DB state.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from typing import Any

from app.core.config import settings
from app.services.email_service import unsubscribe_url, with_utm

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


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class P:
    """A paragraph of plain text."""
    text: str


@dataclass(frozen=True)
class Cmd:
    """A terminal command, shown as a code block."""
    command: str


@dataclass(frozen=True)
class Link:
    """A call-to-action link: 'Label: url' in text, an anchor in HTML."""
    label: str
    url: str


@dataclass(frozen=True)
class Numbered:
    """A numbered list of short paragraphs."""
    items: tuple[str, ...]


Block = P | Cmd | Link | Numbered

_WRAP = (
    '<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif; '
    'font-size: 15px; line-height: 1.55; color: #1f2937; max-width: 560px;">{body}</div>'
)
_PRE = (
    '<pre style="background-color: #f3f4f6; padding: 12px 14px; border-radius: 6px; '
    'font-family: SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; white-space: pre-wrap;">{cmd}</pre>'
)
_FOOTER = '<p style="color: #6b7280; font-size: 12px; line-height: 1.5; margin-top: 28px;">{lines}</p>'


def _text_block(block: Block) -> str:
    if isinstance(block, P):
        return block.text
    if isinstance(block, Cmd):
        return f"    {block.command}"
    if isinstance(block, Link):
        return f"{block.label}: {block.url}"
    return "\n".join(f"{i}. {item}" for i, item in enumerate(block.items, start=1))


def _html_block(block: Block) -> str:
    if isinstance(block, P):
        return f"<p>{escape(block.text)}</p>"
    if isinstance(block, Cmd):
        return _PRE.format(cmd=escape(block.command))
    if isinstance(block, Link):
        return f'<p><a href="{escape(block.url, quote=True)}" style="color: #b4441d;">{escape(block.label)}</a></p>'
    items = "".join(f'<li style="margin-bottom: 8px;">{escape(item)}</li>' for item in block.items)
    return f'<ol style="padding-left: 20px;">{items}</ol>'


def _footer_lines(reason: str, unsubscribe: str | None) -> list[tuple[str, str | None]]:
    """(text, href) pairs for the footer; href is set only on the unsubscribe line."""
    lines: list[tuple[str, str | None]] = [(reason, None)]
    address = settings.COMPANY_POSTAL_ADDRESS.strip()
    if address:
        lines.append((address, None))
    if unsubscribe:
        lines.append((f"Unsubscribe: {unsubscribe}", unsubscribe))
    return lines


def _compose(
    template: str,
    subject: str,
    name: str | None,
    blocks: list[Block],
    *,
    reason: str,
    unsubscribe: str | None,
) -> RenderedEmail:
    greeting = f"Hi {name}," if name else "Hi,"
    body_blocks: list[Block] = [P(greeting), *blocks, P("Hakan")]
    footer = _footer_lines(reason, unsubscribe)

    text = "\n\n".join(_text_block(b) for b in body_blocks)
    text += "\n\n\n" + "\n".join(line for line, _ in footer) + "\n"

    footer_html = "<br>".join(
        f'Unsubscribe: <a href="{escape(href, quote=True)}" style="color: #6b7280;">{escape(href)}</a>' if href
        else escape(line)
        for line, href in footer
    )
    html = _WRAP.format(body="".join(_html_block(b) for b in body_blocks) + _FOOTER.format(lines=footer_html))
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
        P("You signed up for kodwai but haven't confirmed your email yet. Signing in stays blocked until you do."),
        Link("Confirm your email", _utm(verify_url, template)),
        P("After that, your first challenge is one command away."),
    ]
    return _compose(template, "Confirm your email to start your first challenge", name, blocks,
                    reason=REASON_VERIFY, unsubscribe=None)


def welcome(*, user_id: str, name: str, starter_slug: str, starter_title: str | None = None,
            starter_minutes: int | None = None, **_: Any) -> RenderedEmail:
    """Event-driven on verify or new GitHub account; daily backstop within 72 h."""
    template = "welcome"
    challenge = f"the starter challenge, {starter_title}" if starter_title else "the starter challenge"
    timer = f"{starter_minutes} minutes, " if starter_minutes else ""
    blocks: list[Block] = [
        P("I'm Hakan, co-founder of kodwai. Thanks for signing up."),
        P(f"The quickest way to see what kodwai measures is {challenge} ({timer}solved on your own machine "
          "with your own agent). Run this where you want the workspace:"),
        Cmd(CHALLENGE_COMMAND.format(slug=starter_slug)),
        P("The CLI signs you in, asks which agent you use (Claude Code, Cursor or Codex) and sets up the "
          f"problem, starter files and tests. Submit from that folder with {SUBMIT_COMMAND}."),
        P("You get a score from 0 to 100 across three axes: Direction, Outcome and Lift."),
        P("If anything gets in the way, reply. I read every reply myself."),
    ]
    return _compose(template, "Your first kodwai challenge is one command away", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id))


def d1_start(*, user_id: str, name: str, starter_slug: str, free_remaining: int = 0, free_limit: int = 0,
             **_: Any) -> RenderedEmail:
    """24 to 72 h after signup, no CLI login yet."""
    template = "d1_start"
    if free_remaining > 0 and free_remaining == free_limit:
        key_note = (f"Your first {free_remaining} submissions are scored free on our key. After that, connect your "
                    "own Anthropic API key in Settings. It's encrypted and only scores your own work.")
    elif free_remaining > 0:
        key_note = (f"You have {_plural(free_remaining, 'free submission')} left, scored on our key. After that, "
                    "connect your own Anthropic API key in Settings. It's encrypted and only scores your own work.")
    else:
        key_note = ("Scoring runs on your own Anthropic API key, so connect it in Settings before you start. "
                    "It's encrypted and only scores your own work.")
    blocks: list[Block] = [
        P("You haven't started a challenge yet. This is the one command that does it:"),
        Cmd(CHALLENGE_COMMAND.format(slug=starter_slug)),
        P("Three things worth knowing first:"),
        Numbered((
            "Have your agent installed (Claude Code, Cursor or Codex): the CLI asks which one, and you open the "
            "challenge folder with it. The CLI needs Node.js 20+ and git.",
            key_note,
            f"The CLI creates a kodwai-{starter_slug} folder where you run it, with PROBLEM.md, starter files and "
            f"tests. Run {SUBMIT_COMMAND} from inside it when you're done.",
        )),
        P("If something else stopped you, reply and tell me what it was."),
    ]
    return _compose(template, "The one command that starts a kodwai challenge", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id))


def d3_first_submit(*, user_id: str, name: str, starter_slug: str, starter_title: str | None = None,
                    **_: Any) -> RenderedEmail:
    """3 to 6 days after signup, CLI login present, no submission started."""
    template = "d3_first_submit"
    label = f"Open {starter_title}" if starter_title else "Open the starter challenge"
    blocks: list[Block] = [
        P("You've signed in to the kodwai CLI, but no challenge has started on your account yet."),
        P("The starter challenge page shows what it asks for and the exact command to start it:"),
        Link(label, _utm(app_url(f"/dev/challenges/{starter_slug}"), template)),
        P("If something blocked you, reply and tell me what happened. Even one line helps."),
    ]
    return _compose(template, "Stuck before your first submission?", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id))


def stalled_submission(*, user_id: str, name: str, challenge_slug: str, challenge_title: str,
                       days_open: int, **_: Any) -> RenderedEmail:
    """A submission in_progress for 48 h to 7 days, nothing scored yet."""
    template = "stalled_submission"
    blocks: list[Block] = [
        P(f"You started {challenge_title} {_plural(days_open, 'day')} ago and haven't submitted it yet."),
        P(f"If you have a solution, even a partial one, submit it from inside the kodwai-{challenge_slug} folder:"),
        Cmd(SUBMIT_COMMAND),
        P("The timer kept running, so a late penalty applies, but you still get the full breakdown across "
          "Direction, Outcome and Lift. For a fresh timer instead, stop the challenge on the Submissions page in "
          "the app and start it again. Only one challenge can be open at a time, so either way frees you up for "
          "the next one."),
        P("If the submit fails, reply with the error message. I read every reply."),
    ]
    return _compose(template, "Your challenge is still open. Here's how to finish it", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id))


def first_score(*, user_id: str, name: str, score: float, challenge_title: str, result_url: str,
                is_share_card: bool = False, top_axis: str | None = None, **_: Any) -> RenderedEmail:
    """Milestone: the user's first scored submission."""
    template = "first_score"
    shown = format_score(score)
    blocks: list[Block] = [P(f"Your first kodwai submission is scored: {shown}/100 on {challenge_title}.")]
    if top_axis in SCORE_AXES:
        label, description = SCORE_AXES[top_axis]
        blocks.append(P(f"Your strongest axis was {label}: {description}."))
    if is_share_card:
        blocks.append(P("Your score card has the full breakdown, and it's ready to share:"))
        cta = "See your score card"
    else:
        blocks.append(P("The full breakdown, with the evidence behind each signal, is on your results page. "
                        "You can share a public score card from there too."))
        cta = "See your score"
    blocks += [
        Link(cta, _utm(result_url, template)),
        P("If the score doesn't match how the session felt, reply and tell me. I read every reply."),
    ]
    return _compose(template, f"Your kodwai score is in: {shown}/100", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id))


def d7_scored(*, user_id: str, name: str, score: float, challenge_title: str, harder_slug: str,
              harder_title: str, harder_difficulty: str, harder_minutes: int | None = None,
              most_missed_axis: str | None = None, **_: Any) -> RenderedEmail:
    """7 to 10 days after signup, at least one scored submission, no second one started."""
    template = "d7_scored"
    blocks: list[Block] = [
        P(f"You scored {format_score(score)}/100 on {challenge_title}. Your results page shows what moved it: "
          "every signal cites its own evidence from your transcript, commits, and test runs."),
    ]
    if most_missed_axis in SCORE_AXES:
        blocks.append(P(f"Most of the points you missed were in {SCORE_AXES[most_missed_axis][0]}, so that's the "
                        "part to read first."))
    detail = f"{harder_difficulty}, {harder_minutes} minutes" if harder_minutes else harder_difficulty
    blocks += [
        P(f"If you want a harder one, try {harder_title} ({detail}):"),
        Link(f"Try {harder_title}", _utm(app_url(f"/dev/challenges/{harder_slug}"), template)),
    ]
    return _compose(template, "What moved your score, and a harder challenge to try", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id))


def d7_not_scored(*, user_id: str, name: str, **_: Any) -> RenderedEmail:
    """7 to 10 days after signup, nothing scored. The one CTA is a reply."""
    template = "d7_not_scored"
    blocks: list[Block] = [
        P("You signed up for kodwai about a week ago and haven't gotten a score yet. I'd like to know what got "
          "in the way: setup, time, the challenges, or something else."),
        P("Reply with one line. I read every reply, and it's how I decide what to work on next."),
    ]
    return _compose(template, "Quick question: what got in the way?", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id))


def reengage(*, user_id: str, name: str, new_count: int, newest_title: str | None = None,
             **_: Any) -> RenderedEmail:
    """30 days inactive after at least one score; at most 2 sends 14 days apart, then sunset."""
    template = "reengage"
    challenges = _plural(new_count, "new challenge")
    lead = f"Since your last kodwai run, {challenges} went live"
    lead += f", including {newest_title}." if newest_title else "."
    blocks: list[Block] = [
        P(lead),
        Link("See the challenges", _utm(app_url("/dev/challenges"), template)),
    ]
    return _compose(template, f"{challenges} since your last run", name, blocks,
                    reason=REASON_SIGNED_UP, unsubscribe=lifecycle_unsubscribe_url(user_id))


def news(*, user_id: str, name: str, headline: str, body: str, url: str, link_label: str = "Read more",
         **_: Any) -> RenderedEmail:
    """Stub for product news (marketing, consent only). Never auto-scheduled by the runner."""
    template = "news"
    blocks: list[Block] = [P(paragraph) for paragraph in body.split("\n\n") if paragraph.strip()]
    blocks.append(Link(link_label, _utm(url, template)))
    return _compose(template, f"New on kodwai: {headline}", name, blocks,
                    reason=REASON_NEWS, unsubscribe=lifecycle_unsubscribe_url(user_id))


# ---------------------------------------------------------------------------
# Account mail (transactional, tracked)
# ---------------------------------------------------------------------------

def verify_email(*, name: str | None, verify_url: str, **_: Any) -> RenderedEmail:
    """Email verification link, sent at signup and by POST /auth/resend-verification."""
    blocks: list[Block] = [
        P("Welcome to kodwai. Please confirm your email address with the link below:"),
        Link("Verify email", verify_url),
    ]
    return _compose("verify_email", "Verify your email for kodwai", first_name(name), blocks,
                    reason="If you didn't create a kodwai account, you can safely ignore this email.",
                    unsubscribe=None)


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
