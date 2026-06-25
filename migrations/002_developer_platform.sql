-- Kodwai v2: Developer Platform Migration
-- Adds user_type and username to users table
-- Creates challenges, submissions, developer_profiles tables
-- Extends api_keys with user_id for developer-scoped keys

PRAGMA foreign_keys = OFF;

-- ============================================================
-- Step 1: Recreate users table with user_type + nullable org_id
-- ============================================================

CREATE TABLE IF NOT EXISTS users_new (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    organization_id TEXT REFERENCES organizations(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    username TEXT UNIQUE,
    role TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin', 'interviewer', 'viewer')),
    user_type TEXT NOT NULL DEFAULT 'company' CHECK (user_type IN ('developer', 'company')),
    email_verified INTEGER NOT NULL DEFAULT 0,
    email_verification_token TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO users_new (id, organization_id, email, password_hash, name, role, user_type, email_verified, email_verification_token, created_at)
SELECT id, organization_id, email, password_hash, name, role, 'company', email_verified, email_verification_token, created_at
FROM users;

DROP TABLE users;

ALTER TABLE users_new RENAME TO users;

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_org ON users(organization_id);
CREATE INDEX IF NOT EXISTS idx_users_verification ON users(email_verification_token);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_type ON users(user_type);

-- ============================================================
-- Step 2: Extend api_keys with user_id for developer-scoped keys
-- ============================================================

CREATE TABLE IF NOT EXISTS api_keys_new (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    organization_id TEXT REFERENCES organizations(id) ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    encrypted_key TEXT NOT NULL,
    key_iv TEXT NOT NULL,
    key_last4 TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'Default',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO api_keys_new (id, organization_id, encrypted_key, key_iv, key_last4, label, is_active, created_at)
SELECT id, organization_id, encrypted_key, key_iv, key_last4, label, is_active, created_at
FROM api_keys;

DROP TABLE api_keys;

ALTER TABLE api_keys_new RENAME TO api_keys;

CREATE INDEX IF NOT EXISTS idx_api_keys_org ON api_keys(organization_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);

-- ============================================================
-- Step 3: Challenges table
-- ============================================================

CREATE TABLE IF NOT EXISTS challenges (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    created_by TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    problem_statement_md TEXT NOT NULL,
    difficulty TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    category TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    time_limit_minutes INTEGER NOT NULL DEFAULT 60,
    test_suite TEXT,
    scoring_config TEXT NOT NULL DEFAULT '{}',
    starter_files TEXT,
    allowed_tools TEXT,
    disallowed_tools TEXT,
    max_budget_usd REAL,
    is_public INTEGER NOT NULL DEFAULT 1,
    is_featured INTEGER NOT NULL DEFAULT 0,
    submission_count INTEGER NOT NULL DEFAULT 0,
    avg_score REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_challenges_slug ON challenges(slug);
CREATE INDEX IF NOT EXISTS idx_challenges_difficulty ON challenges(difficulty);
CREATE INDEX IF NOT EXISTS idx_challenges_category ON challenges(category);
CREATE INDEX IF NOT EXISTS idx_challenges_public ON challenges(is_public);
CREATE INDEX IF NOT EXISTS idx_challenges_featured ON challenges(is_featured);

-- ============================================================
-- Step 4: Developer profiles table
-- ============================================================

CREATE TABLE IF NOT EXISTS developer_profiles (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    bio TEXT,
    github_url TEXT,
    linkedin_url TEXT,
    website_url TEXT,
    skills TEXT DEFAULT '[]',
    preferred_agent TEXT,
    total_score REAL NOT NULL DEFAULT 0,
    challenges_completed INTEGER NOT NULL DEFAULT 0,
    rank INTEGER,
    streak_days INTEGER NOT NULL DEFAULT 0,
    last_submission_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dev_profiles_user ON developer_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_dev_profiles_rank ON developer_profiles(rank);
CREATE INDEX IF NOT EXISTS idx_dev_profiles_score ON developer_profiles(total_score DESC);

-- ============================================================
-- Step 5: Submissions table
-- ============================================================

CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    challenge_id TEXT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'in_progress'
        CHECK (status IN ('in_progress', 'submitted', 'scoring', 'scored', 'error')),
    mode TEXT NOT NULL DEFAULT 'local',
    agent_used TEXT,
    agent_trace TEXT,
    score REAL,
    score_breakdown TEXT,
    time_taken_ms INTEGER,
    code_snapshot TEXT,
    git_diff TEXT,
    git_log TEXT,
    test_results TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    submitted_at TEXT,
    scored_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_submissions_challenge ON submissions(challenge_id);
CREATE INDEX IF NOT EXISTS idx_submissions_user ON submissions(user_id);
CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);
CREATE INDEX IF NOT EXISTS idx_submissions_score ON submissions(challenge_id, score DESC);

PRAGMA foreign_keys = ON;
