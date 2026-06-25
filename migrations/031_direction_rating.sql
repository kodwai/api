-- AI-Direction Rating (ELO-style) — KOD-79
ALTER TABLE developer_profiles ADD COLUMN direction_rating INTEGER NOT NULL DEFAULT 1000;
