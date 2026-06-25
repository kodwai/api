-- Migration 011: Fourth batch of challenges (38-52)
-- Final push to 50+ challenges
-- Brings total from 37 to 52

PRAGMA foreign_keys = OFF;

INSERT OR IGNORE INTO challenges (id, created_by, title, slug, description, problem_statement_md, difficulty, category, tags, time_limit_minutes, test_suite, scoring_config, is_public, is_featured)
VALUES
-- ============================================================
-- Challenge 038: Easy / Backend - Markdown to HTML Converter
-- ============================================================
(
    'seed_challenge_038',
    'system',
    'Markdown to HTML Converter',
    'markdown-html-converter',
    'Build a Markdown parser that converts a subset of Markdown to valid HTML — headings, lists, links, code blocks, and emphasis.',
    '# Markdown to HTML Converter

## Objective
Build a Markdown-to-HTML converter from scratch. No libraries.

## Supported Syntax
1. **Headings**: `# H1` through `###### H6`
2. **Bold**: `**text**`
3. **Italic**: `*text*`
4. **Links**: `[text](url)`
5. **Images**: `![alt](url)`
6. **Code**: Inline `` `code` `` and fenced blocks ` ```lang `
7. **Unordered lists**: `- item` (nested with indentation)
8. **Ordered lists**: `1. item`
9. **Blockquotes**: `> text`
10. **Horizontal rule**: `---`
11. **Paragraphs**: Text separated by blank lines

## API
```javascript
const html = markdown("# Hello\n\nThis is **bold** and *italic*.");
// <h1>Hello</h1>\n<p>This is <strong>bold</strong> and <em>italic</em>.</p>
```

## Requirements
- Handle nested formatting (`**bold *and italic* text**`)
- Properly close all HTML tags
- Escape HTML entities in content (`<`, `>`, `&`)
- Handle edge cases: empty input, consecutive headings, nested lists

## Evaluation Criteria
- Parsing correctness
- Nested formatting handling
- Edge case coverage
- Code clarity',
    'easy',
    'backend',
    '["parsing", "markdown", "html", "string-processing"]',
    45,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 039: Medium / Algorithms - Dependency Resolver
-- ============================================================
(
    'seed_challenge_039',
    'system',
    'Dependency Resolver',
    'dependency-resolver',
    'Build a dependency resolver that computes installation order, detects circular dependencies, and resolves version conflicts.',
    '# Dependency Resolver

## Objective
Build a package dependency resolver — the core algorithm behind npm, pip, and cargo.

## Requirements

### Input
```json
{
  "A": { "version": "1.0", "deps": { "B": "^2.0", "C": "^1.0" } },
  "B": { "version": "2.1", "deps": { "D": "^3.0" } },
  "C": { "version": "1.2", "deps": { "D": "^3.0" } },
  "D": { "version": "3.0", "deps": {} }
}
```

### Core Features
1. **Topological sort**: Return packages in installation order (dependencies first)
2. **Circular dependency detection**: Detect and report cycles with the full cycle path
3. **Version resolution**: When multiple packages depend on D, find a compatible version
4. **Semver matching**: Implement `^` (compatible), `~` (patch-level), exact matching

### API
```javascript
const resolver = new DependencyResolver(registry);

const result = resolver.resolve(["A"]);
// { order: ["D@3.0", "B@2.1", "C@1.2", "A@1.0"], resolved: {...} }

const result2 = resolver.resolve(["X"]);
// throws CircularDependencyError: "X -> Y -> Z -> X"
```

### Edge Cases
- Diamond dependencies (A→B→D, A→C→D)
- Version conflicts (B needs D@3.x, C needs D@2.x)
- Optional dependencies
- Missing packages

## Evaluation Criteria
- Topological sort correctness
- Cycle detection with clear error messages
- Semver matching accuracy
- Conflict resolution strategy',
    'medium',
    'algorithms',
    '["algorithms", "graph", "topological-sort", "semver"]',
    60,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 040: Easy / DevOps - Health Check Dashboard
-- ============================================================
(
    'seed_challenge_040',
    'system',
    'Service Health Check Dashboard',
    'health-check-dashboard',
    'Build a health check system that monitors multiple services, tracks uptime, and displays status on a live dashboard.',
    '# Service Health Check Dashboard

## Objective
Build a system that monitors the health of multiple services and displays their status.

## Requirements

### Health Checker
```javascript
const monitor = new HealthMonitor({
  interval: 30000, // check every 30s
  timeout: 5000,   // 5s timeout per check
  services: [
    { name: "API", url: "http://localhost:3000/health", type: "http" },
    { name: "Database", host: "localhost", port: 5432, type: "tcp" },
    { name: "Redis", host: "localhost", port: 6379, type: "tcp" },
    { name: "Webhook", url: "http://example.com/webhook", type: "http", method: "POST" },
  ]
});
```

### Check Types
- **HTTP**: GET/POST request, expect 2xx status
- **TCP**: Attempt socket connection, expect success within timeout

### Dashboard (HTML page)
- Show each service: name, status (UP/DOWN/DEGRADED), response time, last checked
- Color coding: green (up), red (down), yellow (degraded/slow)
- Uptime percentage (last 24 hours)
- Response time chart (last 1 hour)
- Auto-refresh every 30 seconds

### Incident Tracking
- Service goes DOWN → start incident, log timestamp
- Service comes back UP → close incident, calculate downtime
- `GET /api/incidents` → list all incidents with duration

## Constraints
- Any language for backend
- Vanilla HTML/CSS/JS for dashboard (no frameworks)
- In-memory storage

## Evaluation Criteria
- Check reliability
- Dashboard UX
- Incident tracking accuracy
- Response time measurement',
    'easy',
    'devops',
    '["monitoring", "health-check", "dashboard", "devops"]',
    50,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 041: Hard / Backend - SQL Query Engine
-- ============================================================
(
    'seed_challenge_041',
    'system',
    'Mini SQL Query Engine',
    'mini-sql-engine',
    'Build a SQL query engine that parses and executes SELECT, WHERE, JOIN, GROUP BY, and ORDER BY on in-memory CSV data.',
    '# Mini SQL Query Engine

## Objective
Build a SQL query engine that operates on CSV files loaded into memory.

## Supported SQL
```sql
SELECT name, department, AVG(salary) as avg_salary
FROM employees
WHERE department != ''HR''
GROUP BY department
HAVING AVG(salary) > 50000
ORDER BY avg_salary DESC
LIMIT 10
```

## Requirements

### SQL Parser
Parse these clauses:
- `SELECT` (columns, aliases, aggregate functions)
- `FROM` (table name = CSV filename)
- `WHERE` (=, !=, >, <, >=, <=, AND, OR, LIKE, IN, IS NULL)
- `JOIN` (INNER JOIN ... ON)
- `GROUP BY` + `HAVING`
- `ORDER BY` (ASC/DESC)
- `LIMIT` / `OFFSET`

### Aggregate Functions
- `COUNT(*)`, `COUNT(col)`
- `SUM(col)`, `AVG(col)`
- `MIN(col)`, `MAX(col)`

### Data Loading
- Load CSV files as tables: `engine.loadCSV("employees", "employees.csv")`
- Auto-detect column types (string, number, date)

### API
```javascript
const engine = new SQLEngine();
engine.loadCSV("employees", "data/employees.csv");
engine.loadCSV("departments", "data/departments.csv");

const result = engine.execute(`
  SELECT e.name, d.name as dept
  FROM employees e
  JOIN departments d ON e.dept_id = d.id
  WHERE e.salary > 60000
  ORDER BY e.name
`);
// { columns: ["name", "dept"], rows: [...] }
```

## Evaluation Criteria
- SQL parsing correctness
- JOIN implementation
- Aggregate functions
- Query optimization (any indexing or early filtering)
- Error messages for invalid SQL',
    'hard',
    'backend',
    '["sql", "parser", "query-engine", "algorithms"]',
    90,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 042: Medium / Frontend - Command Palette
-- ============================================================
(
    'seed_challenge_042',
    'system',
    'Command Palette (Cmd+K)',
    'command-palette',
    'Build a Cmd+K command palette component with fuzzy search, keyboard navigation, nested actions, and recent history.',
    '# Command Palette (Cmd+K)

## Objective
Build the Cmd+K command palette pattern used by Linear, GitHub, Vercel, and Raycast.

## Requirements

### Core
1. **Trigger**: Open with Cmd+K (Mac) / Ctrl+K (Windows)
2. **Search**: Fuzzy matching against command names and descriptions
3. **Keyboard navigation**: Up/Down arrows, Enter to select, Esc to close
4. **Sections**: Group commands by category (Navigation, Actions, Settings)
5. **Nested menus**: Some commands open sub-menus (e.g., "Change theme" → Light/Dark/System)
6. **Recent**: Show recently used commands at the top

### Command Registry
```jsx
const commands = [
  { id: "home", label: "Go to Home", section: "Navigation", action: () => navigate("/") },
  { id: "settings", label: "Open Settings", section: "Navigation", shortcut: "Cmd+,", action: ... },
  { id: "theme", label: "Change Theme", section: "Settings", children: [
    { id: "light", label: "Light", action: () => setTheme("light") },
    { id: "dark", label: "Dark", action: () => setTheme("dark") },
  ]},
  { id: "copy-url", label: "Copy Current URL", section: "Actions", action: () => copyToClipboard(url) },
];
```

### Fuzzy Search
- Match by label and keywords
- Highlight matched characters in results
- Rank: exact match > starts with > contains > fuzzy

### UX Details
- Modal overlay with backdrop blur
- Smooth open/close animation
- Show keyboard shortcuts next to commands
- Empty state: "No results for ..."
- Max 8 visible results, scroll for more

## Constraints
- React + TypeScript
- No component libraries
- Must be fully keyboard-operable
- Accessible (proper ARIA roles)

## Evaluation Criteria
- Fuzzy search quality
- Keyboard navigation correctness
- Nested menu UX
- Animation polish
- Accessibility',
    'medium',
    'frontend',
    '["react", "command-palette", "search", "keyboard"]',
    60,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 043: Easy / Debugging - Fix the Flaky Tests
-- ============================================================
(
    'seed_challenge_043',
    'system',
    'Fix the Flaky Tests',
    'fix-flaky-tests',
    'A test suite has 8 flaky tests that pass sometimes and fail sometimes. Find the root cause of each and make them deterministic.',
    '# Fix the Flaky Tests

## Objective
A test suite has 8 tests that fail intermittently. Make them all pass 100% of the time.

## Flaky Patterns
Each test has a different root cause for flakiness:

1. **Date dependency**: Test hardcodes a date that fails on weekends
2. **Random order**: Test depends on execution order of other tests
3. **Timing**: Test uses `setTimeout` with exact timing assertions
4. **Shared state**: Tests share a global variable that bleeds between runs
5. **Network**: Test hits a real API that occasionally times out
6. **Floating point**: Test compares floats with `===` instead of tolerance
7. **Timezone**: Test assumes UTC but CI runs in different timezone
8. **Async**: Test doesn''t wait for async operation to complete

## Requirements
1. Identify the flakiness root cause for each test
2. Fix each test to be deterministic
3. Add a comment above each fix explaining the pattern
4. Tests must pass 50 consecutive runs with `--repeat 50`
5. Do NOT delete any tests — fix them

## Rules
- You may refactor the test code
- You may add test utilities/helpers
- You may NOT modify the source code being tested
- You may add mocks/stubs where needed

## Evaluation Criteria
- All 8 root causes correctly identified
- Fixes are clean and minimal
- Tests pass consistently (50 runs)
- Explanation quality',
    'easy',
    'debugging',
    '["testing", "debugging", "flaky-tests", "determinism"]',
    40,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 044: Medium / Refactoring - Extract a Design System
-- ============================================================
(
    'seed_challenge_044',
    'system',
    'Extract a Design System',
    'extract-design-system',
    'Refactor a React app with inconsistent styling into a cohesive design system with tokens, components, and documentation.',
    '# Extract a Design System

## Objective
A React app has grown organically with inconsistent styling — 47 different font sizes, 23 shades of blue, and duplicated components. Extract a design system.

## The Problem
- Buttons use 6 different styles across the app
- Colors are hardcoded hex values everywhere
- Spacing uses random pixel values (13px, 17px, 22px)
- Typography has no system (font sizes from 10px to 48px with no scale)
- Some components are duplicated 3-4 times with slight variations

## Requirements

### 1. Design Tokens
Create a token system:
```javascript
const tokens = {
  colors: { primary: { 50: "...", 100: "...", ..., 900: "..." }, ... },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32, xxl: 48 },
  typography: { xs: 12, sm: 14, base: 16, lg: 18, xl: 20, "2xl": 24, "3xl": 30 },
  radii: { sm: 4, md: 8, lg: 12, full: 9999 },
  shadows: { sm: "...", md: "...", lg: "..." },
};
```

### 2. Core Components
Extract and unify these components:
- **Button**: primary, secondary, outline, ghost, danger variants + sizes
- **Input**: text, email, password, textarea + states (error, disabled)
- **Card**: with header, body, footer slots
- **Badge**: status variants (success, warning, error, info)
- **Avatar**: sizes, fallback initials

### 3. Replace Hardcoded Values
Refactor existing pages to use tokens and components. Zero hardcoded colors, font sizes, or spacing values should remain.

### 4. Storybook-style Documentation
Create a simple page showing all components with their variants.

## Evaluation Criteria
- Token system completeness
- Component API design
- Consistency (no remaining hardcoded values)
- Visual quality (does it look good?)
- Documentation',
    'medium',
    'refactoring',
    '["design-system", "react", "refactoring", "css"]',
    75,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 045: Hard / Algorithms - Regex Engine
-- ============================================================
(
    'seed_challenge_045',
    'system',
    'Regex Engine from Scratch',
    'regex-engine-scratch',
    'Build a regular expression engine that supports literals, wildcards, quantifiers, character classes, groups, and alternation.',
    '# Regex Engine from Scratch

## Objective
Implement a regular expression engine using Thompson''s NFA construction.

## Supported Syntax
1. **Literals**: `abc` matches "abc"
2. **Dot**: `.` matches any character
3. **Quantifiers**: `*` (0+), `+` (1+), `?` (0 or 1)
4. **Character classes**: `[abc]`, `[a-z]`, `[^0-9]`
5. **Alternation**: `cat|dog`
6. **Groups**: `(abc)+`
7. **Anchors**: `^` (start), `$` (end)
8. **Escape**: `\.` matches literal dot

## API
```javascript
const re = new RegexEngine("^[a-z]+@[a-z]+\\.[a-z]{2,}$");
re.test("hello@world.com");  // true
re.test("HELLO@world.com");  // false

