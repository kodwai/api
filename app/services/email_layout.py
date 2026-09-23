"""Shared layout for every kodwai email: blocks in, matching plain-text and HTML parts out.

The HTML is built for email clients, not browsers: table layout, inline styles, a 560px card,
a hidden preheader (the inbox preview line), bulletproof buttons, and no images or web fonts, so
it renders the same in Gmail, Apple Mail and Outlook. Colors follow the site: warm paper
background, ink text, rust accent, and a dark terminal block for commands.

Every interpolated value is escaped here; callers pass plain strings. This module imports only
settings-free helpers so email_service, email_templates and feedback_emails can all use it.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape

PAPER = "#f4f0e8"
CARD = "#ffffff"
CARD_BORDER = "#e6e0d4"
INK = "#1c1a17"
BODY = "#2f2b26"
MUTED = "#8a8377"
RUST = "#b4441d"
TERMINAL = "#1c1a17"
TERMINAL_TEXT = "#f3eee4"
QUOTE_BORDER = "#e0d8ca"

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
SERIF = "Georgia, 'Times New Roman', serif"
MONO = "SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class P:
    """A paragraph of plain text. Single newlines become line breaks."""
    text: str


@dataclass(frozen=True)
class Cmd:
    """A terminal command, shown as a dark code block."""
    command: str


@dataclass(frozen=True)
class Link:
    """The call to action: 'Label: url' in text, a button in HTML."""
    label: str
    url: str


@dataclass(frozen=True)
class Numbered:
    """A numbered list of short paragraphs."""
    items: tuple[str, ...]


@dataclass(frozen=True)
class Quote:
    """Quoted text, e.g. the user's original feedback."""
    text: str


@dataclass(frozen=True)
class Small:
    """A muted note, e.g. a link that expires."""
    text: str


Block = P | Cmd | Link | Numbered | Quote | Small


def _lines_html(text: str) -> str:
    return "<br>".join(escape(line) for line in text.splitlines())


def text_block(block: Block) -> str:
    if isinstance(block, (P, Small)):
        return block.text
    if isinstance(block, Cmd):
        return f"    {block.command}"
    if isinstance(block, Link):
        return f"{block.label}: {block.url}"
    if isinstance(block, Quote):
        return "\n".join(f"> {line}" if line else ">" for line in block.text.splitlines())
    return "\n".join(f"{i}. {item}" for i, item in enumerate(block.items, start=1))


def html_block(block: Block) -> str:
    if isinstance(block, P):
        return f'<p style="margin: 0 0 16px 0;">{_lines_html(block.text)}</p>'
    if isinstance(block, Small):
        return f'<p style="margin: 0 0 16px 0; font-size: 13px; line-height: 1.55; color: {MUTED};">{_lines_html(block.text)}</p>'
    if isinstance(block, Cmd):
        return (
            f'<div style="margin: 4px 0 20px 0; padding: 14px 16px; background-color: {TERMINAL}; border-radius: 8px; '
            f'font-family: {MONO}; font-size: 13.5px; line-height: 1.5; color: {TERMINAL_TEXT}; '
            f'white-space: pre-wrap; word-break: normal; overflow-wrap: anywhere;">'
            f'<span style="color: {MUTED};">$ </span>{escape(block.command)}</div>'
        )
    if isinstance(block, Link):
        href = escape(block.url, quote=True)
        return (
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin: 6px 0 22px 0;">'
            f'<tr><td style="border-radius: 6px; background-color: {RUST};">'
            f'<a href="{href}" style="display: inline-block; padding: 12px 22px; font-family: {SANS}; font-size: 15px; '
            f'font-weight: 600; line-height: 1.2; color: #ffffff; text-decoration: none; border-radius: 6px;">'
            f"{escape(block.label)}</a></td></tr></table>"
        )
    if isinstance(block, Quote):
        return (
            f'<blockquote style="margin: 0 0 16px 0; padding: 2px 0 2px 14px; border-left: 3px solid {QUOTE_BORDER}; '
            f'color: #6b645a;">'
            + "".join(
                f'<p style="margin: 0 0 10px 0;">{_lines_html(paragraph)}</p>'
                for paragraph in block.text.split("\n\n") if paragraph.strip()
            )
            + "</blockquote>"
        )
    items = "".join(
        f'<li style="margin: 0 0 10px 0; padding-left: 4px;">{escape(item)}</li>' for item in block.items
    )
    return f'<ol style="margin: 0 0 18px 0; padding-left: 22px;">{items}</ol>'


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FooterLine:
    """One footer line. With href, the HTML shows ``link_label`` as a link and the text part
    shows ``text`` (usually 'Unsubscribe: <url>')."""
    text: str
    href: str | None = None
    link_label: str | None = None


