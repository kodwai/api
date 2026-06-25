-- Enforce "one challenge in progress per developer" at the database level so the
-- check-then-insert in start_challenge can't be raced into two in_progress rows.

-- First resolve any pre-existing duplicates (the old code allowed several): keep
-- the newest in_progress per user (tie-break by id), demote the rest to 'error'
-- so the partial unique index below can be created.
UPDATE submissions SET status = 'error', updated_at = datetime('now')
WHERE status = 'in_progress' AND EXISTS (
    SELECT 1 FROM submissions other
    WHERE other.user_id = submissions.user_id
      AND other.status = 'in_progress'
      AND (other.created_at > submissions.created_at
           OR (other.created_at = submissions.created_at AND other.id > submissions.id))
);

-- At most one in_progress submission per user. A submission leaves this partial
-- index once it is submitted/scored/stopped, freeing the slot.
CREATE UNIQUE INDEX IF NOT EXISTS idx_submissions_one_active
    ON submissions(user_id) WHERE status = 'in_progress';
