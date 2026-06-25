"""Generator script for migration 019: 9 bespoke-rubric challenges from DEFAULT_PROJECTS.

Run from the repo root:
    python scripts/gen_quality_challenges_migration.py

Emits:
    migrations/019_quality_rubric_challenges.sql
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Ensure the repo root is on sys.path so `app` is importable.
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.services.default_projects import DEFAULT_PROJECTS  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXISTING_SLUGS: set[str] = {
    # Slugs present in migrations 003–018 (collected from the seed files).
    "build-rest-api",
    "react-component-refactor",
    "debug-auth-flow",
    "cli-file-processing",
    "database-schema-design",
    "algorithm-rate-limiter",
    "fullstack-realtime-chat",
    "url-shortener",
    "job-queue-retries",
    "accessible-form-builder",
    "performance-bottleneck",
    "webhook-delivery-system",
    "event-sourcing-store",
    "mini-git",
    "lru-cache-ttl",
    "env-config-parser",
    "bookmark-manager",
    "markdown-note-app",
    "theme-switcher",
    "drag-drop-uploader",
    "api-gateway",
    "csv-api-pipeline",
    "etl-pipeline-validation",
    "contact-form-spam-filter",
    "command-palette",
    "data-table-component",
    "extract-design-system",
    "feature-flag-system",
    "distributed-kv-store",
    "distributed-task-scheduler",
    "pubsub-message-broker",
    "health-check-dashboard",
    "cicd-pipeline-scratch",
    "docker-multi-stage-build",
    "graphql-api-scratch",
    "oauth2-auth-server",
    "regex-engine-scratch",
    "minilang-compiler",
    "mini-sql-engine",
    "collaborative-text-editor",
    "realtime-kanban-board",
    "browser-layout-engine",
    "search-engine",
    "sql-query-engine",
    "dependency-resolver",
    "distributed-task-scheduler",
    "rate-limiter-middleware",
    "task-scheduler-cron",
    "workflow-builder",
    "reactive-database",
    "callback-hell-async",
    "fix-flaky-tests",
    "fix-memory-leak",
    "race-condition-hunter",
    "untangle-spaghetti",
    "log-file-analyzer",
    "json-schema-validator",
    "markdown-html-converter",
    "system-design",
}


def to_slug(title: str) -> str:
    """Convert a title to a kebab-case slug, stripping non-alphanumeric chars."""
    s = title.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)   # strip non-alphanum (& etc)
    s = re.sub(r"[\s_]+", "-", s.strip())  # spaces/underscores → hyphens
    s = re.sub(r"-+", "-", s)              # collapse multiple hyphens
    return s.strip("-")


def sql_escape(text: str) -> str:
    """Escape a string for use as a SQL single-quoted literal."""
    return text.replace("'", "''")


def sq(text: str) -> str:
    """Wrap in single quotes after escaping."""
    return "'" + sql_escape(text) + "'"


def infer_category(title: str, description: str) -> str:
    """Infer a category from the project title / description (title takes priority)."""
    t = title.lower()
    d = description.lower()
    combined = t + " " + d

    def w(word: str) -> bool:
        """True if word appears as a whole-word substring in combined."""
        return bool(re.search(r"\b" + re.escape(word) + r"\b", combined))

    if "rag" in t or "llm" in t or w("retrieval") or w("embedding"):
        return "ai"
    if w("vault") or w("encrypt") or "kek" in t or ("secret" in t and "vault" in t):
        return "security"
    if "security" in t and ("engineer" in t or "engineer" in d):
        return "security"
    if "etl" in t or ("pipeline" in t and "schema drift" in t):
        return "data"
    if w("data engineer") or ("csv" in t and "pipeline" in t):
        return "data"
    if "ledger" in t or "wallet" in t or ("multi-currency" in t):
        return "backend"
    if "feature flag" in t or ("schema migration" in t) or ("zero-downtime" in t):
        return "platform"
    if "sre" in d or "rollout" in t:
        return "platform"
    if "mobile" in d or "react native" in d or "flutter" in d or "notes app" in t:
        return "mobile"
    if "bookshelf" in t or "rest api" in t or "backend" in d[:40]:
        return "backend"
    if "product listing" in t or "searchable" in t:
        return "frontend"
    if w("frontend") or "ui" in t:
        return "frontend"
    if w("backend") or w("crud"):
        return "backend"
    return "fullstack"


# Tags mapping per project title
TAGS: dict[str, list[str]] = {
    "Searchable Product Listing UI":                              ["react", "frontend", "state-management", "accessibility"],
    "Offline-First Notes App":                                    ["mobile", "react-native", "offline", "persistence"],
    "Bookshelf REST API":                                         ["rest", "api", "backend", "testing"],
    "Idempotent ETL Pipeline with Schema Drift":                  ["etl", "data-engineering", "pipeline", "idempotency"],
    "Multi-Tenant Feature Flag Service":                          ["feature-flags", "multi-tenant", "platform", "rollout"],
    "Secrets Vault with Envelope Encryption":                     ["security", "cryptography", "vault", "key-management"],
    "Production RAG Service with Eval Harness & Cost Guardrails": ["ai", "rag", "llm", "multi-tenant"],
    "Multi-Currency Wallet Ledger with Idempotent Transfers":     ["fintech", "ledger", "double-entry", "idempotency"],
    "Zero-Downtime Schema Migration & Progressive Rollout":       ["sre", "migrations", "zero-downtime", "platform"],
}


def generate_migration() -> str:
    lines: list[str] = []

    lines.append("-- Migration 019: 9 bespoke-rubric challenges from DEFAULT_PROJECTS")
    lines.append("-- Generated by scripts/gen_quality_challenges_migration.py")
    lines.append("-- These become the curated public core for the B2C platform.")
    lines.append("--")
    lines.append("-- created_by uses 'system' (same pattern as migrations 003-011)")
    lines.append("-- with PRAGMA foreign_keys = OFF so the FK is satisfied at apply time.")
    lines.append("")
    lines.append("PRAGMA foreign_keys = OFF;")
    lines.append("")

    new_slugs: list[str] = []

    for i, project in enumerate(DEFAULT_PROJECTS, start=1):
        title = project["title"]
        slug = to_slug(title)

        # Prefix with 'q-' if slug collides with an existing one.
        if slug in EXISTING_SLUGS:
            slug = "q-" + slug

        new_slugs.append(slug)

        description = project["description"]
        problem_statement_md = project["problem_statement_md"]
        difficulty = project["difficulty"]
        time_limit_minutes = project["time_limit_minutes"]
        max_budget_usd = project["max_budget_usd"]
        rubric = project["rubric"]

        category = infer_category(title, description)
        tags_list = TAGS.get(title, [])
        tags_json = json.dumps(tags_list)

        scoring_config = json.dumps({"profile": "spec_heavy", "rubric": rubric})

        challenge_id = f"quality_challenge_{i:03d}"

        lines.append(f"-- ============================================================")
        lines.append(f"-- Q{i}: {title}")
        lines.append(f"-- slug: {slug} | category: {category} | difficulty: {difficulty}")
        lines.append(f"-- rubric dimensions: {len(rubric)}")
        lines.append(f"-- ============================================================")
        lines.append("")
        lines.append("INSERT OR IGNORE INTO challenges")
        lines.append("    (id, created_by, title, slug, description, problem_statement_md,")
        lines.append("     difficulty, category, tags, time_limit_minutes, test_suite,")
        lines.append("     scoring_config, starter_files, max_budget_usd, is_public, is_featured)")
        lines.append("VALUES")
        lines.append("(")
        lines.append(f"    {sq(challenge_id)},")
        lines.append(f"    'system',")
        lines.append(f"    {sq(title)},")
        lines.append(f"    {sq(slug)},")
        lines.append(f"    {sq(description)},")
        lines.append(f"    {sq(problem_statement_md)},")
        lines.append(f"    '{difficulty}',")
        lines.append(f"    '{category}',")
        lines.append(f"    {sq(tags_json)},")
        lines.append(f"    {time_limit_minutes},")
        lines.append(f"    NULL,")
        lines.append(f"    {sq(scoring_config)},")
        lines.append(f"    NULL,")
        lines.append(f"    {max_budget_usd},")
        lines.append(f"    1,")
        lines.append(f"    1")
        lines.append(");")
        lines.append("")

    # --------------------------------------------------------------------
    # Curate public core: exactly the 9 new rubric challenges
    # --------------------------------------------------------------------
    slug_list = ", ".join(sq(s) for s in new_slugs)
    lines.append("-- ============================================================")
    lines.append("-- Curate public core: exactly the 9 bespoke-rubric challenges.")
    lines.append("-- This supersedes migration 018's keep-12 curation.")
    lines.append("-- Reversible: only flips is_public; no challenges are deleted.")
    lines.append("-- ============================================================")
    lines.append("")
    lines.append(f"UPDATE challenges SET is_public = 0 WHERE slug NOT IN ({slug_list});")
    lines.append("")
    lines.append("PRAGMA foreign_keys = ON;")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    sql = generate_migration()

    out_path = REPO_ROOT / "migrations" / "019_quality_rubric_challenges.sql"
    out_path.write_text(sql, encoding="utf-8")
    print(f"Written: {out_path}")

    # Print summary
    print("\nSummary of 9 challenges:")
    for i, project in enumerate(DEFAULT_PROJECTS, start=1):
        title = project["title"]
        slug = to_slug(title)
        if slug in EXISTING_SLUGS:
            slug = "q-" + slug
        category = infer_category(title, project["description"])
        rubric_dims = len(project["rubric"])
        print(f"  Q{i}: {slug}  [{category}]  {rubric_dims} dims")


if __name__ == "__main__":
    main()
