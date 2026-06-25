-- Feature flags: on/off + optional schedule window — gates Weekly Sprint, Wrapped, etc.
CREATE TABLE IF NOT EXISTS feature_flags (
  key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  starts_at TEXT,
  ends_at TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO feature_flags (key, name, description, enabled) VALUES
  ('weekly_sprint', 'Weekly Sprint', 'The recurring weekly contest (challenges page card + /dev/sprint).', 1),
  ('wrapped', 'kodwai Wrapped', 'The Spotify-Wrapped-style recap (/dev/wrapped + profile link).', 1);
