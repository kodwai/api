-- Make free-credit consumption permanent.
-- Previously free credits used = COUNT(submissions WHERE key_source='platform').
-- That let a developer refund a credit by deleting a platform-scored submission,
-- so they could submit -> score -> delete -> repeat forever on the platform key.
-- A monotonic counter that deletion never touches closes that loophole.
ALTER TABLE developer_profiles ADD COLUMN free_submissions_used INTEGER NOT NULL DEFAULT 0;

-- Backfill from historical platform-scored submissions so existing developers
-- keep the credits they have already spent.
UPDATE developer_profiles SET free_submissions_used = (
    SELECT COUNT(*) FROM submissions s
    WHERE s.user_id = developer_profiles.user_id AND s.key_source = 'platform'
);
