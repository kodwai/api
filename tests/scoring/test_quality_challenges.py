"""Tests for migration 019: 9 bespoke-rubric challenges from DEFAULT_PROJECTS.

Verifies:
- Exactly 9 challenges are is_public=1 after migration 019.
- Each has a non-empty scoring_config.rubric with >= 5 dimensions.
- resolve_config returns a ScoringConfig with a non-empty .rubric list.
- Titles match the 9 DEFAULT_PROJECTS.
- Profile is spec_heavy for all 9 (build-from-scratch direction).
- One challenge (Searchable Product Listing UI) tested end-to-end via resolve_config.
"""
from __future__ import annotations

import json

import pytest

from app.core.database import fetch_all, fetch_one
from app.services.default_projects import DEFAULT_PROJECTS
from app.services.scoring.config import resolve_config

# ---------------------------------------------------------------------------
# Expected challenge catalogue
# ---------------------------------------------------------------------------

EXPECTED_SLUGS: list[str] = [
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

EXPECTED_TITLES: list[str] = [p["title"] for p in DEFAULT_PROJECTS]

# Minimum rubric dimensions per project (from DEFAULT_PROJECTS)
MIN_RUBRIC_DIMS: dict[str, int] = {
    "searchable-product-listing-ui":                              5,
    "offline-first-notes-app":                                    5,
    "bookshelf-rest-api":                                         5,
    "idempotent-etl-pipeline-with-schema-drift":                  6,
    "multi-tenant-feature-flag-service":                          6,
    "secrets-vault-with-envelope-encryption":                     6,
    "production-rag-service-with-eval-harness-cost-guardrails":   8,
    "multi-currency-wallet-ledger-with-idempotent-transfers":      9,
    "zero-downtime-schema-migration-progressive-rollout":          9,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_exactly_9_public_challenges():
    """After migration 019, at least the original 9 bespoke-rubric challenges are is_public=1.

    NOTE: Migration 020 extends the catalog to 15 public challenges (adding 6 new senior
    challenges from CHALLENGE_LIBRARY). This test now verifies the 9 original slugs are
    still present and public, rather than asserting the total count is exactly 9.
    See tests/scoring/test_curated_catalog.py for the 15-challenge count assertion.
    """
    rows = fetch_all("SELECT slug FROM challenges WHERE is_public = 1")
    public_slugs = {r["slug"] for r in rows}
    # The 9 original quality challenges must still all be present and public.
    missing = set(EXPECTED_SLUGS) - public_slugs
    assert not missing, (
        f"Original quality challenge slugs missing from public catalog:\n"
        f"  {sorted(missing)}"
    )


def test_all_9_challenges_are_featured():
    """All 9 quality challenges must be is_featured=1."""
    rows = fetch_all(
        "SELECT slug FROM challenges WHERE slug IN ({})".format(
            ",".join("?" * len(EXPECTED_SLUGS))
        ),
        tuple(EXPECTED_SLUGS),
    )
    featured = fetch_all(
        "SELECT slug FROM challenges WHERE is_featured = 1 AND slug IN ({})".format(
            ",".join("?" * len(EXPECTED_SLUGS))
        ),
        tuple(EXPECTED_SLUGS),
    )
    assert len(featured) == 9, (
        f"Expected all 9 quality challenges to be featured; got {len(featured)}"
    )


def test_titles_match_default_projects():
    """Each seeded challenge title must match its corresponding DEFAULT_PROJECTS entry."""
    for slug, title in zip(EXPECTED_SLUGS, EXPECTED_TITLES):
        row = fetch_one("SELECT title FROM challenges WHERE slug = ?", (slug,))
        assert row is not None, f"Challenge with slug={slug!r} not found in DB"
        assert row["title"] == title, (
            f"slug={slug}: expected title={title!r}, got {row['title']!r}"
        )


def test_each_challenge_has_spec_heavy_profile():
    """All 9 quality challenges must use the spec_heavy scoring profile."""
    for slug in EXPECTED_SLUGS:
        row = fetch_one("SELECT scoring_config FROM challenges WHERE slug = ?", (slug,))
        assert row is not None, f"slug={slug!r} not found"
        cfg = resolve_config(row["scoring_config"])
        assert cfg.profile == "spec_heavy", (
            f"slug={slug}: expected profile='spec_heavy', got {cfg.profile!r}"
        )


def test_each_challenge_has_non_empty_rubric_with_min_dims():
    """Each challenge must have scoring_config.rubric with the expected number of dimensions."""
    for slug, min_dims in MIN_RUBRIC_DIMS.items():
        row = fetch_one("SELECT scoring_config FROM challenges WHERE slug = ?", (slug,))
        assert row is not None, f"slug={slug!r} not found"

        raw = json.loads(row["scoring_config"])
        rubric = raw.get("rubric", [])

        assert len(rubric) >= 5, (
            f"slug={slug}: scoring_config.rubric must have >= 5 dims, got {len(rubric)}"
        )
        assert len(rubric) == min_dims, (
            f"slug={slug}: expected {min_dims} rubric dims, got {len(rubric)}"
        )


def test_resolve_config_returns_rubric_list():
    """resolve_config must populate the .rubric field from scoring_config."""
    for slug in EXPECTED_SLUGS:
        row = fetch_one("SELECT scoring_config FROM challenges WHERE slug = ?", (slug,))
        assert row is not None, f"slug={slug!r} not found"
        cfg = resolve_config(row["scoring_config"])
        assert isinstance(cfg.rubric, list), (
            f"slug={slug}: resolve_config().rubric should be a list, got {type(cfg.rubric)}"
        )
        assert len(cfg.rubric) >= 5, (
            f"slug={slug}: resolve_config().rubric must have >= 5 items"
        )


def test_searchable_product_listing_rubric_dimensions():
    """Deep-verify the Searchable Product Listing UI rubric via resolve_config.

    Expected dimensions (from RUBRIC_E1):
      Functional Correctness (weight 10), Component Composition (weight 8),
      State and Performance (weight 7), UX Polish (weight 6), Code Quality (weight 5).
    """
    slug = "searchable-product-listing-ui"
    row = fetch_one("SELECT scoring_config FROM challenges WHERE slug = ?", (slug,))
    assert row is not None, f"{slug!r} not seeded"

    cfg = resolve_config(row["scoring_config"])
    rubric = cfg.rubric  # list of dicts

    assert len(rubric) == 5, f"Expected 5 rubric dims, got {len(rubric)}"

    names = [d["name"] for d in rubric]
    assert "Functional Correctness" in names, "Expected 'Functional Correctness' dim"
    assert "Component Composition" in names, "Expected 'Component Composition' dim"
    assert "State and Performance" in names, "Expected 'State and Performance' dim"
    assert "UX Polish" in names, "Expected 'UX Polish' dim"
    assert "Code Quality" in names, "Expected 'Code Quality' dim"

    # Verify weights
    weight_map = {d["name"]: d["weight"] for d in rubric}
    assert weight_map["Functional Correctness"] == 10
    assert weight_map["Component Composition"] == 8
    assert weight_map["State and Performance"] == 7
    assert weight_map["UX Polish"] == 6
    assert weight_map["Code Quality"] == 5


def test_rubric_dimensions_have_required_fields():
    """Every rubric dimension must have 'name', 'weight', and 'description' fields."""
    for slug in EXPECTED_SLUGS:
        row = fetch_one("SELECT scoring_config FROM challenges WHERE slug = ?", (slug,))
        assert row is not None
        cfg = resolve_config(row["scoring_config"])
        for dim in cfg.rubric:
            assert "name" in dim, f"slug={slug}: rubric dim missing 'name'"
            assert "weight" in dim, f"slug={slug}: rubric dim missing 'weight'"
            assert "description" in dim, f"slug={slug}: rubric dim missing 'description'"
            assert isinstance(dim["weight"], (int, float)), (
                f"slug={slug}: rubric dim weight must be numeric, got {type(dim['weight'])}"
            )
            assert dim["description"], f"slug={slug}: rubric dim description must not be empty"


def test_scoring_config_profile_spec_heavy_has_correct_axes():
    """For quality challenges, spec_heavy profile must provide direction=60, outcome=25, lift=15."""
    from app.services.scoring.config import build_rubric

    slug = "bookshelf-rest-api"
    row = fetch_one("SELECT scoring_config FROM challenges WHERE slug = ?", (slug,))
    assert row is not None

    rubric_display = build_rubric(row["scoring_config"])
    axes_map = {a["name"]: a["points"] for a in rubric_display["axes"]}

    assert axes_map.get("direction") == 60, f"spec_heavy direction must be 60, got {axes_map.get('direction')}"
    assert axes_map.get("outcome") == 25, f"spec_heavy outcome must be 25, got {axes_map.get('outcome')}"
    assert axes_map.get("lift") == 15, f"spec_heavy lift must be 15, got {axes_map.get('lift')}"
    assert rubric_display["profile"] == "spec_heavy"
