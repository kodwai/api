-- GitHub OAuth: add github_id and avatar_url to users

ALTER TABLE users ADD COLUMN github_id TEXT;
ALTER TABLE users ADD COLUMN avatar_url TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github_id ON users(github_id) WHERE github_id IS NOT NULL;