const matches = re.match("abc123def456", "[0-9]+");
// ["123", "456"]
```

## Implementation Steps
1. **Lexer**: Tokenize the regex pattern
2. **Parser**: Build an AST from tokens
3. **NFA Construction**: Thompson''s algorithm to build NFA from AST
4. **Matcher**: Simulate NFA to match input strings

## Requirements
- Implement all syntax listed above
- `test(input)` — returns boolean
- `match(input)` — returns all matches
- Handle edge cases: empty pattern, empty input, catastrophic backtracking prevention
- Write at least 25 test cases

## Evaluation Criteria
- Syntax coverage
- NFA construction correctness
- Performance (no exponential blowup on pathological inputs)
- Code structure (lexer → parser → NFA → matcher pipeline)',
    'hard',
    'algorithms',
    '["regex", "automata", "nfa", "parser"]',
    90,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 046: Medium / Data - ETL Pipeline with Validation
-- ============================================================
(
    'seed_challenge_046',
    'system',
    'ETL Pipeline with Validation',
    'etl-pipeline-validation',
    'Build an Extract-Transform-Load pipeline that pulls data from multiple sources, validates, deduplicates, and loads into a unified schema.',
    '# ETL Pipeline with Validation

## Objective
Build an ETL pipeline that merges user data from 3 different sources into a clean, unified dataset.

## Data Sources
1. **CSV file**: `users_crm.csv` — CRM export (name, email, phone, company)
2. **JSON file**: `users_app.json` — App database dump (username, email, created_at, plan)
3. **API endpoint**: `GET /api/users` — Third-party service (email, full_name, role, department)

## Pipeline Stages

### Extract
- Read each source into a common intermediate format
- Handle encoding issues (UTF-8, Latin-1)
- Parse dates into ISO format regardless of source format

### Transform
- **Schema mapping**: Map each source''s fields to a unified schema
- **Deduplication**: Match users across sources by email (primary key)
- **Merge**: When same user exists in multiple sources, merge fields (prefer newest data)
- **Validation**: Validate email format, phone format, required fields
- **Enrichment**: Derive `full_name` from `first_name + last_name` where needed

### Load
- Output unified dataset as `users_unified.json`
- Generate `validation_report.json` with all errors and warnings
- Generate `merge_log.json` showing how records were merged

## Unified Schema
```json
{
  "email": "required, unique",
  "full_name": "required",
  "phone": "optional, E.164 format",
  "company": "optional",
  "role": "optional",
  "plan": "optional",
  "source": ["crm", "app", "api"],
  "created_at": "ISO 8601",
  "merged_from": 2
}
```

## Evaluation Criteria
- Deduplication accuracy
- Merge conflict resolution
- Validation thoroughness
- Report quality
- Pipeline robustness (handles missing/malformed data)',
    'medium',
    'data',
    '["etl", "data-pipeline", "validation", "deduplication"]',
    75,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 047: Easy / Fullstack - Contact Form with Spam Filter
-- ============================================================
(
    'seed_challenge_047',
    'system',
    'Contact Form with Spam Filter',
    'contact-form-spam-filter',
    'Build a contact form with honeypot, rate limiting, content analysis, and email delivery — no CAPTCHA needed.',
    '# Contact Form with Spam Filter

## Objective
Build a contact form that blocks spam without annoying CAPTCHAs.

## Requirements

### Frontend
- Fields: name, email, subject, message
- Client-side validation with inline errors
- Honeypot field (hidden from humans, visible to bots)
- Submission timestamp tracking (reject forms submitted in under 3 seconds)
- Success/error feedback with animations

### Backend API
`POST /api/contact`

### Spam Detection (layer by layer)
1. **Honeypot**: Reject if hidden field is filled
2. **Timing**: Reject if form submitted in < 3 seconds
3. **Rate limit**: Max 3 submissions per IP per hour
4. **Content analysis**: Flag if message contains:
   - More than 3 URLs
   - All-caps text (>50% uppercase)
   - Known spam keywords list
   - Very short message (< 10 chars)
5. **Email validation**: Verify email format + MX record check

### On Valid Submission
- Store in database/memory
- Send notification email to admin
- Send confirmation email to submitter
- Return success response

### Admin View
- `GET /api/contacts` — List all submissions
- `GET /api/contacts/spam` — List flagged spam
- Mark as spam / not spam

## Evaluation Criteria
- Spam detection effectiveness
- UX quality (no friction for real users)
- Email delivery
- Code organization',
    'easy',
    'fullstack',
    '["forms", "spam-filter", "email", "fullstack"]',
    50,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 048: Medium / Backend - API Gateway
-- ============================================================
(
    'seed_challenge_048',
    'system',
    'API Gateway',
    'api-gateway',
    'Build an API gateway that routes requests to backend services with authentication, rate limiting, request transformation, and circuit breaking.',
    '# API Gateway

## Objective
Build a lightweight API gateway that sits in front of multiple backend services.

## Requirements

### Route Configuration
```javascript
const gateway = new APIGateway({
  routes: [
    { path: "/api/users/*", target: "http://user-service:3001", auth: true },
    { path: "/api/products/*", target: "http://product-service:3002", auth: true },
    { path: "/api/public/*", target: "http://public-service:3003", auth: false },
  ]
});
```

### Features
1. **Routing**: Path-based routing to backend services (strip gateway prefix)
2. **Authentication**: Validate JWT in Authorization header, inject user info as `X-User-Id` header
3. **Rate Limiting**: Per-user and per-IP rate limits
4. **Request Logging**: Log method, path, status, duration for every request
5. **Circuit Breaker**: If a backend returns 5 errors in 30 seconds, open the circuit (return 503) for 60 seconds, then half-open (allow 1 request to test)
6. **Request Transformation**: Add/remove/modify headers before forwarding
7. **Response Caching**: Cache GET responses with configurable TTL
8. **Health Aggregation**: `GET /health` returns health of all backends

### Circuit Breaker States
- **Closed**: Normal operation, forward all requests
- **Open**: Backend is failing, immediately return 503
- **Half-Open**: Allow one test request through, if it succeeds → close, if it fails → re-open

## Evaluation Criteria
- Routing correctness
- Circuit breaker state machine
- Rate limiting accuracy
- Caching implementation
- Overall architecture',
    'medium',
    'backend',
    '["api-gateway", "microservices", "circuit-breaker", "proxy"]',
    75,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 049: Hard / Fullstack - Collaborative Text Editor
-- ============================================================
(
    'seed_challenge_049',
    'system',
    'Collaborative Text Editor',
    'collaborative-text-editor',
    'Build a real-time collaborative text editor using Operational Transformation or CRDTs that supports multiple simultaneous users.',
    '# Collaborative Text Editor

## Objective
Build a Google Docs-style collaborative text editor where multiple users can edit the same document simultaneously.

## Requirements

### Backend
1. **Document storage**: Create, read, update documents
2. **WebSocket server**: Real-time sync between clients
3. **Conflict resolution**: Implement OT (Operational Transform) or CRDT
4. **Operation types**: Insert text, delete text, retain (skip) positions
5. **Operation history**: Store all operations for undo/redo and replay

### Frontend
1. **Text editor**: Contenteditable div or textarea with cursor management
2. **Real-time sync**: See other users'' edits instantly
3. **Cursor presence**: Show other users'' cursor positions with colored indicators
4. **User list**: Show who''s currently editing
5. **Undo/Redo**: Per-user undo stack

### Conflict Resolution (OT)
```
User A types "Hello" at position 0
User B types "World" at position 0 (simultaneously)

