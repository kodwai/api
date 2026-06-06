-- Capture which AI model drove a submission (KOD-63)
ALTER TABLE submissions ADD COLUMN model TEXT;
ALTER TABLE submissions ADD COLUMN model_display TEXT;
ALTER TABLE submissions ADD COLUMN model_provider TEXT;
ALTER TABLE leaderboard_entries ADD COLUMN model TEXT;
