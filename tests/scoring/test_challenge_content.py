"""Tests for challenge content quality (KOD-70).

Migration 017: debug-auth-flow and performance-bottleneck get runnable starter
files and test suites; react-component-refactor gets starter files only.

Migration 018: only the core 12 challenges are public; all others are drafted.
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

# Known non-core slugs that are seeded in the test DB (verified present)
NON_CORE_SLUGS = ["sql-query-engine", "theme-switcher", "api-gateway"]


# ── Migration 017 ─────────────────────────────────────────────────────────────

class TestMigration017StarterFiles:
    def _get(self, slug: str):
        return fetch_one(
            "SELECT starter_files, test_suite FROM challenges WHERE slug = ?",
            (slug,),
        )

    def test_debug_auth_flow_has_starter_files(self):
        row = self._get("debug-auth-flow")
        assert row["starter_files"] is not None, "debug-auth-flow must have starter_files"
        files = json.loads(row["starter_files"])
        assert isinstance(files, list) and len(files) >= 1, (
            "starter_files must be a JSON array with at least 1 file"
        )
        paths = [f["path"] for f in files]
        assert "auth.js" in paths, "starter_files must include auth.js"

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

    def test_performance_bottleneck_has_starter_files(self):
        row = self._get("performance-bottleneck")
        assert row["starter_files"] is not None, "performance-bottleneck must have starter_files"
        files = json.loads(row["starter_files"])
        assert isinstance(files, list) and len(files) >= 1, (
            "starter_files must be a JSON array with at least 1 file"
        )
        paths = [f["path"] for f in files]
        assert "dashboard.js" in paths, "starter_files must include dashboard.js"

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

    def test_react_component_refactor_has_starter_files(self):
        row = self._get("react-component-refactor")
        assert row["starter_files"] is not None, (
            "react-component-refactor must have starter_files"
        )
        files = json.loads(row["starter_files"])
        assert isinstance(files, list) and len(files) >= 1, (
            "starter_files must be a JSON array with at least 1 file"
        )

    def test_starter_files_content_is_non_empty(self):
        """Each starter file must have a non-empty 'content' field."""
        for slug in ("debug-auth-flow", "performance-bottleneck", "react-component-refactor"):
            row = self._get(slug)
            files = json.loads(row["starter_files"])
            for f in files:
                assert f.get("content"), (
                    f"{slug}: starter file '{f.get('path')}' has empty content"
                )

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

class TestMigration018CurateCore:
    def _get_public_slugs(self) -> list[str]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT slug FROM challenges WHERE is_public = 1"
        ).fetchall()
        return [r[0] for r in rows]

    def test_all_core_12_are_public(self):
        public = set(self._get_public_slugs())
        conn = get_connection()
        seeded = {
            r[0]
            for r in conn.execute("SELECT slug FROM challenges").fetchall()
        }
        for slug in CORE_12:
            if slug in seeded:
                assert slug in public, (
                    f"Core challenge '{slug}' should be public (is_public=1)"
                )

    def test_non_core_challenges_are_not_public(self):
        public = set(self._get_public_slugs())
        for slug in NON_CORE_SLUGS:
            assert slug not in public, (
                f"Non-core challenge '{slug}' should be drafted (is_public=0)"
            )

    def test_exactly_12_or_fewer_public_challenges(self):
        public = self._get_public_slugs()
        assert len(public) <= 12, (
            f"Expected at most 12 public challenges, found {len(public)}: {public}"
        )

    def test_at_least_one_non_core_is_drafted(self):
        conn = get_connection()
        drafted = conn.execute(
            "SELECT COUNT(*) FROM challenges WHERE is_public = 0"
        ).fetchone()[0]
        assert drafted >= 1, "At least one non-core challenge should be drafted"
