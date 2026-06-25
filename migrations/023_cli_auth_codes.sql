-- CLI auth codes: short-lived single-use codes for the CLI browser (loopback) login flow.
-- The web app mints a code for the logged-in user; the CLI exchanges it for an access token.

CREATE TABLE IF NOT EXISTS cli_auth_codes (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cli_auth_code ON cli_auth_codes(code);
CREATE INDEX IF NOT EXISTS idx_cli_auth_user ON cli_auth_codes(user_id);
