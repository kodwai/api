-- Badges and developer_badges tables

CREATE TABLE IF NOT EXISTS badges (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    icon TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('milestone', 'skill', 'streak', 'special')),
    criteria TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_badges_slug ON badges(slug);
CREATE INDEX IF NOT EXISTS idx_badges_category ON badges(category);

CREATE TABLE IF NOT EXISTS developer_badges (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    badge_id TEXT NOT NULL REFERENCES badges(id) ON DELETE CASCADE,
    submission_id TEXT REFERENCES submissions(id),
    earned_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, badge_id)
);

CREATE INDEX IF NOT EXISTS idx_dev_badges_user ON developer_badges(user_id);
CREATE INDEX IF NOT EXISTS idx_dev_badges_badge ON developer_badges(badge_id);

-- Seed badge definitions

PRAGMA foreign_keys = OFF;

INSERT OR IGNORE INTO badges (id, name, slug, description, icon, category, criteria) VALUES
('badge_first_blood', 'First Blood', 'first-blood', 'Complete your first challenge', 'sword', 'milestone', '{"type":"challenges_completed","min":1}'),
('badge_five_down', 'Five Down', 'five-down', 'Complete 5 challenges', 'star', 'milestone', '{"type":"challenges_completed","min":5}'),
('badge_ten_strong', 'Ten Strong', 'ten-strong', 'Complete 10 challenges', 'trophy', 'milestone', '{"type":"challenges_completed","min":10}'),
('badge_quarter_century', 'Quarter Century', 'quarter-century', 'Complete 25 challenges', 'crown', 'milestone', '{"type":"challenges_completed","min":25}'),
('badge_streak_3', 'On Fire', 'streak-3', 'Complete challenges 3 days in a row', 'flame', 'streak', '{"type":"streak","min":3}'),
('badge_streak_7', 'Week Warrior', 'streak-7', 'Complete challenges 7 days in a row', 'flame-double', 'streak', '{"type":"streak","min":7}'),
('badge_streak_30', 'Monthly Machine', 'streak-30', 'Complete challenges 30 days in a row', 'flame-triple', 'streak', '{"type":"streak","min":30}'),
('badge_top_10', 'Top 10%', 'top-10', 'Score in the top 10% on any challenge', 'medal', 'skill', '{"type":"percentile","max_percentile":10}'),
('badge_speed_demon', 'Speed Demon', 'speed-demon', 'Complete a challenge in under 50% of the time limit', 'lightning', 'skill', '{"type":"speed","max_ratio":0.5}'),
('badge_perfect', 'Perfectionist', 'perfect-score', 'Score 95 or above on any challenge', 'diamond', 'skill', '{"type":"min_score","min":95}'),
('badge_polyglot', 'Polyglot', 'polyglot', 'Complete challenges in 3 or more categories', 'globe', 'skill', '{"type":"categories","min":3}'),
('badge_claude_master', 'Claude Master', 'claude-master', 'Score 80+ on 5 challenges using Claude Code', 'brain', 'special', '{"type":"agent_score","agent":"claude-code","min_score":80,"min_count":5}'),
('badge_cursor_pro', 'Cursor Pro', 'cursor-pro', 'Score 80+ on 5 challenges using Cursor', 'cursor', 'special', '{"type":"agent_score","agent":"cursor","min_score":80,"min_count":5}'),
('badge_early_adopter', 'Early Adopter', 'early-adopter', 'Join kodwai in the first 30 days', 'clock', 'special', '{"type":"early_adopter","days":30}');

PRAGMA foreign_keys = ON;
