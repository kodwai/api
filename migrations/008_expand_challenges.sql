-- Migration 008: Expand challenge library with 5 new challenges
-- Categories covered: backend, frontend, fullstack, devops, algorithms
-- Difficulty spread: 2 easy, 2 medium, 1 hard

PRAGMA foreign_keys = OFF;

INSERT OR IGNORE INTO challenges (id, created_by, title, slug, description, problem_statement_md, difficulty, category, tags, time_limit_minutes, test_suite, scoring_config, is_public, is_featured)
VALUES
-- ============================================================
-- Challenge 008: Easy / Backend - Environment Config Parser
-- ============================================================
(
    'seed_challenge_008',
    'system',
    'Environment Config Parser',
    'env-config-parser',
    'Build a library that parses .env files with support for variable interpolation, comments, and type casting.',
    '# Environment Config Parser

## Objective
Build a robust `.env` file parser that goes beyond simple key=value pairs.

## Requirements
1. **Basic parsing**: Read a `.env` file and return an object of key-value pairs
2. **Comments**: Lines starting with `#` should be ignored
3. **Quoted values**: Support single and double quoted values (`KEY="hello world"`)
4. **Variable interpolation**: `API_URL=https://$HOST:$PORT/api` should resolve `$HOST` and `$PORT`
5. **Type casting**: Provide a `typed()` method that converts:
   - `"true"` / `"false"` → boolean
   - Numeric strings → number
   - `"null"` → null
6. **Multiline values**: Support values wrapped in triple quotes (`"""..."""`)
7. **Default values**: Support `${VAR:-default}` syntax

## Example Input
```env
# Server config
HOST=localhost
PORT=3000
API_URL=https://$HOST:$PORT/api
DEBUG=true
SECRET_KEY="my-secret-key"
DESCRIPTION="""
This is a
multiline value
"""
FALLBACK=${UNDEFINED_VAR:-fallback_value}
```

## Expected Output
```json
{
  "HOST": "localhost",
  "PORT": "3000",
  "API_URL": "https://localhost:3000/api",
  "DEBUG": "true",
  "SECRET_KEY": "my-secret-key",
  "DESCRIPTION": "This is a\nmultiline value",
  "FALLBACK": "fallback_value"
}
```

## Constraints
- Use any language (Node.js, Python, Go, Rust)
- No external parsing libraries — write the parser from scratch
- Must handle edge cases: empty values, escaped characters, missing variables

## Evaluation Criteria
- Correctness of parsing logic
- Edge case handling
- Code organization and readability
- Test coverage',
    'easy',
    'backend',
    '["parsing", "config", "string-processing"]',
    45,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 009: Easy / Frontend - Accessible Form Builder
-- ============================================================
(
    'seed_challenge_009',
    'system',
    'Accessible Form Builder',
    'accessible-form-builder',
    'Create a dynamic form component with real-time validation, error messages, and full keyboard/screen-reader accessibility.',
    '# Accessible Form Builder

## Objective
Build a form component that is fully accessible and validates in real-time.

## Requirements
1. **Dynamic fields**: Render a form from a JSON schema:
```json
[
  {"name": "email", "type": "email", "label": "Email", "required": true},
  {"name": "password", "type": "password", "label": "Password", "required": true, "minLength": 8},
  {"name": "age", "type": "number", "label": "Age", "min": 18, "max": 120},
  {"name": "bio", "type": "textarea", "label": "Bio", "maxLength": 500},
  {"name": "role", "type": "select", "label": "Role", "options": ["Developer", "Designer", "PM"]}
]
```
2. **Real-time validation**: Validate on blur and show inline error messages
3. **Accessibility (WCAG 2.1 AA)**:
   - All inputs must have associated `<label>` elements
   - Error messages linked via `aria-describedby`
   - `aria-invalid` set on invalid fields
   - Focus management: move focus to first error on submit
   - Form must be fully operable with keyboard only
4. **Character counter** for textarea fields with maxLength
5. **Submit handler**: Call `onSubmit(data)` with validated form data
6. **Loading state**: Disable form and show spinner during submission

## Constraints
- Use React (with or without TypeScript)
- No form libraries (no react-hook-form, formik, etc.)
- Must pass axe-core accessibility audit with zero violations
- Style with CSS (no UI framework required, but must be usable)

## Evaluation Criteria
- Accessibility compliance (primary)
- Validation UX (helpful, not annoying)
- Component API design
- Code quality',
    'easy',
    'frontend',
    '["react", "accessibility", "forms", "a11y"]',
    45,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 010: Medium / Backend - Job Queue with Retries
-- ============================================================
(
    'seed_challenge_010',
    'system',
    'Job Queue with Retries',
    'job-queue-retries',
    'Implement an in-memory job queue with priority levels, exponential backoff retries, and concurrency control.',
    '# Job Queue with Retries

## Objective
Build a robust in-memory job queue system.

## Requirements

### Core Queue
1. `queue.add(job, options)` - Add a job to the queue
   - `job`: async function to execute
   - `options`: `{ priority: 1-5, retries: 3, timeout: 5000 }`
2. `queue.process(concurrency)` - Start processing with N concurrent workers
3. `queue.pause()` / `queue.resume()` - Pause/resume processing
4. `queue.getStats()` - Return `{ pending, active, completed, failed, retrying }`

### Retry Logic
- Failed jobs retry with **exponential backoff**: `delay = baseDelay * 2^attempt`
- Base delay: 1 second, max delay: 30 seconds
- Add jitter: `delay += random(0, delay * 0.1)`
- After max retries, move to dead-letter queue

### Priority
- Jobs with priority 1 (highest) execute before priority 5 (lowest)
- Equal priority: FIFO order

### Events
- `queue.on("completed", (result) => {})`
- `queue.on("failed", (error, job) => {})`
- `queue.on("retrying", (attempt, job) => {})`

## Example
```javascript
const queue = new JobQueue();

queue.add(async () => {
  const res = await fetch("https://api.example.com/data");
  return res.json();
}, { priority: 1, retries: 3, timeout: 5000 });

queue.on("completed", (result) => console.log("Done:", result));
queue.on("failed", (err) => console.error("Failed:", err));

queue.process(3); // 3 concurrent workers
```

## Constraints
- No external queue libraries
- Must handle job timeouts (reject if exceeds timeout)
- Must be safe for concurrent execution
- Clean up completed jobs from memory

## Evaluation Criteria
- Correctness of retry/backoff logic
- Concurrency handling
- Event system design
- Edge cases (timeout, rapid add/cancel)',
    'medium',
    'backend',
    '["queue", "async", "concurrency", "retry"]',
    60,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 011: Medium / DevOps - Docker Multi-Stage Build
-- ============================================================
(
    'seed_challenge_011',
    'system',
    'Docker Multi-Stage Build',
    'docker-multi-stage-build',
    'Containerize a Node.js/TypeScript application with a multi-stage Dockerfile, health checks, and a docker-compose setup with PostgreSQL.',
    '# Docker Multi-Stage Build

## Objective
Create a production-ready Docker setup for a TypeScript API.

## Given
A simple Express + TypeScript API project with:
- `src/index.ts` - Express server with a `/health` and `/api/users` endpoint
- `package.json` - Dependencies (express, typescript, ts-node)
- `tsconfig.json` - TypeScript config

## Requirements

### Dockerfile (multi-stage)
1. **Stage 1 - Builder**: Install deps, compile TypeScript
2. **Stage 2 - Production**: Copy only compiled JS + production deps
3. Use `node:22-alpine` as base
4. Run as non-root user
5. Add `HEALTHCHECK` instruction
6. Final image must be under 150MB

### docker-compose.yml
1. **api** service: the Node.js app
2. **db** service: PostgreSQL 16
3. **Networking**: services on a shared network
4. **Volumes**: persist PostgreSQL data
5. **Environment**: configure via `.env` file
6. **Health checks**: both services must have health checks
7. API should `depends_on` db with `condition: service_healthy`

### .dockerignore
- Exclude: `node_modules`, `.git`, `*.md`, `.env`, `dist`

## Bonus
- Add a `Makefile` with `make build`, `make up`, `make down`, `make logs`
- Add a `nginx` reverse proxy service
- Implement graceful shutdown in the Express app

## Evaluation Criteria
- Image size optimization
- Security (non-root, minimal attack surface)
- docker-compose best practices
- Health check implementation',
    'medium',
    'devops',
    '["docker", "devops", "typescript", "postgresql"]',
    60,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 012: Hard / Algorithms - LRU Cache with TTL
-- ============================================================
(
    'seed_challenge_012',
    'system',
    'LRU Cache with TTL',
    'lru-cache-ttl',
    'Implement an LRU cache with per-key TTL expiration, O(1) operations, and memory-bounded eviction.',
    '# LRU Cache with TTL

## Objective
Implement a Least Recently Used (LRU) cache with per-key TTL (time-to-live) support.

## Requirements

### Core API
```javascript
const cache = new LRUCache({ maxSize: 100, defaultTTL: 60000 });

cache.set("key", "value");              // uses defaultTTL
cache.set("key2", "value2", 5000);      // custom TTL: 5 seconds
cache.get("key");                       // returns "value" or undefined if expired
cache.has("key");                       // true/false (does not update recency)
cache.delete("key");                    // remove entry
cache.clear();                          // remove all entries
cache.size;                             // current number of non-expired entries
cache.keys();                           // iterator of keys in LRU order (most recent first)
```

### LRU Behavior
- When cache exceeds `maxSize`, evict the **least recently used** entry
- `get()` and `set()` both update an entry''s recency
- `has()` does NOT update recency

### TTL Behavior
- Each entry can have its own TTL (milliseconds)
- Expired entries are treated as non-existent:
  - `get()` on expired key returns `undefined`
  - `has()` on expired key returns `false`
- Expired entries should be lazily cleaned (on access) AND periodically purged
- Implement `cache.purgeExpired()` for manual cleanup

### Performance Requirements
- `get()`: O(1)
- `set()`: O(1)
- `delete()`: O(1)
- `has()`: O(1)

### Events
- `cache.on("evict", (key, value, reason) => {})`
  - `reason`: `"capacity"` or `"expired"`

## Implementation Hint
Use a **doubly-linked list** + **hash map** for O(1) LRU operations. Store timestamps for TTL checks.

## Constraints
- No external caching libraries
- Must achieve O(1) for all core operations
- Must handle edge cases: set on existing key, expired during iteration
- Write comprehensive tests (at least 15 test cases)

## Evaluation Criteria
- Algorithmic correctness (O(1) operations verified)
- TTL accuracy and cleanup strategy
- Memory efficiency
- Test comprehensiveness
- Code clarity',
    'hard',
    'algorithms',
    '["cache", "lru", "data-structures", "algorithms"]',
    60,
    NULL,
    '{}',
    1,
    1
);

PRAGMA foreign_keys = ON;
