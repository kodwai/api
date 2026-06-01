-- Free submissions tier
-- Tracks which Anthropic key paid for a submission's AI scoring so we can meter
-- the platform-funded free tier. key_source values:
--   'platform' — scored with the platform's own key (consumes a free credit)
--   'user'     — scored with the developer's own connected key (unlimited)
--   NULL       — legacy rows scored before this column existed
ALTER TABLE submissions ADD COLUMN key_source TEXT;

-- Counting a developer's used free credits is a hot path on every entitlement
-- check (auth/me, challenge start, submit), so index (user_id, key_source).
CREATE INDEX IF NOT EXISTS idx_submissions_user_key_source ON submissions(user_id, key_source);
