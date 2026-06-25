-- Admin platform: add superadmin/banned flags to users, create audit log table

ALTER TABLE users ADD COLUMN is_superadmin INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN is_banned INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN banned_reason TEXT;
ALTER TABLE users ADD COLUMN banned_at TEXT;

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    admin_user_id TEXT NOT NULL REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_log_admin ON admin_audit_log(admin_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON admin_audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON admin_audit_log(created_at DESC);
