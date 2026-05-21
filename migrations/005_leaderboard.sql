-- Leaderboard entries: best score per user per challenge

CREATE TABLE IF NOT EXISTS leaderboard_entries (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    challenge_id TEXT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    score REAL NOT NULL,
    rank INTEGER,
    agent_used TEXT,
    time_taken_ms INTEGER,
    submitted_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, challenge_id)
);

CREATE INDEX IF NOT EXISTS idx_leaderboard_challenge ON leaderboard_entries(challenge_id, rank);
CREATE INDEX IF NOT EXISTS idx_leaderboard_user ON leaderboard_entries(user_id);
CREATE INDEX IF NOT EXISTS idx_leaderboard_agent ON leaderboard_entries(agent_used);
CREATE INDEX IF NOT EXISTS idx_leaderboard_score ON leaderboard_entries(challenge_id, score DESC);
