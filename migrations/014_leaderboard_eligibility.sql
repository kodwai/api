-- Leaderboard eligibility
--
-- A scored submission only counts toward leaderboards when its score includes the
-- AI/analytical phase. That phase runs only when the developer has added their own
-- Claude API key. Without a key, the submission is rated with non-AI (objective)
-- scoring alone, which is not comparable to AI-scored submissions, so it must be
-- hidden from every leaderboard.

ALTER TABLE submissions ADD COLUMN leaderboard_eligible INTEGER NOT NULL DEFAULT 1;

-- Backfill: mark already-scored submissions that were rated without the AI phase.
UPDATE submissions
SET leaderboard_eligible = 0
WHERE status = 'scored'
  AND json_extract(score_breakdown, '$.analytical_skipped') = 1;

CREATE INDEX IF NOT EXISTS idx_submissions_eligible ON submissions(leaderboard_eligible);

-- Drop per-challenge leaderboard entries that came from ineligible submissions.
DELETE FROM leaderboard_entries
WHERE submission_id IN (SELECT id FROM submissions WHERE leaderboard_eligible = 0);

-- Recompute weighted total_score from eligible submissions only.
UPDATE developer_profiles
SET total_score = COALESCE((
    SELECT SUM(best.weighted) / SUM(best.weight)
    FROM (
        SELECT MAX(s.score) * (CASE c.difficulty WHEN 'easy' THEN 1.0 WHEN 'medium' THEN 1.5 WHEN 'hard' THEN 2.0 ELSE 1.0 END) AS weighted,
               CASE c.difficulty WHEN 'easy' THEN 1.0 WHEN 'medium' THEN 1.5 WHEN 'hard' THEN 2.0 ELSE 1.0 END AS weight
        FROM submissions s
        JOIN challenges c ON s.challenge_id = c.id
        WHERE s.user_id = developer_profiles.user_id
          AND s.status = 'scored'
          AND s.leaderboard_eligible = 1
          AND s.score IS NOT NULL
        GROUP BY s.challenge_id
    ) best
), 0);

-- Recompute global ranks; only developers with an eligible submission are ranked,
-- everyone else has their rank cleared (the correlated subquery yields NULL).
UPDATE developer_profiles
SET rank = (
    SELECT ranked.rnk
    FROM (
        SELECT user_id, ROW_NUMBER() OVER (ORDER BY total_score DESC) AS rnk
        FROM developer_profiles
        WHERE user_id IN (
            SELECT DISTINCT user_id FROM submissions
            WHERE status = 'scored' AND leaderboard_eligible = 1
        )
    ) ranked
    WHERE ranked.user_id = developer_profiles.user_id
);
