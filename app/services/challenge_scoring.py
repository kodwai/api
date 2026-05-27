"""Backward-compatible shim. Real implementation lives in app.services.scoring.

Kept so `from app.services.challenge_scoring import score_submission` (used by
app/routers/submissions.py) and `from app.services.challenge_scoring import
_recompute_ranks` (used by app/routers/admin/leaderboard.py) continue to work
after the v2 refactor.
"""
from __future__ import annotations

from app.services.scoring import score_submission
from app.services.scoring.engine import _recompute_ranks

__all__ = ["score_submission", "_recompute_ranks"]
