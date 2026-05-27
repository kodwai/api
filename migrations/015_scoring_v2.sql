-- Scoring v2 (Lift): static AI baseline per challenge + per-submission scoring version.
ALTER TABLE challenges ADD COLUMN ai_baseline REAL;
ALTER TABLE submissions ADD COLUMN scoring_version INTEGER NOT NULL DEFAULT 1;
