-- Quest claims: idempotent per (user, quest, period) — gamification v3
CREATE TABLE IF NOT EXISTS quest_claims (
  user_id TEXT NOT NULL,
  quest_key TEXT NOT NULL,
  period_key TEXT NOT NULL,
  xp INTEGER NOT NULL DEFAULT 0,
  claimed_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (user_id, quest_key, period_key)
);
