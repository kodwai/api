-- 039_feedback_replies.sql
-- Emailed replies to in-app feedback. No new "replied" status: the platform_feedback CHECK
-- constraint would need a table rebuild, so reply_emailed_at plus resolved/reviewed carries it.
-- Comments live on their own lines: the runner drops comment-only lines.
ALTER TABLE platform_feedback ADD COLUMN reply_emailed_at TEXT;
ALTER TABLE platform_feedback ADD COLUMN reply_email_send_id TEXT;
-- challenge_feedback had no admin response columns; mirror platform_feedback.
ALTER TABLE challenge_feedback ADD COLUMN admin_response TEXT;
ALTER TABLE challenge_feedback ADD COLUMN admin_responded_by TEXT;
ALTER TABLE challenge_feedback ADD COLUMN admin_responded_at TEXT;
ALTER TABLE challenge_feedback ADD COLUMN reply_emailed_at TEXT;
ALTER TABLE challenge_feedback ADD COLUMN reply_email_send_id TEXT;