Without OT: One edit overwrites the other
With OT: Transform operations so both edits are preserved → "HelloWorld" or "WorldHello"
```

### Operations
```javascript
// Insert "Hello" at position 0
{ type: "insert", position: 0, text: "Hello", userId: "A" }

// Delete 3 characters at position 5
{ type: "delete", position: 5, count: 3, userId: "B" }

// Transform: if A inserts at pos 0, B''s pos 5 becomes pos 10
```

## Test Scenario
Open 3 browser tabs → All editing same document → All changes sync instantly → No data loss

## Evaluation Criteria
- OT/CRDT correctness (no data loss under concurrent edits)
- Real-time sync latency
- Cursor presence
- Undo/redo per user
- Code architecture',
    'hard',
    'fullstack',
    '["crdt", "ot", "collaborative", "websocket", "realtime"]',
    120,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 050: Medium / Debugging - Performance Bottleneck
-- ============================================================
(
    'seed_challenge_050',
    'system',
    'Find the Performance Bottleneck',
    'performance-bottleneck',
    'A Node.js API endpoint takes 8 seconds to respond. Profile it, find the bottlenecks, and optimize it to under 200ms.',
    '# Find the Performance Bottleneck

## Objective
An API endpoint `GET /api/dashboard` takes 8 seconds to respond. Find all bottlenecks and optimize it to under 200ms.

## The Endpoint
The dashboard endpoint:
1. Fetches user profile from database
2. Fetches user''s 50 most recent orders
3. For each order, fetches the order items
4. For each order, fetches the shipping status
5. Calculates summary statistics
6. Renders and returns the response

## Hidden Bottlenecks (find them all)
There are 6 performance issues:
1. **N+1 query**: Fetches order items one-by-one instead of batch
2. **Sequential async**: Fetches that could be parallel are sequential
3. **Missing index**: Database query does full table scan
4. **Redundant computation**: Recalculates the same value in a loop
5. **Oversized payload**: Fetches all columns when only 3 are needed
6. **No caching**: Fetches static config data on every request

## Requirements
1. Identify all 6 bottlenecks
2. Fix each one with a comment explaining the issue
3. Add timing instrumentation to prove the improvement
4. Final response time must be under 200ms
5. Behavior must remain identical (same response data)

## Evaluation Criteria
- Number of bottlenecks correctly identified
- Optimization quality (not just "cache everything")
- Timing proof (before/after measurements)
- Explanation clarity',
    'medium',
    'debugging',
    '["performance", "optimization", "profiling", "n-plus-one"]',
    60,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 051: Easy / Refactoring - TypeScript Migration
-- ============================================================
(
    'seed_challenge_051',
    'system',
    'JavaScript to TypeScript Migration',
    'js-to-typescript-migration',
    'Migrate a 500-line JavaScript Express API to TypeScript with strict mode, proper types, and zero `any` usage.',
    '# JavaScript to TypeScript Migration

## Objective
Migrate a working JavaScript Express API to strict TypeScript.

## The Codebase
A REST API with:
- `server.js` — Express setup and middleware
- `routes/users.js` — CRUD endpoints for users
- `routes/posts.js` — CRUD endpoints for posts
- `middleware/auth.js` — JWT authentication
- `utils/helpers.js` — Utility functions
- `db.js` — In-memory database layer

## Requirements
1. Rename all `.js` files to `.ts`
2. Add proper types for ALL function parameters and return types
3. Create interface definitions for all data models
4. Type the Express request/response with custom properties
5. Enable `strict: true` in tsconfig.json
6. Zero `any` types — use `unknown` with type guards where needed
7. Add generic types where beneficial
8. All existing tests must still pass

## Specific Typing Challenges
- Express `req.user` (added by auth middleware)
- Database query results
- Error handling middleware types
- Utility function generics
- Environment variable types

## Deliverables
- All `.ts` files with proper types
- `tsconfig.json` with strict mode
- Type declaration file for any untyped dependencies
- No TypeScript errors with `tsc --noEmit`

## Evaluation Criteria
- Type safety (no `any`, no `@ts-ignore`)
- Interface/type design quality
- Generic usage where appropriate
- Strict mode compliance
- Code readability (types help, not hinder)',
    'easy',
    'refactoring',
    '["typescript", "migration", "refactoring", "types"]',
    50,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 052: Medium / System Design - Feature Flag System
-- ============================================================
(
    'seed_challenge_052',
    'system',
    'Feature Flag System',
    'feature-flag-system',
    'Build a feature flag service with percentage rollouts, user targeting, A/B testing support, and a management dashboard.',
    '# Feature Flag System

## Objective
Build a feature flag system for controlling feature rollouts.

## Requirements

### Core API
```javascript
const flags = new FeatureFlagService();

