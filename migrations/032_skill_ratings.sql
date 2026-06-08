-- Per-category / per-model mastery ratings (ELO) — KOD-79
CREATE TABLE IF NOT EXISTS user_skill_ratings (
  user_id TEXT NOT NULL,
  dimension TEXT NOT NULL,
  key TEXT NOT NULL,
  rating INTEGER NOT NULL DEFAULT 1000,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (user_id, dimension, key)
);
