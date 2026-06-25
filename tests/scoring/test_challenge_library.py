"""Tests for the extended CHALLENGE_LIBRARY of senior build-from-scratch challenges.

Verifies the content module in app/services/challenge_library.py:
- exactly 6 challenges,
- each with >= 6 anchored rubric dimensions (every description contains "10/10"),
- weights present and roughly descending, every dim well-formed,
- slugs kebab-case, unique, and distinct from the 9 existing quality slugs,
- catalogue dicts carry the full required shape (category/difficulty/budget/etc.).
"""
from __future__ import annotations

import re

from app.services.challenge_library import CHALLENGE_LIBRARY

# The 9 existing quality slugs (from DEFAULT_PROJECTS / migration 019). The new
# library must not collide with any of these.
EXISTING_QUALITY_SLUGS: set[str] = {
    "searchable-product-listing-ui",
    "offline-first-notes-app",
    "bookshelf-rest-api",
    "idempotent-etl-pipeline-with-schema-drift",
    "multi-tenant-feature-flag-service",
    "secrets-vault-with-envelope-encryption",
    "production-rag-service-with-eval-harness-cost-guardrails",
    "multi-currency-wallet-ledger-with-idempotent-transfers",
    "zero-downtime-schema-migration-progressive-rollout",
}

VALID_CATEGORIES = {"distributed", "realtime", "data", "search", "platform", "backend"}

_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def test_library_has_exactly_six_challenges():
    assert len(CHALLENGE_LIBRARY) == 6, (
        f"Expected 6 challenges, got {len(CHALLENGE_LIBRARY)}"
    )


def test_every_challenge_has_required_top_level_fields():
    required = {
        "title",
        "slug",
        "description",
        "category",
        "difficulty",
        "time_limit_minutes",
        "rubric",
        "max_budget_usd",
    }
    for ch in CHALLENGE_LIBRARY:
        missing = required - set(ch)
        assert not missing, f"{ch.get('slug')!r} missing fields: {missing}"
        assert ch["difficulty"] == "hard", f"{ch['slug']}: must be hard"
        assert ch["category"] in VALID_CATEGORIES, (
            f"{ch['slug']}: category {ch['category']!r} not in {VALID_CATEGORIES}"
        )
        assert 90 <= ch["time_limit_minutes"] <= 150, (
            f"{ch['slug']}: time_limit_minutes out of [90,150]: {ch['time_limit_minutes']}"
        )
        assert 8 <= ch["max_budget_usd"] <= 12, (
            f"{ch['slug']}: max_budget_usd out of [8,12]: {ch['max_budget_usd']}"
        )
        # description is 2-3 sentences of senior framing
        assert ch["description"].strip(), f"{ch['slug']}: empty description"
        assert ch["description"].count(".") >= 2, (
            f"{ch['slug']}: description should be 2-3 sentences"
        )


def test_slugs_are_kebab_unique_and_distinct_from_existing():
    slugs = [ch["slug"] for ch in CHALLENGE_LIBRARY]
    for s in slugs:
        assert _KEBAB.match(s), f"slug {s!r} is not kebab-case"
    assert len(set(slugs)) == len(slugs), f"duplicate slugs: {slugs}"
    overlap = set(slugs) & EXISTING_QUALITY_SLUGS
    assert not overlap, f"slug(s) collide with existing quality challenges: {overlap}"


def test_each_challenge_has_at_least_six_rubric_dims():
    for ch in CHALLENGE_LIBRARY:
        rubric = ch["rubric"]
        assert isinstance(rubric, list), f"{ch['slug']}: rubric must be a list"
        assert len(rubric) >= 6, (
            f"{ch['slug']}: expected >= 6 rubric dims, got {len(rubric)}"
        )
        assert len(rubric) <= 9, (
            f"{ch['slug']}: expected <= 9 rubric dims, got {len(rubric)}"
        )


def test_every_rubric_dimension_is_well_formed_and_anchored():
    for ch in CHALLENGE_LIBRARY:
        names = set()
        for dim in ch["rubric"]:
            assert {"name", "weight", "description"} <= set(dim), (
                f"{ch['slug']}: rubric dim malformed: {dim.get('name')}"
            )
            assert dim["name"], f"{ch['slug']}: rubric dim missing name"
            assert dim["name"] not in names, (
                f"{ch['slug']}: duplicate dim name {dim['name']!r}"
            )
            names.add(dim["name"])
            assert isinstance(dim["weight"], (int, float)), (
                f"{ch['slug']}/{dim['name']}: weight must be numeric"
            )
            assert 4 <= dim["weight"] <= 10, (
                f"{ch['slug']}/{dim['name']}: weight {dim['weight']} out of [4,10]"
            )
            desc = dim["description"]
            # anchored at all four bands
            for anchor in ("2/10", "5/10", "8/10", "10/10"):
                assert anchor in desc, (
                    f"{ch['slug']}/{dim['name']}: description missing {anchor} anchor"
                )
            # anchors should carry real, specific content (not stubs)
            assert len(desc) > 200, (
                f"{ch['slug']}/{dim['name']}: anchored description suspiciously short"
            )


def test_first_rubric_dimension_is_highest_weighted():
    """The top dimension carries the most senior signal (weight ~10, descending order)."""
    for ch in CHALLENGE_LIBRARY:
        weights = [d["weight"] for d in ch["rubric"]]
        assert weights[0] == max(weights), (
            f"{ch['slug']}: first dim should be the highest-weighted"
        )
        assert weights[0] >= 9, (
            f"{ch['slug']}: top dimension weight should be >= 9, got {weights[0]}"
        )
        # broadly importance-ordered: last dim is the lowest weight
        assert weights[-1] == min(weights), (
            f"{ch['slug']}: last dim should be the lowest-weighted"
        )


def test_problem_domains_are_all_covered():
    slugs = {ch["slug"] for ch in CHALLENGE_LIBRARY}
    expected = {
        "raft-lite-log-replication",
        "crdt-collaborative-text-buffer",
        "time-series-metrics-store",
        "inverted-index-search-with-ranking",
        "multi-tenant-rate-limiter-quota-service",
        "process-task-orchestrator-lite",
    }
    assert slugs == expected, f"slug set mismatch: {slugs ^ expected}"
