-- 040_automation_tokens.sql
-- Scoped bearer tokens (kdw_at_...) for the daily growth routine. Only the sha256 hash is stored;
-- the plaintext is shown once at mint time. scopes is a JSON array of scope strings.
-- owner_user_id is the superadmin who minted it, so admin_audit_log rows keep a real admin id.
-- Comments live on their own lines: the runner drops comment-only lines.
CREATE TABLE IF NOT EXISTS automation_tokens (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    token_prefix TEXT NOT NULL,
    scopes TEXT NOT NULL DEFAULT '[]',
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT,
    revoked_at TEXT,
    last_used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_automation_tokens_owner ON automation_tokens(owner_user_id);
