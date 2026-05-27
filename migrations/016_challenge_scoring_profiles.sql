-- Migration 016: Assign Scoring v2 scoring_config (profile + traps) to curated core challenges.
-- Profiles chosen by product decision (KOD-70).  Traps are authored from each challenge''s
-- actual problem statement to surface subtle, easy-to-miss requirements.
-- UPDATEs are naturally idempotent: re-running this migration is safe.

-- ============================================================
-- debugging profile
-- ============================================================

UPDATE challenges
SET scoring_config = '{"profile":"debugging","traps":[{"id":"bearer-extraction","description":"Middleware must strip the ''Bearer '' prefix before passing the raw token to jwt.verify — passing the full header string causes silent verification failures."},{"id":"logout-invalidation","description":"Logout must add the token to a denylist or clear it server-side; simply returning 200 without tracking used tokens leaves the route unprotected."},{"id":"expiry-check","description":"Token verification must explicitly check the exp claim; jwt libraries with permissive configs may accept expired tokens without throwing."}]}'
WHERE slug = 'debug-auth-flow';

UPDATE challenges
SET scoring_config = '{"profile":"debugging","traps":[{"id":"n-plus-one-items","description":"Order items must be fetched in a single batched query (WHERE order_id IN (...)), not inside a per-order loop — the loop pattern is the primary cause of the 8-second response time."},{"id":"parallel-async","description":"User profile, orders, and static config fetches are independent and must be launched with Promise.all / asyncio.gather rather than awaited sequentially."},{"id":"select-star","description":"Fetching all columns when only 3 are needed bloats the payload; the fix must use explicit column lists in the SELECT, not just add a cache layer on top of the oversized query."}]}'
WHERE slug = 'performance-bottleneck';

-- ============================================================
-- architecture profile
-- ============================================================

UPDATE challenges
SET scoring_config = '{"profile":"architecture","traps":[{"id":"hook-colocation","description":"Data-fetching logic must live in a dedicated custom hook (e.g. useUserProfile) rather than directly in the component body — a flat component that merely splits JSX into subfunctions does not satisfy the requirement."},{"id":"shared-state-boundary","description":"The avatar upload and form editing sub-components share mutation state; that state must be lifted to a common ancestor or managed via a shared hook, not duplicated or passed through multiple layers of props."},{"id":"error-boundary-scope","description":"TypeScript types must cover all async states including loading and error; using ''any'' or omitting the error type on fetch hooks is a silent spec violation."}]}'
WHERE slug = 'react-component-refactor';

UPDATE challenges
SET scoring_config = '{"profile":"architecture","traps":[{"id":"optimistic-concurrency","description":"store.append must reject when the caller''s expectedVersion does not match the stream''s current version — omitting this check allows lost-update races even in a single-threaded runtime."},{"id":"global-position-monotonic","description":"Each event''s global position must be strictly monotonically increasing across all streams, not just within a single stream; projections that read getAllEvents depend on this invariant."},{"id":"snapshot-replay-boundary","description":"loadAggregate must replay only events with version > snapshot.version — replaying from position 0 on every load defeats the purpose of snapshots and will time-out on long-lived aggregates."}]}'
WHERE slug = 'event-sourcing-store';

UPDATE challenges
SET scoring_config = '{"profile":"architecture","traps":[{"id":"content-addressable-dedup","description":"Identical file content committed in different directories must produce the same blob SHA and be stored only once — solutions that hash by file path rather than content will fail deduplication."},{"id":"lca-merge-base","description":"Three-way merge requires finding the true lowest common ancestor in the commit DAG; using the naive ''most recent shared commit'' heuristic breaks on criss-cross merges."},{"id":"detached-head-state","description":"kodgit checkout <sha> (non-branch) must set HEAD to the raw SHA, not a symbolic ref; subsequent commits in detached state should not advance any branch pointer."}]}'
WHERE slug = 'mini-git';

UPDATE challenges
SET scoring_config = '{"profile":"architecture","traps":[{"id":"signature-verification","description":"The receiver must verify the HMAC-SHA256 signature using the stored secret before processing the payload — implementations that generate signatures but never verify them on delivery failure retry paths are incomplete."},{"id":"replay-attack-window","description":"X-Webhook-Timestamp must be validated against a tolerance window (e.g. ±5 minutes); accepting timestamps from hours ago renders the replay-attack protection useless."},{"id":"delivery-log-per-attempt","description":"Each retry attempt must create a separate delivery log entry with its own status, response code, and timestamp — a single row updated in-place loses the attempt history required by GET /webhooks/:id/deliveries."}]}'
WHERE slug = 'webhook-delivery-system';

