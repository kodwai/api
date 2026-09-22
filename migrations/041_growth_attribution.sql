-- 041_growth_attribution.sql
-- Self-reported acquisition source (the /dev/welcome "how did you hear about us" field) and
-- an opt-in search indexing flag for public profiles. Nullable or constant defaults only.
-- Comments live on their own lines: the runner drops comment-only lines.
ALTER TABLE developer_profiles ADD COLUMN acquisition_source TEXT;
ALTER TABLE developer_profiles ADD COLUMN acquisition_prompt TEXT;
ALTER TABLE developer_profiles ADD COLUMN search_indexable INTEGER NOT NULL DEFAULT 0;
-- Demo accounts (seeded leaderboard users) are excluded from lifecycle email and growth stats.
ALTER TABLE users ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0;
UPDATE users SET is_demo = 1 WHERE lower(email) LIKE '%@demo.kodwai.dev';
