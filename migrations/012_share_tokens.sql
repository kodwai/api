-- Migration 012: Add share_token to submissions for public sharing

ALTER TABLE submissions ADD COLUMN share_token TEXT UNIQUE;

CREATE INDEX IF NOT EXISTS idx_submissions_share_token ON submissions(share_token);
