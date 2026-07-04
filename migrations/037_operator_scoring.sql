-- 037_operator_scoring.sql
-- Additive, non-breaking wiring for the operator scoring core (SCORING_DESIGN section 11.1).
-- Every statement is idempotent; the migration runner swallows duplicate-column/already-exists errors.
-- Comments live on their own lines: the runner drops comment-only lines and rejects inline comments in column defs.
-- Item bank: per-challenge IRT calibration (a, b, s) + Layer-E baseline stats.
CREATE TABLE IF NOT EXISTS operator_item_params (
    challenge_id TEXT PRIMARY KEY REFERENCES challenges(id) ON DELETE CASCADE,
    a REAL,
    b REAL,
    s REAL,
    mu_baseline REAL,
    sigma_baseline REAL,
    baseline_m INTEGER DEFAULT 20,
    ceiling REAL,
    sigma_intrinsic REAL,
    discrimination_vec TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
-- Layer-G predictive calibration store (learned gamma weights + output calibration).
CREATE TABLE IF NOT EXISTS operator_calibration (
    key TEXT PRIMARY KEY,
    gamma0 REAL,
    gamma1 REAL,
    gamma2 REAL,
    gamma3 REAL,
    sigma_reg REAL,
    calibration_method TEXT,
    calibration_params TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
-- Per-developer ability estimate (Layer D theta_hat +/- SE); all nullable.
ALTER TABLE developer_profiles ADD COLUMN ability_theta REAL;
ALTER TABLE developer_profiles ADD COLUMN ability_se REAL;
ALTER TABLE developer_profiles ADD COLUMN ability_updated_at TEXT;
-- Full-precision Layer-E outputs per submission (used to re-fit ability); nullable.
ALTER TABLE submissions ADD COLUMN operator_l REAL;
ALTER TABLE submissions ADD COLUMN operator_s REAL;
