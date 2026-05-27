"""Tests for migration 020: curated catalog of exactly 15 quality challenges.

Verifies:
- Exactly 15 challenges exist after all migrations.
- All 15 are is_public=1.
- All 15 are is_featured=1.
- Every challenge has a non-empty scoring_config.rubric with >= 5 dimensions
  (verified via resolve_config).
- The 6 new library slugs are present with difficulty='hard'.
- Known junk slugs are absent: 'url-shortener', 'debug-auth-flow',
  'theme-switcher', 'sql-query-engine'.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.core.database import fetch_all, fetch_one
from app.services.challenge_library import CHALLENGE_LIBRARY
from app.services.scoring.config import resolve_config

# ---------------------------------------------------------------------------
# Expected catalogue
# ---------------------------------------------------------------------------

# 9 quality slugs from migration 019
QUALITY_SLUGS_019: list[str] = [
    "searchable-product-listing-ui",
    "offline-first-notes-app",
    "bookshelf-rest-api",
    "idempotent-etl-pipeline-with-schema-drift",
    "multi-tenant-feature-flag-service",
    "secrets-vault-with-envelope-encryption",
    "production-rag-service-with-eval-harness-cost-guardrails",
    "multi-currency-wallet-ledger-with-idempotent-transfers",
    "zero-downtime-schema-migration-progressive-rollout",
]

# 6 new slugs from migration 020 (derived from CHALLENGE_LIBRARY)
LIBRARY_SLUGS: list[str] = [ch["slug"] for ch in CHALLENGE_LIBRARY]

# Full 15-slug keep-list
ALL_15_SLUGS: list[str] = QUALITY_SLUGS_019 + LIBRARY_SLUGS

assert len(ALL_15_SLUGS) == 15, f"Keep-list should have 15 slugs, got {len(ALL_15_SLUGS)}"

# Junk slugs that MUST NOT remain
JUNK_SLUGS: list[str] = [
    "url-shortener",
    "debug-auth-flow",
    "theme-switcher",
    "sql-query-engine",
]

# Minimum rubric dimensions per library challenge
MIN_RUBRIC_DIMS: dict[str, int] = {ch["slug"]: len(ch["rubric"]) for ch in CHALLENGE_LIBRARY}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_exactly_15_challenges_total():
    """After all migrations, the total challenge count must be exactly 15."""
    rows = fetch_all("SELECT slug FROM challenges")
    slugs = [r["slug"] for r in rows]
    assert len(slugs) == 15, (
        f"Expected exactly 15 challenges, got {len(slugs)}:\n  {sorted(slugs)}"
    )


def test_all_15_are_public():
    """Every challenge in the catalog must be is_public=1."""
    rows = fetch_all("SELECT slug, is_public FROM challenges")
    non_public = [r["slug"] for r in rows if not r["is_public"]]
    assert non_public == [], (
        f"These challenges are not public: {non_public}"
    )


def test_all_15_are_featured():
    """Every challenge in the catalog must be is_featured=1."""
    rows = fetch_all("SELECT slug, is_featured FROM challenges")
    non_featured = [r["slug"] for r in rows if not r["is_featured"]]
    assert non_featured == [], (
        f"These challenges are not featured: {non_featured}"
    )


def test_all_15_slugs_present():
    """All 15 expected slugs must be in the DB."""
    rows = fetch_all("SELECT slug FROM challenges")
    db_slugs = {r["slug"] for r in rows}
    missing = set(ALL_15_SLUGS) - db_slugs
    assert not missing, f"Missing slugs: {sorted(missing)}"


def test_6_new_library_slugs_are_hard():
    """The 6 new library challenges must have difficulty='hard'."""
    for slug in LIBRARY_SLUGS:
        row = fetch_one("SELECT difficulty FROM challenges WHERE slug = ?", (slug,))
        assert row is not None, f"Challenge slug={slug!r} not found"
        assert row["difficulty"] == "hard", (
            f"slug={slug}: expected difficulty='hard', got {row['difficulty']!r}"
        )


def test_every_challenge_has_rubric_via_resolve_config():
    """Every challenge must have a non-empty scoring_config.rubric (>= 5 dims) via resolve_config."""
    rows = fetch_all("SELECT slug, scoring_config FROM challenges")
    for row in rows:
        slug = row["slug"]
        cfg = resolve_config(row["scoring_config"])
        assert isinstance(cfg.rubric, list), (
            f"slug={slug}: resolve_config().rubric should be a list, got {type(cfg.rubric)}"
        )
        assert len(cfg.rubric) >= 5, (
            f"slug={slug}: expected >= 5 rubric dims, got {len(cfg.rubric)}"
        )


def test_library_challenges_have_correct_rubric_dim_counts():
    """Each new library challenge must have the exact rubric dim count from CHALLENGE_LIBRARY."""
    for slug, expected_dims in MIN_RUBRIC_DIMS.items():
        row = fetch_one("SELECT scoring_config FROM challenges WHERE slug = ?", (slug,))
        assert row is not None, f"slug={slug!r} not found"
        raw = json.loads(row["scoring_config"])
        rubric = raw.get("rubric", [])
        assert len(rubric) == expected_dims, (
            f"slug={slug}: expected {expected_dims} rubric dims, got {len(rubric)}"
        )


def test_rubric_dimensions_have_required_fields():
    """Every rubric dimension of every challenge must have 'name', 'weight', 'description'."""
    rows = fetch_all("SELECT slug, scoring_config FROM challenges")
    for row in rows:
        slug = row["slug"]
        cfg = resolve_config(row["scoring_config"])
        for dim in cfg.rubric:
            assert "name" in dim, f"slug={slug}: rubric dim missing 'name'"
            assert "weight" in dim, f"slug={slug}: rubric dim missing 'weight'"
            assert "description" in dim, f"slug={slug}: rubric dim missing 'description'"
            assert isinstance(dim["weight"], (int, float)), (
                f"slug={slug}: weight must be numeric, got {type(dim['weight'])}"
            )
            assert dim["description"], f"slug={slug}: rubric dim description must not be empty"


def test_all_15_challenges_have_spec_heavy_profile():
    """All 15 quality challenges must use the spec_heavy scoring profile."""
    rows = fetch_all("SELECT slug, scoring_config FROM challenges")
    for row in rows:
        slug = row["slug"]
        cfg = resolve_config(row["scoring_config"])
        assert cfg.profile == "spec_heavy", (
            f"slug={slug}: expected profile='spec_heavy', got {cfg.profile!r}"
        )


def test_junk_slugs_are_absent():
    """Known legacy junk slugs must NOT appear in the DB after migration 020."""
    for slug in JUNK_SLUGS:
        row = fetch_one("SELECT id FROM challenges WHERE slug = ?", (slug,))
        assert row is None, (
            f"Junk slug {slug!r} was not deleted — still in the DB"
        )


def test_library_challenge_descriptions_are_non_empty():
    """Each library challenge must have a non-empty description and problem_statement_md."""
    for slug in LIBRARY_SLUGS:
        row = fetch_one(
            "SELECT description, problem_statement_md FROM challenges WHERE slug = ?",
            (slug,),
        )
        assert row is not None, f"slug={slug!r} not found"
        assert row["description"], f"slug={slug}: description is empty"
        assert row["problem_statement_md"], f"slug={slug}: problem_statement_md is empty"
        # Problem statement should be substantial (>500 chars — these are large markdowns)
        assert len(row["problem_statement_md"]) > 500, (
            f"slug={slug}: problem_statement_md seems too short ({len(row['problem_statement_md'])} chars)"
        )