def _footer_html(lines: list[FooterLine]) -> str:
    parts = []
    for line in lines:
        if line.href:
            parts.append(
                f'<a href="{escape(line.href, quote=True)}" style="color: {MUTED}; text-decoration: underline;">'
                f"{escape(line.link_label or line.text)}</a>"
            )
        else:
            parts.append(escape(line.text))
    return "<br>".join(parts)


def _signature_html(name: str, title: str | None) -> str:
    role = f'<br><span style="font-size: 13px; color: {MUTED};">{escape(title)}</span>' if title else ""
    return f'<p style="margin: 24px 0 0 0;">{escape(name)}{role}</p>'


def render(
    *,
    subject: str,
    preheader: str,
    blocks: list[Block],
    footer: list[FooterLine],
    greeting: str | None = None,
    signature: str | None = "Hakan",
    signature_title: str | None = "Co-founder, kodwai",
    after: list[Block] | None = None,
) -> tuple[str, str]:
    """Render (text, html) for one email. The text part is the source of truth: same words, same
    order. ``signature`` None leaves the sign-off out (e.g. a message that already ends with one);
    ``after`` blocks follow the signature (e.g. the quoted original a reply answers)."""
    text_parts: list[str] = []
    if greeting:
        text_parts.append(greeting)
    text_parts += [text_block(b) for b in blocks]
    if signature:
        text_parts.append(signature)
    text_parts += [text_block(b) for b in after or []]
    text = "\n\n".join(text_parts)
    if footer:
        text += "\n\n\n" + "\n".join(line.text for line in footer)
    text += "\n"

    body = ""
    if greeting:
        body += html_block(P(greeting))
    body += "".join(html_block(b) for b in blocks)
    if signature:
        body += _signature_html(signature, signature_title)
    if after:
        body += '<div style="height: 12px;"></div>' + "".join(html_block(b) for b in after)

    # Zero-width padding keeps clients from pulling body text into the inbox preview.
    pad = "&#847;&zwnj;&nbsp;" * 40
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{escape(subject)}</title>
<style>
  @media (max-width: 620px) {{
    .k-outer {{ padding: 20px 12px !important; }}
    .k-card {{ padding: 28px 22px !important; }}
  }}
</style>
</head>
<body style="margin: 0; padding: 0; background-color: {PAPER}; -webkit-text-size-adjust: 100%;">
<div style="display: none; max-height: 0; overflow: hidden; opacity: 0; mso-hide: all;">{escape(preheader)}{pad}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {PAPER};">
<tr><td class="k-outer" align="center" style="padding: 36px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width: 560px;">
<tr><td style="padding: 0 6px 18px 6px; font-family: {SERIF}; font-size: 24px; line-height: 1; color: {INK}; letter-spacing: -0.3px;">kodwai</td></tr>
<tr><td class="k-card" style="background-color: {CARD}; border: 1px solid {CARD_BORDER}; border-radius: 10px; padding: 36px 40px; font-family: {SANS}; font-size: 16px; line-height: 1.6; color: {BODY};">
{body}
</td></tr>
<tr><td style="padding: 20px 8px 0 8px; font-family: {SANS}; font-size: 12px; line-height: 1.6; color: {MUTED};">
{_footer_html(footer)}
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    return text, html
