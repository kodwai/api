-- First-login welcome tracking.
-- welcomed_at is set the first time a developer sees the /dev/welcome intro.
-- NULL means "not yet welcomed" → the app shows the intro once on first login.
ALTER TABLE developer_profiles ADD COLUMN welcomed_at TEXT;

-- Backfill every existing developer as already welcomed so current users don't
-- get an out-of-nowhere intro. Only profiles created after this migration
-- (genuinely new signups) keep NULL and see the welcome.
UPDATE developer_profiles SET welcomed_at = datetime('now') WHERE welcomed_at IS NULL;
