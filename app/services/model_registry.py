"""Canonical model registry — the single source of truth for normalizing the
raw model strings the CLI captures from agent traces into a stable
{slug, display, provider} shape used for storage, display, and leaderboard
grouping."""
from __future__ import annotations

import re

# Canonical entries keyed by slug.
_CANONICAL: dict[str, dict] = {
    "claude-opus-4-8": {"display": "Opus 4.8", "provider": "anthropic"},
    "claude-opus-4-7": {"display": "Opus 4.7", "provider": "anthropic"},
    "claude-sonnet-4-6": {"display": "Sonnet 4.6", "provider": "anthropic"},
    "claude-sonnet-4-5": {"display": "Sonnet 4.5", "provider": "anthropic"},
    "claude-haiku-4-5": {"display": "Haiku 4.5", "provider": "anthropic"},
    "gpt-5.5": {"display": "GPT-5.5", "provider": "openai"},
    "gpt-5": {"display": "GPT-5", "provider": "openai"},
}

# Raw/alias spellings (lowercased) -> canonical slug.
_ALIASES: dict[str, str] = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
    "claude-opus-4-8": "claude-opus-4-8",
    "claude-opus-4-7": "claude-opus-4-7",
    "claude-sonnet-4-6": "claude-sonnet-4-6",
    "claude-sonnet-4-5": "claude-sonnet-4-5",
    "claude-4.5-sonnet": "claude-sonnet-4-5",
    "claude-4.5-sonnet-thinking": "claude-sonnet-4-5",
    "claude-haiku-4-5": "claude-haiku-4-5",
    "gpt-5.5": "gpt-5.5",
    "gpt-5": "gpt-5",
}


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", s.strip().lower()).strip("-")


def _infer_provider(raw: str, provider: str | None) -> str:
    if provider:
        return provider
    low = raw.lower()
    if low.startswith("claude"):
        return "anthropic"
    if low.startswith(("gpt", "o1", "o3", "codex")):
        return "openai"
    return "unknown"


def normalize_model(raw: str | None, provider: str | None = None) -> dict | None:
    """Map a raw model string to {slug, display, provider}, or None when there is
    no usable signal ("default"/empty/None)."""
    if not raw:
        return None
    key = raw.strip().lower()
    if not key or key == "default":
        return None
    slug = _ALIASES.get(key)
    if slug and slug in _CANONICAL:
        entry = _CANONICAL[slug]
        return {"slug": slug, "display": entry["display"], "provider": entry["provider"]}
    # Unknown but non-empty: keep it visible (ungrouped) until the registry learns it.
    return {"slug": _slugify(raw), "display": raw.strip(), "provider": _infer_provider(raw, provider)}


def display_for_slug(slug: str | None) -> str | None:
    """Reverse lookup for read paths that store only the slug (leaderboard rows)."""
    if not slug:
        return None
    entry = _CANONICAL.get(slug)
    return entry["display"] if entry else slug
