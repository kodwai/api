-- Scoring v2 (Lift): static AI baseline per challenge + per-submission scoring version.
-- ai_baseline is on a 0-100 scale (normalized artifact score), matching the badge delta computation in engine._assemble.
ALTER TABLE challenges ADD COLUMN ai_baseline REAL;
ALTER TABLE submissions ADD COLUMN scoring_version INTEGER NOT NULL DEFAULT 1;
