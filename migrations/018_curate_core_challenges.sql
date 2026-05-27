-- Migration 018: Curate to core 12 public challenges, draft the rest
-- Reversible: only flips is_public; does not delete any challenges.
-- To revert: UPDATE challenges SET is_public = 1 WHERE slug NOT IN (...core list...)

UPDATE challenges
SET is_public = 0
WHERE slug NOT IN (
  'build-rest-api',
  'url-shortener',
  'debug-auth-flow',
  'accessible-form-builder',
  'react-component-refactor',
  'job-queue-retries',
  'webhook-delivery-system',
  'performance-bottleneck',
  'algorithm-rate-limiter',
  'lru-cache-ttl',
  'event-sourcing-store',
  'mini-git'
);
