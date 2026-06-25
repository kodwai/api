-- Migration 010: Third batch of challenges (23-37)
-- Fills gaps: refactoring, debugging, data, devops, system-design
-- Brings total from 22 to 37

PRAGMA foreign_keys = OFF;

INSERT OR IGNORE INTO challenges (id, created_by, title, slug, description, problem_statement_md, difficulty, category, tags, time_limit_minutes, test_suite, scoring_config, is_public, is_featured)
VALUES
-- ============================================================
-- Challenge 023: Easy / Debugging - Fix the Memory Leak
-- ============================================================
(
    'seed_challenge_023',
    'system',
    'Fix the Memory Leak',
    'fix-memory-leak',
    'A Node.js server is leaking memory and crashes after a few hours. Find the leaks, fix them, and prove it with metrics.',
    '# Fix the Memory Leak

## Objective
A production Node.js Express server is leaking memory. It starts at ~50MB RSS and climbs to 500MB+ within minutes under load. Find and fix all memory leaks.

## The Codebase
You receive a working Express app with 4 routes. Each route has at least one memory leak pattern:

1. **GET /api/users** - Fetches and caches user data
2. **POST /api/events** - Stores analytics events
3. **GET /api/reports/:id** - Generates PDF reports
4. **WS /live** - WebSocket endpoint for live updates

## Common Leak Patterns to Look For
- Event listeners not being removed
- Closures holding references to large objects
- Unbounded caches without eviction
- Streams not being properly closed
- Global arrays/maps that grow indefinitely
- Timer/interval references not cleared

## Requirements
1. Identify all memory leaks (there are 5)
2. Fix each leak without breaking functionality
3. Add a `/health` endpoint that reports current memory usage
4. Write a brief comment above each fix explaining the leak pattern
5. All existing tests must still pass

## Evaluation Criteria
- Number of leaks correctly identified and fixed
- Memory stability under simulated load
- Fix quality (clean, minimal changes)
- Explanations of each leak pattern',
    'easy',
    'debugging',
    '["debugging", "memory-leak", "node", "performance"]',
    45,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 024: Easy / Refactoring - Untangle the Spaghetti
-- ============================================================
(
    'seed_challenge_024',
    'system',
    'Untangle the Spaghetti',
    'untangle-spaghetti',
    'Refactor a 400-line "god function" that handles user registration, validation, email, and logging into clean, testable modules.',
    '# Untangle the Spaghetti

## Objective
You receive a single file `register.js` containing a 400-line function that does everything: input validation, password hashing, database insert, email sending, audit logging, and rate limiting. Refactor it into clean, testable modules.

## The Problem
```javascript
// register.js - 400 lines, 0 tests, 12 responsibilities
async function registerUser(req, res) {
  // ... validation, hashing, db, email, logging, rate limiting
  // all in one function with deeply nested if/else
}
```

## Requirements
1. Break the god function into **at least 5 focused modules**
2. Each module must have a **single responsibility**
3. Write **unit tests** for each module (at least 2 tests per module)
4. Maintain all existing behavior — the API contract must not change
5. Use dependency injection so modules are testable in isolation
6. Add proper error handling (the original swallows errors silently)

## Suggested Module Structure
```
src/
  validators/   - Input validation
  auth/         - Password hashing, token generation
  users/        - Database operations
  email/        - Email sending
  middleware/   - Rate limiting, logging
  register.js   - Orchestrator (thin, delegates to modules)
```

## Evaluation Criteria
- Module boundaries (clean separation of concerns)
- Test coverage and quality
- Error handling improvement
- Code readability
- Backward compatibility',
    'easy',
    'refactoring',
    '["refactoring", "clean-code", "testing", "architecture"]',
    50,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 025: Medium / Debugging - Race Condition Hunter
-- ============================================================
(
    'seed_challenge_025',
    'system',
    'Race Condition Hunter',
    'race-condition-hunter',
    'Find and fix 4 race conditions in a concurrent task processing system. Tests pass alone but fail when run together.',
    '# Race Condition Hunter

## Objective
A task processing system has 4 race conditions. Individual tests pass, but the full test suite fails intermittently. Find and fix all race conditions.

## The System
- A task queue that processes jobs concurrently
- A shared counter for job statistics
- A file-based lock system for exclusive operations
- A cache with read-modify-write operations

## Symptoms
- Job counter sometimes shows wrong totals
- Duplicate jobs occasionally get processed
- Cache values sometimes revert to stale data
- Lock files occasionally get orphaned

## Race Conditions to Find
1. **Check-then-act** on the job queue (two workers grab the same job)
2. **Read-modify-write** on the statistics counter (lost updates)
3. **Time-of-check-time-of-use** on file locks (gap between check and acquire)
4. **Stale closure** in async cache update (closure captures old value)

## Requirements
1. Identify and fix all 4 race conditions
2. Add a comment explaining each race condition and your fix
3. All tests must pass consistently (run 10 times with no failures)
4. Do not serialize everything — maintain concurrency where safe

## Constraints
- Do not add external locking libraries
- Use language-native concurrency primitives (mutexes, atomics, channels)
- Fixes must not significantly degrade throughput

## Evaluation Criteria
- All race conditions correctly identified
- Fix correctness (verified by repeated test runs)
- Concurrency preserved (not just "make everything serial")
- Explanation quality',
    'medium',
    'debugging',
    '["debugging", "concurrency", "race-condition", "async"]',
    60,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 026: Medium / Refactoring - Callback Hell to Async
-- ============================================================
(
    'seed_challenge_026',
    'system',
    'Callback Hell to Modern Async',
    'callback-hell-async',
    'Refactor a deeply nested callback-based Node.js module into clean async/await code with proper error handling and tests.',
    '# Callback Hell to Modern Async

## Objective
You receive a file `data-pipeline.js` with 6 levels of nested callbacks that processes data through multiple stages: fetch, validate, transform, enrich, save, and notify. Refactor to modern async/await.

## The Problem
```javascript
function processData(id, callback) {
  fetchData(id, (err, raw) => {
    if (err) return callback(err);
    validateData(raw, (err, valid) => {
      if (err) return callback(err);
      transformData(valid, (err, transformed) => {
        if (err) return callback(err);
        enrichData(transformed, (err, enriched) => {
          if (err) return callback(err);
          saveData(enriched, (err, saved) => {
            if (err) return callback(err);
            notifyComplete(saved, (err) => {
              if (err) return callback(err);
              callback(null, saved);
            });
          });
        });
      });
    });
  });
}
```

## Requirements
1. Convert all callback-based functions to return Promises / use async/await
2. Implement proper error handling with **typed errors** (ValidationError, TransformError, etc.)
3. Add **retry logic** for the fetch and save stages (3 attempts with backoff)
4. Add **timeout** support (abort if any stage exceeds 10 seconds)
5. Make the pipeline **cancellable** via AbortController
6. Write tests for happy path, each error type, retry behavior, and cancellation
7. The external API contract must remain the same (still accepts a callback OR returns a Promise)

## Evaluation Criteria
- Async/await correctness
- Error handling (typed errors, proper propagation)
- Retry and timeout implementation
- Test quality and coverage
- Backward compatibility',
    'medium',
    'refactoring',
    '["refactoring", "async", "node", "error-handling"]',
    60,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 027: Medium / Data - CSV to API Pipeline
-- ============================================================
(
    'seed_challenge_027',
    'system',
    'CSV to API Data Pipeline',
    'csv-api-pipeline',
    'Build a data pipeline that reads a large CSV, validates and transforms rows, and bulk-inserts via a REST API with rate limiting and error recovery.',
    '# CSV to API Data Pipeline

## Objective
Build a robust data pipeline that processes a 100K-row CSV file and imports it into a system via REST API calls.

## Requirements

### Pipeline Stages
1. **Read**: Stream the CSV file (don''t load entire file into memory)
2. **Validate**: Check each row against a schema:
   - `email`: valid email format, required
   - `name`: non-empty string, required
   - `age`: integer 0-150, optional
   - `country`: ISO 3166-1 alpha-2 code, optional
3. **Transform**: Normalize data:
   - Trim whitespace, lowercase emails
   - Parse dates to ISO format
   - Map country names to codes
4. **Batch**: Group into batches of 100 rows
5. **Upload**: POST each batch to `http://localhost:3000/api/import`
6. **Report**: Generate a summary at the end

### Resilience Requirements
- Rate limiting: max 10 API calls per second
- Retry failed batches up to 3 times with exponential backoff
- Dead-letter queue: save permanently failed rows to `errors.csv`
- Resume support: if interrupted, resume from where it left off (use a checkpoint file)

### Output Report
```
Pipeline Complete
─────────────────
Total rows:     100,000
Processed:       98,450
Skipped (invalid): 1,230
Failed (API):        320
Duration:         4m 32s
Throughput:      362 rows/sec
```

## Constraints
- Must stream the CSV (memory usage under 100MB for any file size)
- Use any language
- Include a mock API server for testing

## Evaluation Criteria
- Streaming implementation
- Error handling and recovery
- Rate limiting correctness
- Resume/checkpoint logic
- Report quality',
    'medium',
    'data',
    '["data-pipeline", "csv", "api", "streaming"]',
    75,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 028: Hard / DevOps - CI/CD Pipeline from Scratch
-- ============================================================
(
    'seed_challenge_028',
    'system',
    'CI/CD Pipeline from Scratch',
    'cicd-pipeline-scratch',
    'Design a complete CI/CD pipeline with GitHub Actions: lint, test, build, deploy to staging, smoke test, promote to production.',
    '# CI/CD Pipeline from Scratch

## Objective
Create a complete CI/CD pipeline for a Node.js API using GitHub Actions.

## The Application
A simple Express API with:
- TypeScript source code
- Jest test suite (unit + integration)
- Docker containerization
- PostgreSQL dependency

## Pipeline Requirements

### On Pull Request
1. **Lint**: ESLint + Prettier check
2. **Type Check**: `tsc --noEmit`
3. **Unit Tests**: Jest unit tests
4. **Integration Tests**: Jest with test database
5. **Build**: Docker image build (verify it compiles)
6. **Security**: npm audit + Trivy container scan
7. **Comment**: Post test coverage on the PR

### On Merge to Main
1. All PR checks above
2. **Build & Push**: Docker image to registry with git SHA tag
3. **Deploy to Staging**: Update staging environment
4. **Smoke Tests**: Hit health endpoint + critical paths
5. **Notify**: Slack notification with deploy status

### On Release Tag
1. All above
2. **Deploy to Production**: Blue-green deployment
3. **Smoke Tests**: Production health checks
4. **Rollback**: Auto-rollback if smoke tests fail
5. **Changelog**: Auto-generate from commits

### Pipeline Config
- Secrets management via GitHub Secrets
- Environment-specific variables
- Concurrency control (cancel superseded runs)
- Caching (node_modules, Docker layers)

## Deliverables
- `.github/workflows/pr.yml`
- `.github/workflows/deploy.yml`
- `.github/workflows/release.yml`
- `Dockerfile` (multi-stage)
- `docker-compose.test.yml` (for integration tests)
- `scripts/smoke-test.sh`
- Brief README explaining the pipeline

## Evaluation Criteria
- Pipeline completeness
- Security practices
- Caching strategy
- Rollback mechanism
- Documentation',
    'hard',
    'devops',
    '["cicd", "github-actions", "docker", "devops"]',
    90,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 029: Easy / Data - JSON Schema Validator
-- ============================================================
(
    'seed_challenge_029',
    'system',
    'JSON Schema Validator',
    'json-schema-validator',
    'Build a JSON Schema validator from scratch that supports type checking, required fields, nested objects, arrays, and custom error messages.',
    '# JSON Schema Validator

## Objective
Implement a JSON Schema validator (subset of JSON Schema Draft 7) from scratch.

## Supported Keywords
1. **type**: `"string"`, `"number"`, `"integer"`, `"boolean"`, `"object"`, `"array"`, `"null"`
2. **required**: array of required property names
3. **properties**: schema for each object property
4. **items**: schema for array elements
5. **minLength** / **maxLength**: string length constraints
6. **minimum** / **maximum**: number range constraints
7. **minItems** / **maxItems**: array length constraints
8. **enum**: allowed values
9. **pattern**: regex pattern for strings
10. **additionalProperties**: `true`/`false`/schema

## API
```javascript
const validator = new SchemaValidator(schema);
const result = validator.validate(data);
// result: { valid: true } or { valid: false, errors: [...] }
```

## Error Format
```json
{
  "valid": false,
  "errors": [
    { "path": "$.user.email", "message": "Expected type string, got number" },
    { "path": "$.user.age", "message": "Value 200 exceeds maximum of 150" },
    { "path": "$.tags[2]", "message": "Expected type string, got boolean" }
  ]
}
```

## Requirements
- Validate nested objects and arrays recursively
- Return ALL errors (don''t stop at the first one)
- Error paths use JSONPath notation (`$.foo.bar[0].baz`)
- Write at least 20 test cases

## Evaluation Criteria
- Keyword coverage
- Nested validation correctness
- Error message clarity
- Test comprehensiveness',
    'easy',
    'data',
    '["json", "validation", "schema", "parsing"]',
    50,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 030: Medium / System Design - Pub/Sub Message Broker
-- ============================================================
(
    'seed_challenge_030',
    'system',
    'Pub/Sub Message Broker',
    'pubsub-message-broker',
    'Build an in-memory publish/subscribe message broker with topics, subscriptions, message persistence, and dead-letter queues.',
    '# Pub/Sub Message Broker

## Objective
Build a lightweight publish/subscribe message broker.

## Core API
```javascript
const broker = new MessageBroker();

// Create a topic
broker.createTopic("orders");

// Subscribe with options
const sub = broker.subscribe("orders", {
  name: "email-service",
  filter: (msg) => msg.data.total > 100,
  maxRetries: 3,
  ackTimeout: 5000,
});

// Publish a message
broker.publish("orders", {
  type: "order.created",
  data: { orderId: "123", total: 250 },
});

// Consume messages
sub.on("message", async (msg) => {
  await processOrder(msg.data);
  msg.ack(); // Acknowledge
});
```

## Requirements

### Topics
- Create, delete, list topics
- Message ordering guaranteed within a topic

### Subscriptions
- Multiple subscribers per topic (fan-out)
- Message filtering (optional predicate function)
- At-least-once delivery

### Message Lifecycle
1. Published → Pending (in subscriber queue)
2. Delivered → Awaiting Ack
3. Acked → Removed from queue
4. Nacked or Timeout → Retry (with backoff)
5. Max retries exceeded → Dead Letter Queue

### Dead Letter Queue
- Each subscription has an associated DLQ
- Messages in DLQ can be inspected and replayed
- `sub.deadLetterQueue.replay()` re-publishes all DLQ messages

### Observability
- `broker.getStats()` returns: messages published, delivered, acked, nacked, in DLQ per topic

## Evaluation Criteria
- Message delivery guarantees
- Retry and DLQ implementation
- Fan-out correctness
- API design clarity',
    'medium',
    'system-design',
    '["pubsub", "messaging", "system-design", "async"]',
    75,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 031: Hard / Fullstack - OAuth2 Provider
-- ============================================================
(
    'seed_challenge_031',
    'system',
    'OAuth2 Authorization Server',
    'oauth2-auth-server',
    'Implement an OAuth2 authorization server supporting authorization code flow, PKCE, token refresh, and scope management.',
    '# OAuth2 Authorization Server

## Objective
Build a working OAuth2 authorization server that implements the Authorization Code flow with PKCE.

## Requirements

### Client Registration
- `POST /oauth/clients` - Register a new OAuth client
- Returns `client_id` and `client_secret`
- Store allowed redirect URIs and scopes

### Authorization Endpoint
- `GET /oauth/authorize` - Show consent screen
  - Query params: `client_id`, `redirect_uri`, `response_type=code`, `scope`, `state`, `code_challenge`, `code_challenge_method`
- Validate client, scopes, and redirect URI
- Show a login/consent page
- On approval, redirect with `code` and `state`

### Token Endpoint
- `POST /oauth/token` - Exchange code for tokens
  - Grant types: `authorization_code`, `refresh_token`
  - Validate `code_verifier` for PKCE
  - Return `access_token`, `refresh_token`, `expires_in`, `scope`

### Token Introspection
- `POST /oauth/introspect` - Validate a token
- Returns `active`, `scope`, `client_id`, `exp`

### Token Revocation
- `POST /oauth/revoke` - Revoke access or refresh token

### Resource Server
- `GET /api/me` - Protected endpoint, requires valid access token
- `GET /api/data` - Requires `read:data` scope

## Security Requirements
- Authorization codes expire in 60 seconds, single-use
- PKCE required (S256 challenge method)
- Tokens are signed JWTs
- Refresh tokens are opaque, stored server-side
- Rate limiting on token endpoint

## Evaluation Criteria
- OAuth2 spec compliance
- PKCE implementation
- Security (token handling, CSRF protection)
- Error handling (proper OAuth error responses)
- Code organization',
    'hard',
    'fullstack',
    '["oauth2", "security", "auth", "jwt"]',
    90,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 032: Easy / Frontend - Infinite Scroll Feed
-- ============================================================
(
    'seed_challenge_032',
    'system',
    'Infinite Scroll Feed',
    'infinite-scroll-feed',
    'Build an infinite-scrolling content feed with virtualized rendering, loading skeletons, and error recovery.',
    '# Infinite Scroll Feed

## Objective
Build a social media-style infinite scroll feed that loads content as the user scrolls down.

## Requirements
1. **Infinite scroll**: Automatically load more items when user scrolls near the bottom
2. **Intersection Observer**: Use IntersectionObserver API (not scroll events)
3. **Loading skeletons**: Show animated placeholder cards while loading
4. **Error handling**: Show retry button if a page fails to load
5. **Virtualization**: Only render items visible in the viewport (+ buffer)
6. **Pull to refresh**: Pull down at the top to reload the feed
7. **Scroll position restoration**: If user navigates away and back, restore scroll position

## Mock API
Create a mock API that:
- Returns 20 items per page
- Simulates 200ms network latency
- Randomly fails 10% of requests (for error handling testing)
- Returns items with: `id`, `author`, `avatar`, `content`, `image`, `likes`, `timestamp`

## Component API
```jsx
<Feed
  fetchPage={(page) => api.getPosts(page)}
  renderItem={(item) => <PostCard post={item} />}
  pageSize={20}
  threshold={0.8}
  skeleton={<PostSkeleton />}
/>
```

## Constraints
- React (TypeScript preferred)
- No infinite scroll libraries
- Must handle 10,000+ items without performance degradation

## Evaluation Criteria
- Scroll performance (no jank)
- Virtualization implementation
- Loading/error UX
- Memory efficiency',
    'easy',
    'frontend',
    '["react", "infinite-scroll", "virtualization", "performance"]',
    50,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 033: Medium / Backend - Task Scheduler with Cron
-- ============================================================
(
    'seed_challenge_033',
    'system',
    'Task Scheduler with Cron Expressions',
    'task-scheduler-cron',
    'Build a task scheduler that parses cron expressions, schedules recurring jobs, and handles overlapping executions.',
    '# Task Scheduler with Cron Expressions

## Objective
Build a cron-based task scheduler from scratch.

## Requirements

### Cron Parser
Parse standard 5-field cron expressions:
```
┌───────── minute (0-59)
│ ┌─────── hour (0-23)
│ │ ┌───── day of month (1-31)
│ │ │ ┌─── month (1-12)
│ │ │ │ ┌─ day of week (0-6, Sun=0)
│ │ │ │ │
* * * * *
```

Support: exact values, ranges (`1-5`), steps (`*/15`), lists (`1,3,5`), wildcards (`*`)

### Scheduler API
```javascript
const scheduler = new CronScheduler();

scheduler.addJob("cleanup", "0 */6 * * *", async () => {
  await cleanupOldFiles();
}, { timezone: "UTC", overlap: false });

scheduler.addJob("report", "30 9 * * 1-5", async () => {
  await generateDailyReport();
}, { timezone: "America/New_York", timeout: 30000 });

scheduler.start();
scheduler.stop();
scheduler.getNextRun("cleanup"); // Date
scheduler.getJobStatus("report"); // { running, lastRun, nextRun, ... }
```

### Features
- **Overlap prevention**: Option to skip execution if previous run is still active
- **Timeout**: Kill jobs that exceed their timeout
- **Error handling**: Configurable error callback, don''t crash the scheduler
- **Job history**: Store last 10 runs with status and duration
- **Timezone support**: Schedule in any timezone

## Evaluation Criteria
- Cron parsing correctness
- Next-run calculation accuracy
- Overlap and timeout handling
- API design',
    'medium',
    'backend',
    '["cron", "scheduler", "async", "backend"]',
    60,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 034: Hard / System Design - Distributed Key-Value Store
-- ============================================================
(
    'seed_challenge_034',
    'system',
    'Distributed Key-Value Store',
    'distributed-kv-store',
    'Build a distributed key-value store with consistent hashing, replication, vector clocks, and gossip protocol for node discovery.',
    '# Distributed Key-Value Store

## Objective
Build a distributed key-value store that runs on multiple nodes.

## Requirements

### Core API (per node)
```javascript
await node.put("user:123", { name: "Alice", email: "alice@test.com" });
const value = await node.get("user:123");
await node.delete("user:123");
```

### Distribution
- **Consistent hashing** to distribute keys across nodes
- **Virtual nodes** (150 per physical node) for even distribution
- **Replication factor N=3**: Each key is stored on N consecutive nodes in the ring

### Consistency
- **Read repair**: On read, if replicas disagree, resolve and repair
- **Vector clocks**: Track causality for conflict detection
- **Last-writer-wins** as default conflict resolution (configurable)
- **Quorum reads/writes**: Configurable W and R values (default W=2, R=2)

### Node Discovery
- **Gossip protocol**: Nodes periodically exchange membership info
- **Failure detection**: Mark nodes as suspect after missed heartbeats, dead after timeout
- **Node join/leave**: Automatic key redistribution

### API Server
- Each node exposes an HTTP API
- Requests to any node can read/write any key (node proxies to correct owner)

## Test Scenario
```
Start 3 nodes → Write 1000 keys → Kill 1 node →
Verify reads still succeed (degraded) →
Restart node → Verify data resyncs
```

## Evaluation Criteria
- Consistent hashing correctness
- Replication and quorum logic
- Failure handling (reads/writes during node failure)
- Vector clock implementation
- Code architecture',
    'hard',
    'system-design',
    '["distributed-systems", "consistent-hashing", "replication", "system-design"]',
    120,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 035: Medium / Frontend - Drag-and-Drop File Uploader
-- ============================================================
(
    'seed_challenge_035',
    'system',
    'Drag-and-Drop File Uploader',
    'drag-drop-uploader',
    'Build a file upload component with drag-and-drop, progress bars, preview thumbnails, chunked upload, and pause/resume.',
    '# Drag-and-Drop File Uploader

## Objective
Build a production-quality file upload component.

## Requirements
1. **Drag and drop zone** with visual feedback (hover state, valid/invalid file indicator)
2. **Click to browse** as alternative to drag-and-drop
3. **File validation**: Max size (10MB), allowed types (images + PDF), max count (5)
4. **Preview thumbnails** for images, icon for PDFs
5. **Upload progress** bar per file (0-100%)
6. **Chunked upload**: Split large files into 1MB chunks, upload sequentially
7. **Pause/Resume**: Ability to pause and resume an in-progress upload
8. **Cancel**: Remove a file from the queue before or during upload
9. **Retry**: Retry failed uploads
10. **Accessibility**: Keyboard operable, screen reader announcements for upload status

## Component API
```jsx
<FileUploader
  accept={["image/*", "application/pdf"]}
  maxSize={10 * 1024 * 1024}
  maxFiles={5}
  chunkSize={1024 * 1024}
  endpoint="/api/upload"
  onComplete={(files) => console.log(files)}
  onError={(file, error) => console.error(error)}
/>
```

## Mock Server
Create a mock upload server that:
- Accepts chunked uploads
- Returns progress acknowledgment per chunk
- Simulates 5% failure rate on chunks

## Evaluation Criteria
- Drag-and-drop UX quality
- Chunked upload correctness
- Pause/resume implementation
- Error recovery
- Accessibility',
    'medium',
    'frontend',
    '["react", "file-upload", "drag-and-drop", "chunked-upload"]',
    75,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 036: Easy / Backend - Rate Limiter Middleware
-- ============================================================
(
    'seed_challenge_036',
    'system',
    'Rate Limiter Middleware',
    'rate-limiter-middleware',
    'Build an Express middleware for rate limiting with sliding window, token bucket, and fixed window strategies — all configurable.',
    '# Rate Limiter Middleware

## Objective
Build a configurable rate limiting middleware for Express.

## Requirements

### Three Strategies
1. **Fixed Window**: Count requests per time window, reset at window boundary
2. **Sliding Window**: Count requests in a rolling time window
3. **Token Bucket**: Refill tokens at a fixed rate, each request consumes one

### Middleware API
```javascript
const limiter = rateLimit({
  strategy: "sliding-window",
  windowMs: 60 * 1000,    // 1 minute
  maxRequests: 100,
  keyGenerator: (req) => req.ip,
  onLimitReached: (req, res) => {
    res.status(429).json({
      error: "Too Many Requests",
      retryAfter: limiter.getRetryAfter(req),
    });
  },
  skipIf: (req) => req.path === "/health",
  headers: true, // Add X-RateLimit-* headers
});

app.use("/api", limiter);
```

### Response Headers
- `X-RateLimit-Limit`: max requests
- `X-RateLimit-Remaining`: requests remaining
- `X-RateLimit-Reset`: seconds until window resets
- `Retry-After`: seconds until next allowed request (on 429)

### Features
- Per-route limits: different limits for different endpoints
- Custom key: rate limit by IP, user ID, API key, etc.
- Skip conditions: whitelist certain paths or users
- In-memory store (default) with interface for external stores

## Constraints
- Pure Node.js + Express
- No rate limiting libraries
- Write tests for each strategy

## Evaluation Criteria
- Strategy correctness (especially sliding window edge cases)
- Header compliance
- Configuration flexibility
- Test quality',
    'easy',
    'backend',
    '["rate-limiting", "middleware", "express", "backend"]',
    45,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 037: Medium / Fullstack - URL Bookmark Manager
-- ============================================================
(
    'seed_challenge_037',
    'system',
    'URL Bookmark Manager',
    'bookmark-manager',
    'Build a full-stack bookmark manager with auto-fetched metadata, tagging, full-text search, and import/export.',
    '# URL Bookmark Manager

## Objective
Build a personal bookmark manager that automatically enriches saved URLs with metadata.

## Requirements

### Backend API
1. `POST /bookmarks` - Save a URL
   - Auto-fetch: title, description, favicon, Open Graph image from the URL
   - Return enriched bookmark object
2. `GET /bookmarks` - List with filtering, sorting, search
3. `PUT /bookmarks/:id` - Edit tags, notes, title
4. `DELETE /bookmarks/:id` - Remove bookmark
5. `POST /bookmarks/import` - Import from browser HTML export
6. `GET /bookmarks/export` - Export as HTML (Netscape format) or JSON

### Frontend
1. **Add bookmark**: Paste URL → auto-populates title, description, image
2. **Card grid**: Show bookmarks as cards with favicon, title, description, image
3. **Tags**: Add/remove tags, filter by tag
4. **Search**: Full-text search across title, description, URL, tags
5. **Keyboard shortcuts**: Cmd+K (search), Cmd+N (new bookmark)

### Auto-Enrichment
When a URL is saved:
- Fetch the page HTML
- Extract: `<title>`, `meta[description]`, `og:image`, `og:title`, favicon
- Fall back gracefully if any field is missing

### Data Model
```
Bookmark: { id, url, title, description, image, favicon, tags[], notes, created_at }
```

## Constraints
- Any stack (Node + React recommended)
- In-memory storage
- Must handle URLs that are slow or return errors

## Evaluation Criteria
- Auto-enrichment quality
- Search implementation
- Import/export correctness
- UI polish',
    'medium',
    'fullstack',
    '["fullstack", "bookmarks", "metadata", "search"]',
    90,
    NULL,
    '{}',
    1,
    0
);

PRAGMA foreign_keys = ON;
