"""Backward-compatible shim. Real implementation lives in app.services.scoring.

Kept so `from app.services.challenge_scoring import score_submission` (used by
app/routers/submissions.py) continues to work after the v2 refactor.
"""
from __future__ import annotations

from app.services.scoring import score_submission

__all__ = ["score_submission"]