// Check if feature is enabled for a user
flags.isEnabled("new-checkout", { userId: "123", country: "US", plan: "pro" });

// Get all flags for a user (for frontend SDK)
flags.getAllFlags({ userId: "123" });
```

### Flag Types
1. **Boolean**: Simple on/off
2. **Percentage rollout**: Enable for N% of users (deterministic by userId hash)
3. **User targeting**: Enable for specific user IDs or segments
4. **Rule-based**: Enable based on user properties (country, plan, etc.)

### Management API
- `POST /flags` — Create a flag
- `PUT /flags/:key` — Update flag rules
- `DELETE /flags/:key` — Archive a flag
- `GET /flags` — List all flags with status
- `GET /flags/:key/stats` — Flag evaluation stats

### Flag Definition
```json
{
  "key": "new-checkout",
  "description": "New checkout flow",
  "enabled": true,
  "rules": [
    { "type": "user", "userIds": ["123", "456"] },
    { "type": "percentage", "value": 25 },
    { "type": "property", "property": "plan", "operator": "in", "values": ["pro", "enterprise"] }
  ],
  "defaultValue": false
}
```

### Rules Evaluation Order
1. If flag is disabled → return false
2. Check user targeting rules (explicit include/exclude)
3. Check property rules
4. Check percentage rollout
5. Return default value

### Dashboard (bonus)
Simple web UI to create/edit flags and see evaluation stats.

## Evaluation Criteria
- Rule evaluation correctness
- Percentage rollout determinism (same user always gets same result)
- API design
- Flag management UX',
    'medium',
    'system-design',
    '["feature-flags", "system-design", "rollout", "targeting"]',
    75,
    NULL,
    '{}',
    1,
    0
);

PRAGMA foreign_keys = ON;
