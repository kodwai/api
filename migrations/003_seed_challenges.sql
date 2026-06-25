-- Seed starter challenges for the developer platform

PRAGMA foreign_keys = OFF;

INSERT OR IGNORE INTO challenges (id, created_by, title, slug, description, problem_statement_md, difficulty, category, tags, time_limit_minutes, test_suite, scoring_config, is_public, is_featured)
VALUES
(
    'seed_challenge_001',
    'system',
    'Build a REST API',
    'build-rest-api',
    'Design and implement a RESTful API for a todo list application with CRUD operations.',
    '# Build a REST API

## Objective
Create a RESTful API for a todo list application.

## Requirements
1. **GET /todos** - List all todos
2. **POST /todos** - Create a new todo with `title` (required) and `completed` (default: false)
3. **GET /todos/:id** - Get a single todo by ID
4. **PUT /todos/:id** - Update a todo (title and/or completed)
5. **DELETE /todos/:id** - Delete a todo

## Constraints
- Use any language/framework you prefer
- Todos should be stored in memory (no database required)
- Return proper HTTP status codes (200, 201, 404, 400)
- Return JSON responses

## Bonus
- Add input validation
- Add filtering: `GET /todos?completed=true`
- Add pagination support',
    'easy',
    'backend',
    '["api", "rest", "crud"]',
    45,
    '[{"runner": "node", "command": "node test.js", "file_path": "test.js", "content": "console.log(''Tests would run here'')"}]',
    '{}',
    1,
    1
),
(
    'seed_challenge_002',
    'system',
    'React Component Refactor',
    'react-component-refactor',
    'Refactor a messy React component into clean, maintainable code with proper state management.',
    '# React Component Refactor

## Objective
You are given a monolithic React component that handles user profiles. Refactor it into clean, well-structured code.

## The Problem
The file `ProfilePage.jsx` contains a single 300-line component that:
- Fetches user data
- Handles form editing
- Manages avatar uploads
- Shows activity history
- Handles error states

## Requirements
1. Break the monolith into smaller, focused components
2. Extract custom hooks for data fetching and form state
3. Add proper TypeScript types
4. Maintain all existing functionality
5. Improve error handling

## Evaluation Criteria
- Component decomposition quality
- Hook design and reusability
- TypeScript usage
- Code readability',
    'medium',
    'frontend',
    '["react", "typescript", "refactoring"]',
    60,
    NULL,
    '{}',
    1,
    1
),
(
    'seed_challenge_003',
    'system',
    'Debug the Authentication Flow',
    'debug-auth-flow',
    'Find and fix 5 bugs in a broken authentication system. Tests are failing - make them pass.',
    '# Debug the Authentication Flow

## Objective
A JWT-based authentication system has 5 bugs causing test failures. Find and fix them all.

## Setup
The project includes:
- `auth.js` - Authentication logic (login, register, verify token)
- `middleware.js` - Express middleware for protected routes
- `test.js` - Test suite with 5 failing tests

## The Bugs
The test suite will guide you. Each test failure points to a different bug:
1. Registration does not hash passwords
2. Login returns wrong status code on invalid credentials
3. Token verification does not check expiration
4. Protected route middleware does not extract Bearer token correctly
5. Logout does not invalidate the token

## Rules
- Only modify `auth.js` and `middleware.js`
- Do NOT modify the test file
- All 5 tests must pass when you are done',
    'easy',
    'backend',
    '["debugging", "auth", "javascript"]',
    30,
    NULL,
    '{}',
    1,
    1
),
(
    'seed_challenge_004',
    'system',
    'CLI Tool with File Processing',
    'cli-file-processing',
    'Build a command-line tool that processes CSV files and outputs formatted reports.',
    '# CLI Tool with File Processing

## Objective
Build a CLI tool that reads CSV data and generates summary reports.

## Requirements
1. Accept a CSV file path as argument: `node cli.js data.csv`
2. Parse the CSV (headers: name, department, salary, start_date)
3. Generate a report showing:
   - Total employees per department
   - Average salary per department
   - Highest and lowest paid employees
   - Employees who started in the last 12 months
4. Output as formatted table to stdout
5. Support `--format json` flag for JSON output
6. Handle errors gracefully (missing file, malformed CSV)

## Bonus
- Support `--sort-by salary|department|name`
- Support `--filter department=Engineering`
- Add a `--output report.txt` flag to write to file',
    'medium',
    'backend',
    '["cli", "csv", "node"]',
    60,
    NULL,
    '{}',
    1,
    0
),
(
    'seed_challenge_005',
    'system',
    'Database Schema Design',
    'database-schema-design',
    'Design a database schema for an e-commerce platform and write the migration SQL.',
    '# Database Schema Design

## Objective
Design a relational database schema for a small e-commerce platform.

## Requirements
The platform needs to support:
1. **Users** - registration, profiles, addresses
2. **Products** - name, description, price, inventory, categories
3. **Orders** - cart to checkout flow, order status tracking
4. **Reviews** - product reviews with ratings

## Deliverables
1. An SQL file with all CREATE TABLE statements
2. Proper foreign keys, indexes, and constraints
3. A seed file with sample data (at least 5 users, 10 products, 3 orders)
4. A README explaining your design decisions

## Evaluation Criteria
- Normalization (avoid redundancy)
- Index strategy (query performance)
- Constraint design (data integrity)
- Naming conventions (consistency)',
    'medium',
    'fullstack',
    '["sql", "database", "schema-design"]',
    60,
    NULL,
    '{}',
    1,
    0
),
(
    'seed_challenge_006',
    'system',
    'Algorithm: Rate Limiter',
    'algorithm-rate-limiter',
    'Implement a sliding window rate limiter that handles concurrent requests efficiently.',
    '# Algorithm: Rate Limiter

## Objective
Implement a sliding window rate limiter.

## Requirements
1. `RateLimiter(maxRequests, windowMs)` - constructor
2. `limiter.isAllowed(clientId)` - returns true/false
3. `limiter.getRemainingRequests(clientId)` - returns count
4. `limiter.getResetTime(clientId)` - returns ms until window resets

## Constraints
- Must use sliding window (not fixed window)
- Must handle multiple clients independently
- Must clean up expired entries to prevent memory leaks
- O(1) or O(log n) time complexity for isAllowed()

## Test Cases
```
const limiter = new RateLimiter(5, 60000)
limiter.isAllowed("user1") // true (1/5)
limiter.isAllowed("user1") // true (2/5)
// ... 3 more calls
limiter.isAllowed("user1") // false (5/5 - rate limited)
limiter.getRemainingRequests("user1") // 0
```',
    'hard',
    'algorithms',
    '["algorithms", "rate-limiting", "data-structures"]',
    45,
    NULL,
    '{}',
    1,
    1
),
(
    'seed_challenge_007',
    'system',
    'Full-Stack: Real-Time Chat',
    'fullstack-realtime-chat',
    'Build a minimal real-time chat application with rooms, message history, and online status.',
    '# Full-Stack: Real-Time Chat

## Objective
Build a working real-time chat application.

## Requirements
1. **Backend**: WebSocket server with room support
2. **Frontend**: Simple HTML/JS chat UI (no framework required)
3. **Features**:
   - Join/leave chat rooms
   - Send and receive messages in real-time
   - Show online users in current room
   - Message history (in-memory, last 50 messages per room)
   - Username selection on join

## Technical Constraints
- Use WebSocket (not polling)
- Backend in Node.js (any WS library)
- Frontend must work in a browser
- No database needed (in-memory storage)

## Bonus
- Typing indicators
- Private messages between users
- Message timestamps
- Reconnection handling',
    'hard',
    'fullstack',
    '["websocket", "realtime", "fullstack"]',
    90,
    NULL,
    '{}',
    1,
    0
);

PRAGMA foreign_keys = ON;
