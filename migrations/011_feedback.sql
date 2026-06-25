-- Feedback system: challenge feedback + platform feedback

-- Challenge feedback: one per user per challenge, upsertable
CREATE TABLE IF NOT EXISTS challenge_feedback (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    challenge_id TEXT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    submission_id TEXT REFERENCES submissions(id) ON DELETE SET NULL,
    rating_overall INTEGER NOT NULL CHECK (rating_overall BETWEEN 1 AND 5),
    rating_difficulty INTEGER CHECK (rating_difficulty BETWEEN 1 AND 5),
    rating_clarity INTEGER CHECK (rating_clarity BETWEEN 1 AND 5),
    comment TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, challenge_id)
);

CREATE INDEX IF NOT EXISTS idx_cf_challenge ON challenge_feedback(challenge_id);
CREATE INDEX IF NOT EXISTS idx_cf_user ON challenge_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_cf_created ON challenge_feedback(created_at DESC);

-- Platform feedback: bug reports, feature requests, general feedback
CREATE TABLE IF NOT EXISTS platform_feedback (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL CHECK (category IN ('bug_report', 'feature_request', 'general', 'improvement')),
    description TEXT NOT NULL,
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    page_url TEXT,
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'reviewed', 'resolved', 'dismissed')),
    admin_response TEXT,
    admin_responded_by TEXT REFERENCES users(id),
    admin_responded_at TEXT,
    is_flagged INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pf_user ON platform_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_pf_category ON platform_feedback(category);
CREATE INDEX IF NOT EXISTS idx_pf_status ON platform_feedback(status);
CREATE INDEX IF NOT EXISTS idx_pf_created ON platform_feedback(created_at DESC);
