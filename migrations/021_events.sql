-- Time-boxed Event system: events + event_winners tables

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    is_finalized INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_slug ON events(slug);
CREATE INDEX IF NOT EXISTS idx_events_starts_at ON events(starts_at DESC);

CREATE TABLE IF NOT EXISTS event_winners (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    score REAL NOT NULL,
    awarded_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(event_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_event_winners_event ON event_winners(event_id);
CREATE INDEX IF NOT EXISTS idx_event_winners_user ON event_winners(user_id);

-- Seed the "Event Top 3" badge used when finalizing an event
INSERT OR IGNORE INTO badges (id, name, slug, description, icon, category, criteria, is_active)
VALUES (
    'badge_event_top3',
    'Event Top 3',
    'event-top-3',
    'Finished in the top 3 of a time-boxed Kodwai event',
    'trophy',
    'special',
    '{}',
    1
);
