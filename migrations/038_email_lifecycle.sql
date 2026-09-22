-- 038_email_lifecycle.sql
-- Lifecycle email foundation: a send ledger keyed by a unique dedupe_key (claim-then-send),
-- per-user unsubscribe / suppression / marketing-consent timestamps, and kill-switch flags.
-- Comments live on their own lines: the runner drops comment-only lines.
-- email_sends: one row per attempted send. status: claimed (row won, send in flight),
-- sent, failed (retryable up to 3 attempts), skipped (recorded by a caller that chose not to send).
CREATE TABLE IF NOT EXISTS email_sends (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    to_email TEXT NOT NULL,
    template TEXT NOT NULL,
    stream TEXT NOT NULL DEFAULT 'lifecycle' CHECK (stream IN ('transactional', 'lifecycle', 'feedback')),
    dedupe_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'claimed' CHECK (status IN ('claimed', 'sent', 'failed', 'skipped')),
    attempts INTEGER NOT NULL DEFAULT 1,
    provider_id TEXT,
    error TEXT,
    run_id TEXT,
    meta TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    sent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_email_sends_user_tpl ON email_sends(user_id, template);
CREATE INDEX IF NOT EXISTS idx_email_sends_created ON email_sends(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_sends_provider ON email_sends(provider_id);
-- Per-user email state. Unsubscribe is set by the one-click link; suppression by Resend webhooks
-- (bounce, complaint). marketing_consent_at is the opt-in for product news, never pre-checked.
ALTER TABLE users ADD COLUMN email_unsubscribed_at TEXT;
ALTER TABLE users ADD COLUMN email_suppressed_at TEXT;
ALTER TABLE users ADD COLUMN email_suppressed_reason TEXT;
ALTER TABLE users ADD COLUMN marketing_consent_at TEXT;
-- Kill switches, both OFF: deploying this changes nothing until the founder flips them.
INSERT OR IGNORE INTO feature_flags (key, name, description, enabled) VALUES
  ('lifecycle_emails', 'Lifecycle emails', 'Kill switch for onboarding, milestone and re-engagement emails (welcome, first score, drip). Real sends are refused while off.', 0),
  ('feedback_ack_emails', 'Feedback acknowledgment emails', 'Kill switch for the instant acknowledgment sent when a user submits feedback, and the founder notification.', 0);