-- ============================================================
-- spec_heavy profile
-- ============================================================

UPDATE challenges
SET scoring_config = '{"profile":"spec_heavy","traps":[{"id":"post-returns-201","description":"POST /todos must return HTTP 201 Created, not 200 OK — a careless implementation that always returns 200 violates the explicit status-code requirement in the spec."},{"id":"completed-filter-query","description":"GET /todos?completed=true must filter by the boolean value, not the string ''true''; implementations that skip the query-string parsing return all todos regardless of the filter parameter."},{"id":"missing-title-400","description":"POST /todos without a title must return 400 Bad Request with a descriptive error body — silently creating a todo with a null or empty title violates the input validation requirement."}]}'
WHERE slug = 'build-rest-api';

UPDATE challenges
SET scoring_config = '{"profile":"spec_heavy","traps":[{"id":"expired-url-410","description":"Requests to an expired short URL must return 410 Gone, not 404 Not Found — the spec distinguishes between a URL that never existed (404) and one that existed but has expired (410)."},{"id":"redirect-301-not-302","description":"GET /:alias must respond with 301 Moved Permanently, not 302 Found — using a temporary redirect means browsers and crawlers will not cache the redirect and will hit the shortener on every visit."},{"id":"alias-collision-409","description":"Attempting to create a short URL with an alias that already exists must return 409 Conflict; silently overwriting the existing URL would corrupt click stats and break existing links."}]}'
WHERE slug = 'url-shortener';

UPDATE challenges
SET scoring_config = '{"profile":"spec_heavy","traps":[{"id":"jitter-on-backoff","description":"Retry delay must include jitter (delay += random(0, delay * 0.1)); implementations that use deterministic exponential backoff without jitter cause thundering-herd spikes when many jobs fail simultaneously."},{"id":"dead-letter-after-max-retries","description":"After all retries are exhausted the job must move to a dead-letter queue, not simply be dropped; the spec requires the dead-letter state to be observable via getStats()."},{"id":"timeout-rejects-promise","description":"A job that exceeds its timeout option must be rejected with a timeout error even if the underlying async function has not resolved — wrapping with Promise.race or AbortController is required."}]}'
WHERE slug = 'job-queue-retries';

UPDATE challenges
SET scoring_config = '{"profile":"spec_heavy","traps":[{"id":"aria-describedby-errors","description":"Each error message element must be linked to its input via aria-describedby, not just rendered nearby — screen readers will not announce the error unless the association is explicit in the DOM."},{"id":"focus-first-error-on-submit","description":"On submit with validation errors, focus must move programmatically to the first invalid field — a solution that shows errors but leaves focus on the submit button fails the keyboard-only operability requirement."},{"id":"loading-state-disables-all","description":"During submission, every form control including the submit button must be disabled, not just the button — leaving inputs enabled allows the user to mutate data while an async submit is in flight."}]}'
WHERE slug = 'accessible-form-builder';

-- ============================================================
-- balanced profile
-- ============================================================

UPDATE challenges
SET scoring_config = '{"profile":"balanced","traps":[{"id":"sliding-not-fixed-window","description":"The window must be a true sliding window based on per-request timestamps, not a fixed window that resets on a clock boundary — a fixed window allows a burst of 2x maxRequests at every window edge."},{"id":"memory-cleanup-expired","description":"Expired timestamp entries must be pruned from each client''s log on every call to isAllowed; solutions that only add entries will leak memory indefinitely under a large number of distinct clientIds."},{"id":"get-reset-time-accuracy","description":"getResetTime must return the milliseconds until the oldest timestamp in the current window falls outside the window, not the time until the next fixed-clock reset — the distinction matters when the window is partially consumed."}]}'
WHERE slug = 'algorithm-rate-limiter';

UPDATE challenges
SET scoring_config = '{"profile":"balanced","traps":[{"id":"has-no-recency-update","description":"has(key) must not update the entry''s position in the LRU order — a naive implementation that calls get() internally will promote entries that should remain candidates for eviction."},{"id":"lazy-plus-periodic-purge","description":"Expired entries must be removed both lazily on access AND via a periodic purge (purgeExpired); relying only on lazy removal means expired entries count toward maxSize until they happen to be accessed."},{"id":"set-existing-key-recency","description":"Calling set() on an existing key must move that key to the most-recently-used position before updating its value — implementations that insert a new node without removing the old one will corrupt the doubly-linked list order."}]}'
WHERE slug = 'lru-cache-ttl';
