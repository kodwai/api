-- Efficiency: economy of agent steering (turns/tokens) + a rating — gamification v2
ALTER TABLE developer_profiles ADD COLUMN efficiency_rating INTEGER NOT NULL DEFAULT 1000;
ALTER TABLE submissions ADD COLUMN turns INTEGER;
ALTER TABLE submissions ADD COLUMN total_tokens INTEGER;
