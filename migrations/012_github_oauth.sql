-- GitHub OAuth: add github_id and avatar_url to users, make password_hash nullable for OAuth users

ALTER TABLE users ADD COLUMN github_id TEXT UNIQUE;
ALTER TABLE users ADD COLUMN avatar_url TEXT;
