"""Tests for challenge content quality (KOD-70).

Migration 017: debug-auth-flow and performance-bottleneck get runnable starter
files and test suites; react-component-refactor gets starter files only.

Migration 018: only the core 12 challenges are public; all others are drafted.

Migration 020: curates the catalog to exactly 15 quality challenges and DELETES
all legacy seed challenges including debug-auth-flow, performance-bottleneck,
react-component-refactor, and the old non-core slugs. The TestMigration017*
tests are skipped because those challenges no longer exist post-020. The
TestMigration018CurateCore count assertions are updated to reflect 020's
curated catalog of 15 all-public challenges.
"""
from __future__ import annotations

import json
import pytest

from app.core.database import fetch_one, get_connection


CORE_12 = [
    "build-rest-api",
    "url-shortener",
    "debug-auth-flow",
    "accessible-form-builder",
    "react-component-refactor",
    "job-queue-retries",
    "webhook-delivery-system",
    "performance-bottleneck",
    "algorithm-rate-limiter",
    "lru-cache-ttl",
    "event-sourcing-store",
    "mini-git",
]

# Known non-core slugs — all deleted by migration 020.
NON_CORE_SLUGS = ["sql-query-engine", "theme-switcher", "api-gateway"]


# ── Migration 017 ─────────────────────────────────────────────────────────────
# NOTE: Migration 020 deletes debug-auth-flow, performance-bottleneck, and
# react-component-refactor as part of the legacy-cleanup. These tests are
# skipped with an explanatory reason rather than removed, to preserve the
# history of what migration 017 originally verified.

_020_DELETED = pytest.mark.skip(
    reason="Migration 020 deleted this legacy challenge; it no longer exists in the catalog."
)


class TestMigration017StarterFiles:
    def _get(self, slug: str):
        return fetch_one(
            "SELECT starter_files, test_suite FROM challenges WHERE slug = ?",
            (slug,),
        )

    @_020_DELETED
    def test_debug_auth_flow_has_starter_files(self):
        row = self._get("debug-auth-flow")
        assert row["starter_files"] is not None, "debug-auth-flow must have starter_files"
        files = json.loads(row["starter_files"])
        assert isinstance(files, list) and len(files) >= 1, (
            "starter_files must be a JSON array with at least 1 file"
        )
        paths = [f["path"] for f in files]
        assert "auth.js" in paths, "starter_files must include auth.js"

    @_020_DELETED
    def test_debug_auth_flow_has_test_suite_with_command(self):
        row = self._get("debug-auth-flow")
        assert row["test_suite"] is not None, "debug-auth-flow must have test_suite"
        suite = json.loads(row["test_suite"])
        assert isinstance(suite, list) and len(suite) >= 1
        entry = suite[0]
        assert "command" in entry and entry["command"], (
            "test_suite entry must have a non-empty command"
        )
        assert "node" in entry["command"], "command must invoke node"

    @_020_DELETED
    def test_performance_bottleneck_has_starter_files(self):
        row = self._get("performance-bottleneck")
        assert row["starter_files"] is not None, "performance-bottleneck must have starter_files"
        files = json.loads(row["starter_files"])
        assert isinstance(files, list) and len(files) >= 1, (
            "starter_files must be a JSON array with at least 1 file"
        )
        paths = [f["path"] for f in files]
        assert "dashboard.js" in paths, "starter_files must include dashboard.js"

    @_020_DELETED
    def test_performance_bottleneck_has_test_suite_with_command(self):
        row = self._get("performance-bottleneck")
        assert row["test_suite"] is not None, "performance-bottleneck must have test_suite"
        suite = json.loads(row["test_suite"])
        assert isinstance(suite, list) and len(suite) >= 1
        entry = suite[0]
        assert "command" in entry and entry["command"], (
            "test_suite entry must have a non-empty command"
        )
        assert "node" in entry["command"], "command must invoke node"

    @_020_DELETED
    def test_react_component_refactor_has_starter_files(self):
        row = self._get("react-component-refactor")
        assert row["starter_files"] is not None, (
            "react-component-refactor must have starter_files"
        )
        files = json.loads(row["starter_files"])
        assert isinstance(files, list) and len(files) >= 1, (
            "starter_files must be a JSON array with at least 1 file"
        )

    @_020_DELETED
    def test_starter_files_content_is_non_empty(self):
        """Each starter file must have a non-empty 'content' field."""
        for slug in ("debug-auth-flow", "performance-bottleneck", "react-component-refactor"):
            row = self._get(slug)
            files = json.loads(row["starter_files"])
            for f in files:
                assert f.get("content"), (
                    f"{slug}: starter file '{f.get('path')}' has empty content"
                )

    @_020_DELETED
    def test_test_suite_content_is_non_empty(self):
        """Each test_suite entry must have a non-empty 'content' field."""
        for slug in ("debug-auth-flow", "performance-bottleneck"):
            row = self._get(slug)
            suite = json.loads(row["test_suite"])
            for entry in suite:
                assert entry.get("content"), (
                    f"{slug}: test_suite entry has empty content"
                )


# ── Migration 018 ─────────────────────────────────────────────────────────────
# NOTE: Migration 019 (quality_rubric_challenges) supersedes migration 018's
# keep-12 curation. The public core is now exactly the 9 bespoke-rubric
# challenges. Tests below are updated to reflect the current truth.

# The 9 new public slugs installed by migration 019.
CORE_9_RUBRIC = [
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


class TestMigration018CurateCore:
    def _get_public_slugs(self) -> list[str]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT slug FROM challenges WHERE is_public = 1"
        ).fetchall()
        return [r[0] for r in rows]

    def test_all_core_9_rubric_challenges_are_public(self):
        """Migration 020 keeps all 15 curated challenges as is_public=1.

        The 9 original quality rubric challenges from migration 019 must all
        still be public in the curated catalog.
        """
        public = set(self._get_public_slugs())
        for slug in CORE_9_RUBRIC:
            assert slug in public, (
                f"Quality challenge '{slug}' should be public after migration 020"
            )

    def test_non_core_challenges_are_deleted(self):
        """Migration 020 deletes all non-keep-list challenges (they don't exist at all)."""
        conn = get_connection()
        all_slugs = {
            r[0]
            for r in conn.execute("SELECT slug FROM challenges").fetchall()
        }
        for slug in NON_CORE_SLUGS:
            assert slug not in all_slugs, (
                f"Non-core challenge '{slug}' should have been deleted by migration 020"
            )

    def test_exactly_15_public_challenges(self):
        """After migration 020 there are exactly 15 public challenges."""
        public = self._get_public_slugs()
        assert len(public) == 15, (
            f"Expected exactly 15 public challenges after migration 020, found {len(public)}: {sorted(public)}"
        )

    def test_zero_challenges_are_drafted(self):
        """After migration 020, all challenges in the catalog are public (0 drafted)."""
        conn = get_connection()
        drafted = conn.execute(
            "SELECT COUNT(*) FROM challenges WHERE is_public = 0"
        ).fetchone()[0]
        assert drafted == 0, (
            f"Expected 0 drafted challenges after migration 020, got {drafted}"
        )
