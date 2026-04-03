-- Migration 010: AI-resistant challenges (023-032)
-- These challenges are designed to be impossible to solve in a single AI prompt.
-- They exploit known AI weaknesses: multi-phase pipelines, architectural cascading,
-- hidden-state debugging, novel algorithms, and long-horizon reasoning.
-- Brings total from 22 to 32.

PRAGMA foreign_keys = OFF;

INSERT OR IGNORE INTO challenges (id, created_by, title, slug, description, problem_statement_md, difficulty, category, tags, time_limit_minutes, test_suite, scoring_config, is_public, is_featured)
VALUES
-- ============================================================
-- Challenge 023: Hard / Algorithms - SQL Query Engine
-- Why AI can't one-shot: 5-phase pipeline (lexer→parser→planner→optimizer→executor)
-- where each phase's edge cases cascade into the next. AI typically gets the
-- lexer/parser right but breaks on JOIN optimization and correlated subqueries.
-- ============================================================
(
    'seed_challenge_023',
    'system',
    'SQL Query Engine from Scratch',
    'sql-query-engine',
    'Build a working SQL query engine that parses SQL, builds query plans, optimizes joins, and executes against CSV data files.',
    '# SQL Query Engine from Scratch

## Objective
Build a multi-phase SQL query engine that can parse, plan, optimize, and execute queries against CSV files. This is NOT a string-matching exercise — you must build a real pipeline.

## Architecture (you must implement all 5 phases)

```
SQL String → [Lexer] → Tokens → [Parser] → AST → [Planner] → Logical Plan → [Optimizer] → Physical Plan → [Executor] → Results
```

## Phase 1: Lexer & Parser
Parse a subset of SQL into an AST:
```sql
SELECT col1, col2, COUNT(*) as cnt
FROM table1
JOIN table2 ON table1.id = table2.fk_id
WHERE col1 > 100 AND col2 LIKE ''%hello%''
GROUP BY col1, col2
HAVING cnt > 5
ORDER BY col1 DESC
LIMIT 10 OFFSET 20
```

Supported syntax:
- SELECT (with aliases, `*`, expressions)
- FROM (single table and JOINs: INNER, LEFT, RIGHT)
- WHERE (AND, OR, NOT, comparisons, LIKE, IN, IS NULL, BETWEEN)
- GROUP BY + HAVING
- ORDER BY (ASC/DESC, multiple columns)
- LIMIT/OFFSET
- Aggregate functions: COUNT, SUM, AVG, MIN, MAX
- Subqueries in WHERE clause: `WHERE id IN (SELECT fk_id FROM other WHERE ...)`

## Phase 2: Query Planner
Convert AST into a logical plan (tree of relational operators):
- `Scan(table)` - Read all rows from a CSV
- `Filter(predicate)` - Apply WHERE conditions
- `Join(left, right, condition, type)` - Join two inputs
- `Aggregate(group_keys, aggregations)` - GROUP BY
- `Sort(keys)` - ORDER BY
- `Limit(count, offset)` - LIMIT/OFFSET
- `Project(columns)` - SELECT specific columns

## Phase 3: Query Optimizer
Implement at least these optimizations:
1. **Predicate pushdown**: Move WHERE filters below JOINs when possible
2. **Projection pushdown**: Only read needed columns from CSV
3. **Join reordering**: For multi-table joins, put the smaller table on the build side
4. Plan must be inspectable: `EXPLAIN SELECT ...` prints the plan tree

## Phase 4: Executor
- **Iterator model**: Each plan node implements `open()`, `next()`, `close()`
- Scan node streams CSV rows (don''t load entire file into memory for files > 10MB)
- Join uses hash join for equi-joins, nested loop for non-equi
- Must handle NULL values correctly (NULL comparisons, NULL in aggregations)
- Type coercion: numeric strings compared numerically, date strings compared chronologically

## Phase 5: Data Layer
- Tables are CSV files in a `./data/` directory
- First row is header (column names)
- Auto-detect types: integer, float, string, date (YYYY-MM-DD), boolean
- `CREATE TABLE name AS SELECT ...` writes results to a new CSV
- `INSERT INTO table VALUES (...)` appends to CSV

## Test Scenarios Your Engine Must Handle
```sql
-- Basic query
SELECT name, age FROM users WHERE age > 25 ORDER BY name;

-- Join with aggregation
SELECT u.name, COUNT(o.id) as order_count, SUM(o.total) as total_spent
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
GROUP BY u.name
HAVING total_spent > 100
ORDER BY total_spent DESC;

-- Subquery
SELECT * FROM products
WHERE category_id IN (
    SELECT id FROM categories WHERE name LIKE ''%Electronics%''
);

-- Multi-table join with optimization opportunity
SELECT c.name, p.title, o.quantity
FROM customers c
JOIN orders o ON c.id = o.customer_id
JOIN products p ON o.product_id = p.id
WHERE c.country = ''US'' AND p.price > 50
ORDER BY o.quantity DESC
LIMIT 20;

-- Self-join
SELECT e.name as employee, m.name as manager
FROM employees e
LEFT JOIN employees m ON e.manager_id = m.id;

-- EXPLAIN shows the optimized plan
EXPLAIN SELECT * FROM large_table WHERE indexed_col = 42;
```

## Deliverables
1. A CLI: `node sql.js "SELECT * FROM users"` or pipe: `echo "SELECT ..." | node sql.js`
2. Provide sample CSV files in `./data/` for testing (at least 3 tables, 100+ rows each)
3. An `EXPLAIN` command that prints the query plan tree
4. At least 30 test cases covering each phase

## Evaluation Criteria
- Parser completeness (handles all specified SQL)
- Optimizer actually improves plans (demonstrate with EXPLAIN)
- Correct NULL handling
- Memory efficiency (streaming for large files)
- Edge cases: empty tables, all NULLs, zero-row JOINs, self-joins
- Code architecture: clean phase separation',
    'hard',
    'algorithms',
    '["sql", "parser", "query-engine", "compiler", "optimizer"]',
    120,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 024: Hard / Fullstack - Collaborative Text Editor with CRDTs
-- Why AI can't one-shot: CRDT merge semantics have subtle invariants that
-- break under concurrent edits. Cursor tracking, undo-per-user, and
-- offline reconciliation each add a layer of interacting complexity.
-- ============================================================
(
    'seed_challenge_024',
    'system',
    'Real-Time Collaborative Text Editor',
    'collaborative-text-editor',
    'Build a Google Docs-style collaborative editor with CRDT-based conflict resolution, cursor presence, per-user undo, and offline support.',
    '# Real-Time Collaborative Text Editor

## Objective
Build a collaborative plain-text editor where multiple users edit the same document simultaneously with zero conflicts. This requires implementing a CRDT (Conflict-free Replicated Data Type) — not just last-write-wins.

## Why This Is Hard
CRDTs sound simple in theory but break in subtle ways:
- Two users type at the same position → interleaving must be deterministic
- User A deletes a range while User B types inside it → what survives?
- Undo must only undo YOUR operations, not undo what others did concurrently
- Offline edits must merge cleanly when reconnecting

## Requirements

### 1. CRDT Engine (Core)
Implement a sequence CRDT (RGA, LSEQ, or Yjs-style approach):
- **Insert(position, character, userId, timestamp)** — add character
- **Delete(position, userId, timestamp)** — remove character (tombstone, don''t physically remove)
- **Merge(remoteOps)** — integrate remote operations into local state
- Operations must be **commutative** and **idempotent**: applying ops in any order produces the same document

Properties that MUST hold:
- **Convergence**: All replicas reach the same state after receiving the same set of operations
- **Intent preservation**: If user A types "hello" at position 5, the word appears intact even if user B is editing nearby
- **Causality**: Operations respect happened-before ordering

### 2. Networking Layer
- WebSocket server that broadcasts operations to all connected clients
- Operation buffering: batch rapid keystrokes into fewer network messages (50ms window)
- Reconnection: client detects disconnect, queues local ops, replays on reconnect
- Server maintains a canonical operation log for new clients joining mid-session

### 3. Cursor Presence
- Each user has a colored cursor + name label visible to all others
- Cursors update in real-time as users navigate
- Selection ranges are shared (show what others have selected)
- Cursor positions must remain correct as remote edits shift text around

### 4. Per-User Undo/Redo
- Ctrl+Z undoes only YOUR last operation, not the globally last operation
- If you typed "abc" and another user typed "xyz" between your "b" and "c", undoing should remove your "c" only
- Undo stack is per-user and survives reconnection
- Redo works after undo (standard undo/redo semantics per user)

### 5. Offline Support
- Editor remains fully functional when disconnected
- Local operations are queued and sent on reconnect
- On reconnect: merge remote ops that happened during disconnect
- Resolve any conflicts from concurrent offline edits
- Visual indicator showing online/offline status and pending sync count

### 6. Frontend
- Clean text editor UI (monospace font, line numbers)
- Colored cursors for each connected user
- User list panel showing who''s connected
- Connection status indicator
- Document loads from server on connect, syncs incrementally after

## Verification Scenarios
1. **Concurrent typing**: Open 3 tabs, type simultaneously at different positions → all converge
2. **Concurrent same-position**: Two users type at the exact same position → text interleaves deterministically, no data loss
3. **Delete vs. insert conflict**: User A selects and deletes a paragraph while User B types inside it → User B''s new text survives (or is cleanly handled)
4. **Offline edit**: Disconnect one tab, type 100 characters, reconnect → document converges
5. **Per-user undo**: User A types, User B types, User A hits undo → only User A''s text is removed
6. **Rapid reconnection**: Disconnect/reconnect rapidly 10 times → no duplicate operations, no corruption
7. **Late joiner**: New client connects to a document with 10K operations → loads current state efficiently (not replaying all ops)

## Constraints
- Any language for server (Node.js recommended)
- Vanilla JS or lightweight framework for frontend
- You MUST implement the CRDT yourself — do not use Yjs, Automerge, or similar libraries
- WebSocket for real-time communication
- In-memory storage (no database)

## Evaluation Criteria
- **CRDT correctness** (40%): Convergence, intent preservation, idempotency
- **Conflict handling** (20%): Concurrent edits produce sensible results
- **Per-user undo** (15%): Correctly scoped undo/redo
- **Offline support** (15%): Clean merge on reconnect
- **UX polish** (10%): Cursor presence, status indicators, responsive feel',
    'hard',
    'fullstack',
    '["crdt", "realtime", "collaborative", "websocket", "editor"]',
    120,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 025: Hard / System Design - Git Implementation
-- Why AI can't one-shot: Content-addressable storage, tree serialization,
-- three-way merge with conflict markers, and packfile format each have
-- non-obvious invariants. The merge algorithm alone requires understanding
-- LCA in the commit DAG.
-- ============================================================
(
    'seed_challenge_025',
    'system',
    'Build Git from Scratch',
    'mini-git',
    'Implement core Git internals: content-addressable object store, staging area, branching, merging with conflict detection, and diff.',
    '# Build Git from Scratch

## Objective
Implement the core of Git — not a wrapper around Git, but the actual internal data structures and algorithms. Your implementation must produce a `.kodgit/` directory with real content-addressable objects.

## Internal Architecture

### Object Store (`.kodgit/objects/`)
Every object is stored by its SHA-1 hash. Three object types:
1. **Blob**: Raw file content → `sha1(blob <size>\0<content>)`
2. **Tree**: Directory listing → entries of `<mode> <name>\0<sha1_bytes>`
3. **Commit**: Points to a tree + parent(s) + author + message

Store objects as: `.kodgit/objects/<first-2-chars>/<remaining-38-chars>`
Content is zlib-compressed.

### References (`.kodgit/refs/`)
- `refs/heads/<branch>` — file containing commit SHA
- `HEAD` — either `ref: refs/heads/main` (symbolic) or a raw SHA (detached)

### Index / Staging Area (`.kodgit/index`)
Binary or JSON file tracking staged files with their blob SHAs.

## Commands to Implement

### Basics
```bash
kodgit init                          # Create .kodgit/ structure
kodgit hash-object -w <file>         # Hash and store a blob
kodgit cat-file -p <sha>             # Print object content
kodgit cat-file -t <sha>             # Print object type
```

### Staging & Committing
```bash
kodgit add <file>                    # Stage a file (create blob, update index)
kodgit add .                         # Stage all changed files
kodgit status                        # Show staged, modified, untracked files
kodgit commit -m "message"           # Create tree from index, create commit object
kodgit log                           # Walk commit chain, print log
kodgit log --graph                   # ASCII graph for branches
```

### Branching
```bash
kodgit branch                        # List branches
kodgit branch <name>                 # Create branch at HEAD
kodgit checkout <branch>             # Switch branch (update HEAD + working tree)
kodgit checkout -b <name>            # Create and switch
```

### Diffing
```bash
kodgit diff                          # Working tree vs index
kodgit diff --staged                 # Index vs last commit
kodgit diff <commit1> <commit2>      # Between two commits
```
Output unified diff format:
```
--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,4 @@
 line 1
-old line 2
+new line 2
+inserted line
 line 3
```
Implement the diff using Myers'' algorithm or similar LCS-based approach.

### Merging
```bash
kodgit merge <branch>                # Three-way merge into current branch
```
Merge algorithm:
1. Find merge base (LCA of current HEAD and target branch in commit DAG)
2. Three-way diff: base vs ours, base vs theirs
3. Auto-merge non-conflicting changes
4. Mark conflicts in files:
```
<<<<<<< HEAD
our version
=======
their version
>>>>>>> feature-branch
```
5. If no conflicts → auto-commit the merge (two parents)
6. If conflicts → leave markers in working tree, require manual resolution + commit

### Edge Cases Your Merge Must Handle
- File modified in both branches (different sections → auto-merge, same section → conflict)
- File deleted in one branch, modified in the other → conflict
- File added in both branches with different content → conflict
- File renamed in one branch → detect and handle (bonus)
- Binary files → always conflict, don''t attempt merge

## Verification Scenarios
```bash
# Basic workflow
kodgit init
echo "hello" > file.txt
kodgit add file.txt
kodgit commit -m "initial"
kodgit log   # Shows one commit

# Branching + merge (no conflict)
kodgit branch feature
kodgit checkout feature
echo "feature work" > feature.txt
kodgit add feature.txt
kodgit commit -m "add feature"
kodgit checkout main
kodgit merge feature
kodgit log --graph   # Shows merge commit

# Conflict scenario
kodgit checkout -b conflict-a
echo "version A" > shared.txt && kodgit add . && kodgit commit -m "A"
kodgit checkout main
kodgit checkout -b conflict-b
echo "version B" > shared.txt && kodgit add . && kodgit commit -m "B"
kodgit merge conflict-a   # Should show CONFLICT in shared.txt
cat shared.txt            # Should have conflict markers
```

## Constraints
- Any language (Node.js or Python recommended)
- Must use SHA-1 hashing
- Must compress objects (zlib)
- Do NOT shell out to real git
- Must handle binary files (store as blobs, skip diff/merge)

## Evaluation Criteria
- **Object model correctness** (25%): Proper content-addressable storage, deduplication
- **Merge algorithm** (25%): Three-way merge, conflict detection, merge commit
- **Diff quality** (20%): Myers/LCS algorithm, unified format, handles edge cases
- **Branch/checkout** (15%): Correct HEAD management, working tree updates
- **CLI polish** (15%): Colored output, helpful error messages, status display',
    'hard',
    'system-design',
    '["git", "vcs", "content-addressable", "merge-algorithm", "diff"]',
    120,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 026: Hard / Algorithms - Compiler for a Mini Language
-- Why AI can't one-shot: Type inference across closures, register
-- allocation, and optimization passes require iterative debugging.
-- A subtle type-checker bug surfaces only in higher-order functions.
-- ============================================================
(
    'seed_challenge_026',
    'system',
    'Compiler for MiniLang',
    'minilang-compiler',
    'Design and implement a complete compiler for a small typed language: lexer, parser, type checker, optimizer, and code generator targeting JavaScript.',
    '# Compiler for MiniLang

## Objective
Build a complete compiler for "MiniLang" — a small but non-trivial typed language that compiles to JavaScript. Every phase of the compiler must be implemented by you.

## MiniLang Specification

### Types
```
Int, Float, String, Bool, Void
[T]              -- Array of T
(T1, T2) -> T3   -- Function type
T?               -- Nullable (T or null)
```

### Syntax
```
// Variables (type-inferred)
let x = 42
let name: String = "hello"
let mut counter = 0       // mutable

// Functions
fn add(a: Int, b: Int) -> Int {
    return a + b
}

// Higher-order functions & closures
fn apply(f: (Int) -> Int, x: Int) -> Int {
    return f(x)
}
let double = fn(x: Int) -> Int { x * 2 }
apply(double, 5)  // 10

// Control flow
if x > 0 {
    print("positive")
} else if x == 0 {
    print("zero")
} else {
    print("negative")
}

// Pattern matching
match value {
    0 => print("zero"),
    1..10 => print("small"),
    n if n > 100 => print("big: " + str(n)),
    _ => print("other")
}

// Loops
for i in 0..10 {
    print(i)
}
while condition {
    counter = counter + 1
}

// Arrays
let nums = [1, 2, 3, 4, 5]
let doubled = nums.map(fn(x) { x * 2 })
let sum = nums.reduce(0, fn(acc, x) { acc + x })
nums.filter(fn(x) { x > 2 }).forEach(fn(x) { print(x) })

// Nullable handling
let maybe: Int? = findUser(id)
let value = maybe ?? 0              // default if null
let forced = maybe!                 // runtime error if null

// String interpolation
let msg = "Hello, ${name}! You are ${age} years old."

// Structs
struct Point {
    x: Float,
    y: Float
}
fn distance(a: Point, b: Point) -> Float {
    let dx = a.x - b.x
    let dy = a.y - b.y
    return sqrt(dx * dx + dy * dy)
}

// Enums with associated data
enum Shape {
    Circle(Float),
    Rectangle(Float, Float),
    Triangle(Float, Float, Float)
}
fn area(s: Shape) -> Float {
    match s {
        Shape.Circle(r) => 3.14159 * r * r,
        Shape.Rectangle(w, h) => w * h,
        Shape.Triangle(a, b, c) => {
            let s = (a + b + c) / 2.0
            sqrt(s * (s - a) * (s - b) * (s - c))
        }
    }
}
```

## Compiler Phases

### Phase 1: Lexer
- Tokenize MiniLang source into: keywords, identifiers, literals, operators, punctuation
- Track line/column for error reporting
- Handle string interpolation by decomposing `"Hello ${name}"` into string concat tokens

### Phase 2: Parser
- Build an AST from tokens
- Operator precedence: `||` < `&&` < `==`/`!=` < `<`/`>`/`<=`/`>=` < `+`/`-` < `*`/`/`/`%` < unary `-`/`!` < `.`/`[]`
- Parse struct definitions, enum definitions, match expressions
- Good error messages: "Expected '')'' after parameter list at line 12, column 34"

### Phase 3: Type Checker
- **Hindley-Milner style inference**: Infer types from usage where not annotated
- Closures capture variables from enclosing scope — infer captured variable types
- Nullable types: ensure null checks before use (`if x != null { ... x ... }`)
- Struct field access type-checked
- Enum variant type-checked in match arms
- Function overloading NOT supported (simpler) — but generic inference is required for array methods (.map, .filter, .reduce)
- Report clear type errors: `"Cannot add String and Int at line 5"`

### Phase 4: Optimizer (at least 3 passes)
1. **Constant folding**: `2 + 3` → `5`, `"hello" + " world"` → `"hello world"`
2. **Dead code elimination**: Remove unreachable code after return/early exit
3. **Inline small functions**: Functions with ≤3 expressions get inlined at call site
4. Each pass operates on the AST and produces a new AST

### Phase 5: Code Generator
- Output valid JavaScript (ES2020+)
- Map MiniLang constructs to JS:
  - `let`/`let mut` → `const`/`let`
  - `match` → chained `if/else` or `switch`
  - Structs → classes or plain objects
  - Enums → tagged objects: `{ tag: "Circle", _0: 5.0 }`
  - Nullable `??` → JS `??`
  - String interpolation → template literals
  - `for i in 0..10` → `for (let i = 0; i < 10; i++)`
- Generated code must be runnable with `node output.js`

## CLI
```bash
minilang compile input.ml -o output.js    # Compile to JS
minilang run input.ml                      # Compile and execute
minilang check input.ml                    # Type-check only
minilang ast input.ml                      # Print AST
minilang tokens input.ml                   # Print token stream
```

## Test Cases You Must Pass
Provide at least 40 test cases organized by phase:
- Lexer: 10 tests (edge cases: nested interpolation, escaped quotes, Unicode)
- Parser: 10 tests (precedence, error recovery, complex expressions)
- Type checker: 10 tests (inference, nullable, closures, generics, error messages)
- End-to-end: 10 tests (full programs that compile and run correctly)

## Constraints
- Implement in Node.js or Python
- No parser generators (PEG.js, ANTLR, etc.) — write the parser by hand (recursive descent)
- No existing compiler infrastructure — build all phases yourself
- Generated JavaScript must run without dependencies

## Evaluation Criteria
- **Type checker correctness** (30%): Inference, nullable safety, generics
- **Parser quality** (20%): Error messages, full syntax support
- **Optimizer effectiveness** (15%): Demonstrable improvement on test programs
- **Code generation** (20%): Correct, readable output
- **End-to-end tests** (15%): Comprehensive coverage of language features',
    'hard',
    'algorithms',
    '["compiler", "parser", "type-system", "code-generation", "language-design"]',
    120,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 027: Hard / System Design - Distributed Task Scheduler
-- Why AI can't one-shot: DAG dependency resolution, distributed locking,
-- failure recovery with exactly-once semantics, and cron parsing all
-- interact in ways that produce bugs only under concurrent load.
-- ============================================================
(
    'seed_challenge_027',
    'system',
    'Distributed Task Scheduler',
    'distributed-task-scheduler',
    'Build a task scheduling system with cron expressions, DAG dependencies, worker pools, failure recovery, and exactly-once execution.',
    '# Distributed Task Scheduler

## Objective
Build a production-grade task scheduler that handles cron schedules, task dependencies (DAGs), distributed execution across worker processes, and failure recovery. Think Airflow, but built from scratch.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Scheduler   │────▶│  Task Queue  │◀────│   Workers    │
│  (cron +     │     │  (priority   │     │  (pool of N  │
│   DAG engine)│     │   queue)     │     │   processes)  │
└──────┬───────┘     └──────────────┘     └──────┬───────┘
       │                                          │
       ▼                                          ▼
┌──────────────┐                          ┌──────────────┐
│  DAG Store   │                          │  Result Store│
│  (definitions│                          │  (outcomes + │
│   + state)   │                          │   logs)      │
└──────────────┘                          └──────────────┘
```

## Requirements

### 1. Task Definitions
```javascript
// Define tasks
scheduler.task("extract-data", {
    handler: async (ctx) => {
        const data = await fetchFromAPI(ctx.params.source);
        return { rows: data.length, path: "/tmp/data.csv" };
    },
    timeout: 60000,        // 1 minute
    retries: 3,
    retryDelay: "exponential",  // 1s, 2s, 4s, 8s...
    tags: ["etl", "data"]
});

// Define DAGs (task pipelines)
scheduler.dag("daily-etl", {
    schedule: "0 2 * * *",   // 2 AM daily
    tasks: {
        "extract":   { task: "extract-data", params: { source: "api" } },
        "transform": { task: "transform-data", dependsOn: ["extract"] },
        "validate":  { task: "validate-data", dependsOn: ["transform"] },
        "load-db":   { task: "load-to-db", dependsOn: ["validate"] },
        "load-cache":{ task: "update-cache", dependsOn: ["validate"] },
        "notify":    { task: "send-notification", dependsOn: ["load-db", "load-cache"] }
    }
});
```

### 2. Cron Engine
- Parse cron expressions: `"*/5 * * * *"`, `"0 9 * * MON-FRI"`, `"0 0 1,15 * *"`
- Support 5-field (minute, hour, day, month, weekday) and 6-field (+ seconds) formats
- Support ranges (`1-5`), steps (`*/15`), lists (`1,3,5`), names (`MON`, `JAN`)
- Calculate next N run times from any given date
- Handle timezone-aware scheduling

### 3. DAG Engine
- **Topological execution**: Run tasks in dependency order, parallelize independent branches
- **Cycle detection**: Reject DAGs with circular dependencies at definition time
- **Partial retry**: If task 4/6 fails, retry from task 4 (don''t re-run 1-3)
- **DAG-level timeout**: Kill all remaining tasks if DAG exceeds total time limit
- **Dynamic dependencies**: A task can emit new tasks at runtime: `ctx.spawn("subtask", params)`
- **Task output passing**: Downstream tasks receive upstream task outputs via `ctx.upstream.taskName.result`

### 4. Worker Pool
- **N worker processes** (configurable, default 4) executing tasks concurrently
- **Task claiming**: Workers atomically claim tasks from queue (no double execution)
- **Heartbeat**: Workers send heartbeats every 5 seconds; scheduler marks silent workers as dead after 30s
- **Graceful shutdown**: On SIGTERM, finish current task, don''t accept new ones
- **Worker isolation**: A crashing task handler must not crash the worker process
- **Concurrency limits**: Per-task-type concurrency limits (`maxConcurrent: 2`)

### 5. Failure Handling
- **Retry strategies**: fixed, exponential, linear backoff
- **Dead letter queue**: After all retries exhausted, move task to DLQ with full context
- **Circuit breaker**: If a task type fails 5 times in 10 minutes, pause scheduling for that type
- **Zombie detection**: If a worker dies mid-task, another worker picks it up
- **Exactly-once semantics**: Use idempotency keys — task handler receives `ctx.idempotencyKey` and must handle re-execution safely

### 6. Observability
- **Real-time dashboard** (HTTP endpoint): current DAG runs, task states, worker status
- **Event log**: All state transitions logged with timestamps
- **Metrics endpoint** (`GET /metrics`):
  - Tasks completed/failed/retried (by type)
  - Average task duration (by type)
  - Queue depth
  - Worker utilization
  - DAG success/failure rates

### 7. API
```
POST   /dags                    # Create/update a DAG definition
GET    /dags                    # List all DAGs
POST   /dags/:id/trigger        # Manually trigger a DAG run
GET    /dags/:id/runs            # List runs for a DAG
GET    /runs/:id                 # Get run status with task details
POST   /runs/:id/retry           # Retry failed tasks in a run
DELETE /runs/:id                 # Cancel a running DAG
GET    /tasks/dead-letter        # View dead letter queue
POST   /tasks/dead-letter/:id/retry  # Retry a dead-letter task
GET    /metrics                  # Prometheus-style metrics
GET    /workers                  # Worker pool status
```

## Verification Scenarios
1. **DAG execution order**: Define A→B→C→D with C also depending on E (parallel with A→B). Verify E and A→B run in parallel, C waits for both.
2. **Failure + retry**: Task fails twice then succeeds → verify 3 attempts logged, downstream continues.
3. **Worker death**: Kill a worker process mid-task → task gets re-queued and completed by another worker.
4. **Cron scheduling**: Schedule task for "every 5 seconds" → verify it fires ≥5 times in 30 seconds.
5. **Circuit breaker**: Make a task always fail → after 5 failures, verify no more scheduling for that type.
6. **Cycle rejection**: Define DAG with A→B→C→A → verify clear error at definition time.
7. **Partial retry**: In a 5-task DAG, fail at task 3. Retry → only tasks 3-5 re-execute.

## Constraints
- Node.js (use `child_process.fork()` for workers) or Python (use `multiprocessing`)
- In-memory storage for task state (no Redis/DB)
- Must use real multi-process workers, not just async functions
- No external job queue libraries (Bull, Celery, etc.)

## Evaluation Criteria
- **DAG engine correctness** (25%): Dependency resolution, parallel execution, cycle detection
- **Worker pool reliability** (25%): Claiming, heartbeats, zombie recovery
- **Failure handling** (20%): Retries, circuit breaker, DLQ, exactly-once
- **Cron accuracy** (15%): Parsing, edge cases (leap year, DST)
- **Observability** (15%): Dashboard, metrics, event log',
    'hard',
    'system-design',
    '["scheduler", "dag", "distributed", "cron", "worker-pool"]',
    120,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 028: Hard / Data - Full-Text Search Engine
-- Why AI can't one-shot: Inverted index construction, BM25 ranking,
-- fuzzy matching (Levenshtein automata), faceted aggregation, and
-- real-time index updates are each non-trivial. Together they require
-- careful data structure choices that cascade through the entire system.
-- ============================================================
(
    'seed_challenge_028',
    'system',
    'Full-Text Search Engine',
    'search-engine',
    'Build a search engine with inverted index, BM25 ranking, fuzzy matching, faceted search, and real-time indexing.',
    '# Full-Text Search Engine

## Objective
Build a search engine from scratch — not a wrapper around a database LIKE query, but a real inverted index with relevance ranking. Think Elasticsearch, but built by you.

## Architecture

```
Documents → [Analyzer] → [Indexer] → Inverted Index
                                           ↑
Queries → [Query Parser] → [Searcher] ────┘
                                ↓
                          [Ranker (BM25)] → Ranked Results
```

## Requirements

### 1. Document Ingestion
```javascript
// Index a document
engine.index({
    id: "doc1",
    title: "Introduction to Search Engines",
    body: "A search engine is an information retrieval system...",
    author: "Jane Smith",
    tags: ["search", "ir", "tutorial"],
    published: "2024-03-15",
    category: "technology"
});

// Bulk index
engine.bulkIndex(documents);  // Array of 10,000+ documents

// Delete / Update
engine.delete("doc1");
engine.update("doc1", { title: "Updated Title" });
```

### 2. Text Analysis Pipeline
Each text field goes through:
1. **Tokenizer**: Split on whitespace and punctuation
2. **Lowercase filter**: `"Hello"` → `"hello"`
3. **Stop word removal**: Remove "the", "is", "at", "which", "on" (configurable list)
4. **Stemmer**: Porter stemmer algorithm — `"running"` → `"run"`, `"categories"` → `"categori"`
5. **Synonym expansion** (configurable): `"quick"` also indexes as `"fast"`

Implement the Porter stemmer yourself (at least Step 1a, 1b, 1c, 2, 3 — the core morphological rules).

### 3. Inverted Index
Data structure:
```
term → {
    docFreq: N,
    postings: [
        { docId, termFreq, positions: [0, 5, 12] },
        { docId, termFreq, positions: [3, 8] },
        ...
    ]
}
```
- **Positional index**: Store term positions for phrase queries
- **Field-specific indexing**: Separate inverted indexes per field (title, body, tags)
- **Real-time updates**: Adding/removing documents updates the index immediately
- **Memory efficient**: Use sorted posting lists with delta encoding for positions

### 4. Query Language
```
simple search                        // Match any of these terms
"exact phrase"                       // Phrase match (consecutive terms in order)
+required -excluded                  // Must contain / must not contain
title:search                         // Field-specific search
author:"Jane Smith"                  // Field-specific phrase
(search OR retrieval) AND engine     // Boolean operators
search~2                             // Fuzzy match (edit distance ≤ 2)
categ*                               // Prefix/wildcard query
published:[2024-01-01 TO 2024-12-31]  // Range query on date fields
```

Parse this into a query AST and execute against the index.

### 5. Ranking (BM25)
Implement BM25 scoring:
```
score(D, Q) = Σ IDF(qi) · (f(qi, D) · (k1 + 1)) / (f(qi, D) + k1 · (1 - b + b · |D|/avgdl))
```
Where:
- `f(qi, D)` = term frequency of qi in document D
- `|D|` = document length
- `avgdl` = average document length in corpus
- `k1 = 1.2`, `b = 0.75` (tunable)
- `IDF(qi) = ln((N - n(qi) + 0.5) / (n(qi) + 0.5) + 1)`

Field boosting: `title` matches score 3x, `tags` score 2x, `body` score 1x.

### 6. Fuzzy Matching
- Implement Levenshtein distance calculation
- For `search~2`: find all terms in the index within edit distance 2
- Use a BK-tree or similar structure for efficient fuzzy lookup (don''t brute-force all terms)
- Return fuzzy matches ranked by edit distance (closer = higher boost)

### 7. Faceted Search
```javascript
const results = engine.search("machine learning", {
    facets: ["category", "author", "published_year"],
    filters: { category: "technology" }
});

// Results include:
{
    hits: [...],
    facets: {
        category: { "technology": 42, "science": 18, "education": 7 },
        author: { "Jane Smith": 12, "John Doe": 8 },
        published_year: { "2024": 35, "2023": 22, "2022": 10 }
    }
}
```

### 8. Highlighting
Return search results with matched terms highlighted:
```javascript
{
    id: "doc1",
    score: 4.52,
    highlights: {
        title: "Introduction to <mark>Search</mark> <mark>Engines</mark>",
        body: "...a <mark>search</mark> <mark>engine</mark> is an information retrieval system..."
    }
}
```
- Show context window (50 chars before/after match)
- Highlight phrase matches as a unit

### 9. API
```
POST   /index                  # Index a document
POST   /bulk                   # Bulk index documents
DELETE /index/:id              # Delete a document
GET    /search?q=...&facets=...&page=...&size=...  # Search
GET    /suggest?q=...          # Autocomplete suggestions (prefix match)
GET    /stats                  # Index stats (doc count, term count, memory usage)
```

## Verification Scenarios
1. Index 1,000 documents, search for common term → results ranked by relevance, not insertion order
2. Phrase query `"search engine"` → only matches documents with those words adjacent and in order
3. Fuzzy search `"serch~1"` → matches "search"
4. Boolean query `+machine +learning -deep` → correct filtering
5. Faceted search returns accurate category counts even with filters applied
6. Delete a document → immediately disappears from search results
7. Index 10,000 documents → search returns in < 50ms
8. Porter stemmer: "running" and "runs" match "run" query

## Constraints
- Any language (Node.js or Python recommended)
- No search libraries (Lunr, MiniSearch, Whoosh, etc.)
- Implement the Porter stemmer yourself (at least core steps)
- Implement BM25 yourself
- In-memory storage

## Evaluation Criteria
- **Index correctness** (25%): Inverted index, positional data, real-time updates
- **Ranking quality** (20%): BM25 implementation, field boosting, result ordering
- **Query language** (20%): Full parser, boolean logic, phrase/fuzzy/range
- **Performance** (15%): Sub-100ms search on 10K docs, efficient indexing
- **Features** (20%): Facets, highlighting, autocomplete, stemmer quality',
    'hard',
    'data',
    '["search", "inverted-index", "bm25", "nlp", "information-retrieval"]',
    120,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 029: Hard / Frontend - Browser Layout Engine
-- Why AI can't one-shot: CSS cascade resolution, box model calculation,
-- flexbox layout, and paint ordering form a 4-phase pipeline where
-- each phase has hundreds of edge cases (margin collapsing, flex
-- wrapping, z-index stacking contexts) that compound.
-- ============================================================
(
    'seed_challenge_029',
    'system',
    'Mini Browser Layout Engine',
    'browser-layout-engine',
    'Build a mini browser engine that parses HTML/CSS, resolves the cascade, computes box layout (including flexbox), and renders to a canvas.',
    '# Mini Browser Layout Engine

## Objective
Build the rendering pipeline of a web browser — from raw HTML/CSS to pixels on a canvas. You''ll implement the same pipeline that Chrome and Firefox use, just for a subset of CSS.

## Pipeline

```
HTML → [HTML Parser] → DOM Tree
CSS  → [CSS Parser]  → Style Rules
                              ↓
DOM + Styles → [Style Resolver] → Styled Tree
                                       ↓
Styled Tree → [Layout Engine] → Layout Tree (with positions & sizes)
                                       ↓
Layout Tree → [Painter] → Canvas/Image output
```

## Phase 1: HTML Parser
Parse a subset of HTML into a DOM tree:
- Elements: `div`, `span`, `p`, `h1`-`h6`, `ul`, `ol`, `li`, `a`, `img`, `section`, `header`, `footer`, `main`, `nav`, `article`, `button`, `input`, `form`
- Attributes: `class`, `id`, `style` (inline), `src`, `href`
- Text nodes
- Self-closing tags: `<img />`, `<input />`, `<br />`
- Nested structures
- Ignore `<script>`, `<style>` content as DOM nodes (but parse `<style>` for CSS)

DOM Node:
```javascript
{
    type: "element",
    tag: "div",
    attributes: { class: "container", id: "main" },
    children: [...]
}
```

## Phase 2: CSS Parser
Parse CSS into structured rules:
```css
/* Selectors to support */
div { }                  /* Type selector */
.class { }               /* Class selector */
#id { }                  /* ID selector */
div.class { }            /* Combined */
div > p { }              /* Child combinator */
div p { }                /* Descendant combinator */
div, p { }               /* Selector list */
div:first-child { }      /* Pseudo-class (first-child, last-child only) */
* { }                    /* Universal */
```

### CSS Properties to Support
**Box Model:**
- `width`, `height`, `min-width`, `max-width`, `min-height`, `max-height`
- `margin` (shorthand + individual sides), `padding` (shorthand + individual sides)
- `border` (shorthand), `border-width`, `border-color`, `border-style`, `border-radius`

**Layout:**
- `display`: `block`, `inline`, `inline-block`, `flex`, `none`
- `position`: `static`, `relative`, `absolute`
- `top`, `right`, `bottom`, `left`
- `overflow`: `visible`, `hidden`

**Flexbox:**
- `flex-direction`: `row`, `column`
- `justify-content`: `flex-start`, `center`, `flex-end`, `space-between`, `space-around`
- `align-items`: `flex-start`, `center`, `flex-end`, `stretch`
- `flex-wrap`: `nowrap`, `wrap`
- `flex-grow`, `flex-shrink`, `flex-basis`
- `gap`

**Visual:**
- `color`, `background-color`, `background` (solid color only)
- `font-size`, `font-weight`, `font-family` (for text measurement)
- `line-height`, `text-align`
- `opacity`
- `box-shadow` (single shadow)

**Units:** `px`, `%`, `em`, `rem`, `auto`

## Phase 3: Style Resolution (The Cascade)
For each DOM node, compute the final style:
1. **Specificity**: ID (1,0,0) > Class (0,1,0) > Type (0,0,1). Inline styles beat all.
2. **Cascade order**: Later rules override earlier (same specificity)
3. **Inheritance**: `color`, `font-*`, `line-height`, `text-align` inherit from parent
4. **Default values**: Apply browser defaults (div = block, span = inline, etc.)
5. **Shorthand expansion**: `margin: 10px 20px` → `margin-top: 10px`, `margin-right: 20px`, etc.
6. **Unit resolution**: Convert `em`/`rem`/`%` to `px` relative to parent/root font size

Output: each DOM node gets a `computedStyle` object with all properties resolved to absolute `px` values.

## Phase 4: Layout Engine
Compute the position and size of every box.

### Block Layout
- Block boxes stack vertically
- Width defaults to parent''s content width
- **Margin collapsing**: Adjacent vertical margins collapse (take the larger one, not sum)
- `margin: auto` centers horizontally

### Inline Layout
- Inline boxes flow left-to-right, wrapping at container edge
- Text nodes are measured for width (use a font metrics approximation)
- `inline-block` participates in inline flow but has block-like box model

### Flexbox Layout
- Calculate main axis and cross axis based on `flex-direction`
- Distribute space according to `flex-grow`/`flex-shrink`
- Handle `flex-wrap` (items that don''t fit move to next line)
- Apply `justify-content` and `align-items`
- Resolve `flex-basis` vs `width`/`height`

### Absolute Positioning
- Remove from normal flow
- Position relative to nearest positioned ancestor
- `top`/`left`/`right`/`bottom` offset from containing block

Each node gets: `{ x, y, width, height, contentBox, paddingBox, borderBox, marginBox }`

## Phase 5: Painter
Render the layout tree to an HTML `<canvas>` or output as an image (PNG):
1. Paint backgrounds (in tree order, parents before children)
2. Paint borders (respecting `border-radius`)
3. Paint text (positioned correctly, with `color` and `font-size`)
4. Handle `opacity`
5. Handle `overflow: hidden` (clip children)
6. `box-shadow` painted before the box itself
7. **Z-ordering**: Absolutely positioned elements paint after normal flow

## Deliverables

### CLI Mode
```bash
render input.html -o output.png --width 800 --height 600
```

### Interactive Mode (bonus)
Serve an HTML page where:
- Left panel: edit HTML/CSS
- Right panel: your engine''s rendered output on a canvas
- Updates live as you type

### Test Pages
Provide at least 5 test HTML files:
1. **Box model test**: Nested divs with margin, padding, border — verify pixel-perfect sizing
2. **Flexbox test**: Various flex layouts (centered card, navbar, holy grail layout)
3. **Cascade test**: Conflicting styles resolved by specificity
4. **Text layout test**: Paragraphs with different font sizes, line heights, alignment
5. **Complex page**: A realistic page with header, nav, main content, sidebar, footer

## Verification
For each test page, provide an expected output image. Your engine''s output should match within a reasonable tolerance (±2px on positions, correct colors).

## Constraints
- Any language (Node.js with `canvas` package, or Python with Pillow recommended)
- No HTML/CSS parsing libraries — write your own parsers
- No layout libraries — compute all positions yourself
- Canvas/image library for final rendering is OK
- Approximate text metrics are acceptable (monospace assumption is fine for simplicity)

## Evaluation Criteria
- **CSS cascade correctness** (20%): Specificity, inheritance, defaults
- **Box model accuracy** (20%): Margin, padding, border, margin collapsing
- **Flexbox implementation** (25%): All specified flexbox properties work correctly
- **Parser quality** (15%): Handles nested HTML, complex selectors, shorthand CSS
- **Visual output** (20%): Rendered pages look correct and match expected output',
    'hard',
    'frontend',
    '["browser", "css", "layout-engine", "rendering", "parser"]',
    120,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 030: Hard / System Design - API Gateway with Plugin System
-- Why AI can't one-shot: The plugin lifecycle (load, init, per-request hooks,
-- hot-reload) interacts with the request pipeline, circuit breakers,
-- and config management in ways that produce race conditions and subtle
-- ordering bugs that only surface under concurrent requests.
-- ============================================================
(
    'seed_challenge_030',
    'system',
    'Plugin-Based API Gateway',
    'api-gateway',
    'Build an API gateway with dynamic routing, a plugin system (auth, rate-limit, cache, transform), hot-reload config, and circuit breakers.',
    '# Plugin-Based API Gateway

## Objective
Build an API gateway that sits between clients and backend services, providing routing, authentication, rate limiting, caching, and request transformation — all via a hot-reloadable plugin architecture.

## Architecture

```
Client Request
      ↓
[Plugin Pipeline: pre-request hooks]
  → Auth plugin (verify JWT/API key)
  → Rate Limiter plugin (check/increment counters)
  → Cache plugin (return cached response if hit)
  → Transform plugin (rewrite headers/body)
      ↓
[Router] → Match route → Proxy to upstream service
      ↓
[Plugin Pipeline: post-response hooks]
  → Cache plugin (store response)
  → Transform plugin (rewrite response)
  → Logger plugin (log request/response)
      ↓
Client Response
```

## Requirements

### 1. Configuration (YAML/JSON)
```yaml
gateway:
  port: 8080
  admin_port: 8081

routes:
  - path: /api/users/*
    upstream: http://localhost:3001
    methods: [GET, POST, PUT, DELETE]
    plugins:
      - name: auth
        config:
          type: jwt
          secret: "your-secret"
          exclude: ["/api/users/login", "/api/users/register"]
      - name: rate-limit
        config:
          requests: 100
          window: 60s
          key: "header:Authorization"
      - name: cache
        config:
          ttl: 300s
          methods: [GET]
          vary: ["Authorization"]

  - path: /api/products/*
    upstream: http://localhost:3002
    methods: [GET]
    plugins:
      - name: cache
        config:
          ttl: 600s

  - path: /api/admin/*
    upstream: http://localhost:3003
    plugins:
      - name: auth
        config:
          type: api-key
          header: X-Admin-Key
          keys: ["key1", "key2"]

plugins:
  global:
    - name: cors
      config:
        origins: ["http://localhost:3000"]
        methods: [GET, POST, PUT, DELETE]
        headers: [Authorization, Content-Type]
    - name: logger
      config:
        format: combined
        output: stdout
    - name: circuit-breaker
      config:
        threshold: 5
        timeout: 30s
        half_open_requests: 3
```

### 2. Plugin System

#### Plugin Interface
```javascript
class Plugin {
    constructor(config) { }

    // Called once when plugin loads
    async init() { }

    // Called before proxying to upstream (return response to short-circuit)
    async onRequest(ctx) { }

    // Called after receiving upstream response
    async onResponse(ctx) { }

    // Called on error
    async onError(ctx, error) { }

    // Called when plugin is unloaded (cleanup)
    async destroy() { }
}
```

#### Built-in Plugins (implement all 7)

**1. Auth Plugin**
- JWT verification: decode, verify signature, check expiration, attach `ctx.user`
- API key: check header against allowed keys
- Path exclusions: skip auth for specified paths
- Return 401 with clear error on failure

**2. Rate Limiter Plugin**
- Sliding window rate limiting
- Configurable key extraction: by IP, by header value, by JWT claim
- Return 429 with `Retry-After` header when exceeded
- Multiple windows: e.g., 100/minute AND 1000/hour

**3. Cache Plugin**
- Cache GET responses by URL + Vary headers
- TTL-based expiration
- Cache invalidation: `PURGE` method support
- Conditional requests: respect `If-None-Match` / `ETag`
- Skip caching for responses with `Cache-Control: no-store`
- Memory-bounded: LRU eviction when cache exceeds size limit

**4. CORS Plugin**
- Set `Access-Control-Allow-Origin`, `-Methods`, `-Headers`
- Handle preflight `OPTIONS` requests
- Support wildcard and specific origin lists
- Expose configured response headers

**5. Transform Plugin**
- Request transforms: add/remove/rename headers, rewrite paths
- Response transforms: add/remove headers, JSON body manipulation (jq-like path expressions)
- URL rewriting: `/api/v2/users` → `/users` before proxying

**6. Logger Plugin**
- Apache combined log format
- JSON structured logging option
- Log request duration, status, upstream response time
- Configurable output: stdout, file, or HTTP endpoint

**7. Circuit Breaker Plugin**
- Track failure rate per upstream
- States: **Closed** (normal) → **Open** (reject immediately) → **Half-Open** (allow probe requests)
- Closed → Open: when failures exceed threshold in window
- Open → Half-Open: after timeout period
- Half-Open → Closed: if probe requests succeed
- Half-Open → Open: if probe requests fail
- Return 503 with upstream status when circuit is open

### 3. Router
- **Path matching**: Exact, prefix (`/api/*`), parameterized (`/users/:id`)
- **Method matching**: Only route matching HTTP methods
- **Priority**: Exact > parameterized > prefix (most specific wins)
- **Load balancing**: Round-robin across multiple upstreams for the same route
- **Health checks**: Periodic pings to upstreams, remove unhealthy ones from rotation

### 4. Proxy
- Forward request headers (filter hop-by-hop headers)
- Stream request/response bodies (don''t buffer entire body in memory)
- Forward WebSocket connections (`Connection: Upgrade`)
- Timeout handling: connect timeout (5s default), read timeout (30s default)
- Add `X-Request-Id` header (UUID) for tracing
- Add `X-Forwarded-For`, `X-Forwarded-Proto` headers

### 5. Hot Reload
- Watch config file for changes
- On change: diff old vs new config
- Add/remove/update routes WITHOUT dropping existing connections
- Reload plugin instances (call `destroy()` on old, `init()` on new)
- Validate new config before applying (reject invalid configs)
- `POST /admin/reload` endpoint to trigger manual reload

### 6. Admin API (on separate port)
```
GET    /admin/health            # Gateway health status
GET    /admin/routes            # List all routes and their plugins
GET    /admin/plugins           # List loaded plugins
GET    /admin/stats             # Request counts, latencies, error rates per route
GET    /admin/circuit-breakers  # Circuit breaker states per upstream
POST   /admin/reload            # Hot-reload configuration
POST   /admin/cache/purge       # Purge cache (all or by pattern)
```

## Verification Scenarios
1. **Auth**: Request without JWT → 401. Valid JWT → proxied with `ctx.user` set.
2. **Rate limiting**: Send 101 requests in 60s → 101st gets 429 with `Retry-After`.
3. **Cache**: GET request → cached. Second GET → served from cache (verify with response header). PURGE → cache cleared.
4. **Circuit breaker**: Kill upstream → after 5 failures, circuit opens → immediate 503. Restart upstream → circuit half-opens → probe succeeds → circuit closes.
5. **Hot reload**: Change config to add new route → new route works without restart. Existing connections unaffected.
6. **Plugin ordering**: Auth runs before rate-limit. Cache runs before proxy (returns cached response). Logger runs after everything.
7. **WebSocket proxy**: Connect WebSocket through gateway → messages flow bidirectionally.

## Constraints
- Node.js or Python
- HTTP library for the server only (`http` module or equivalent) — no API gateway frameworks
- No external plugins — implement all 7 yourself
- In-memory storage for rate limits, cache, circuit breaker state

## Evaluation Criteria
- **Plugin architecture** (25%): Clean lifecycle, proper hook ordering, isolation
- **Built-in plugins** (25%): All 7 plugins work correctly
- **Router + Proxy** (20%): Path matching, streaming, WebSocket, load balancing
- **Hot reload** (15%): Graceful reconfiguration without downtime
- **Observability** (15%): Admin API, metrics, logging',
    'hard',
    'system-design',
    '["api-gateway", "plugin-system", "proxy", "circuit-breaker", "middleware"]',
    120,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 031: Hard / Backend - Reactive Database with Query Subscriptions
-- Why AI can't one-shot: Live query invalidation requires tracking which
-- rows satisfy each subscription's WHERE clause. Combine this with
-- transactions, conflict resolution, and efficient incremental updates
-- and you get a system where bugs only appear under specific mutation
-- + subscription interaction patterns.
-- ============================================================
(
    'seed_challenge_031',
    'system',
    'Reactive Database with Live Queries',
    'reactive-database',
    'Build an in-memory database with SQL-like queries AND real-time subscriptions that push incremental updates when underlying data changes.',
    '# Reactive Database with Live Queries

## Objective
Build a database where queries are not just one-shot — they''re **live**. When you subscribe to a query, you get the initial results AND real-time updates whenever the underlying data changes. Think Firebase Realtime Database meets SQL.

## Core Concept
```javascript
// One-shot query (traditional)
const users = db.query("SELECT * FROM users WHERE age > 25");

// Live query (reactive) — this is what makes this challenge hard
const subscription = db.subscribe(
    "SELECT * FROM users WHERE age > 25 ORDER BY name",
    (changes) => {
        // Called whenever the result set changes
        // changes = { added: [...], removed: [...], updated: [...] }
        console.log("Results changed:", changes);
    }
);

// This INSERT triggers the subscription callback:
db.exec("INSERT INTO users (name, age) VALUES (''Alice'', 30)");
// → callback fires with: { added: [{ name: "Alice", age: 30 }] }

// This UPDATE triggers it too:
db.exec("UPDATE users SET age = 20 WHERE name = ''Bob''");
// → If Bob was 28 before: callback fires with: { removed: [{ name: "Bob", age: 20 }] }
// (Bob no longer matches age > 25)
```

## Requirements

### 1. Schema & DDL
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    age INTEGER,
    department TEXT,
    salary REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_age ON users(age);
CREATE INDEX idx_users_dept ON users(department);

DROP TABLE users;
DROP INDEX idx_users_age;
```

### 2. DML (Data Manipulation)
```sql
INSERT INTO users (name, email, age) VALUES (''Alice'', ''alice@test.com'', 30);
UPDATE users SET salary = 75000 WHERE department = ''engineering'';
DELETE FROM users WHERE age < 18;
```

### 3. Query Language
Support a subset of SQL:
```sql
SELECT * FROM users WHERE age > 25 AND department = ''engineering'';
SELECT department, COUNT(*) as cnt, AVG(salary) as avg_sal
FROM users
GROUP BY department
HAVING cnt > 5
ORDER BY avg_sal DESC
LIMIT 10;
SELECT u.name, o.total
FROM users u
JOIN orders o ON u.id = o.user_id
WHERE o.total > 100;
```
Support: WHERE (AND/OR/NOT, comparisons, LIKE, IN, IS NULL, BETWEEN), GROUP BY, HAVING, ORDER BY, LIMIT, JOIN (INNER, LEFT), aggregates (COUNT, SUM, AVG, MIN, MAX), aliases.

### 4. Live Query Subscriptions (The Hard Part)

#### Subscribe API
```javascript
const sub = db.subscribe(query, callback, options);
// options: { debounce: 100 } — batch changes within 100ms
sub.unsubscribe();  // Stop listening
```

#### Change Detection
When data is modified (INSERT/UPDATE/DELETE), the engine must:
1. Determine which active subscriptions are affected
2. Compute the **incremental change** (added/removed/updated rows) — NOT re-execute the full query
3. Push changes to the subscription callback

#### Efficiency Requirements
- **Don''t re-run the full query** on every mutation. If you have 10,000 users and one is inserted, you should evaluate that ONE row against active subscriptions, not scan all 10,000.
- **Track which columns each subscription depends on**. If a subscription is `WHERE age > 25`, an `UPDATE ... SET name = ''...''` should NOT trigger it (name column irrelevant).
- **Handle GROUP BY subscriptions**: If subscribed to `SELECT department, COUNT(*) FROM users GROUP BY department`, an INSERT must update the count for the affected department only.
- **Handle JOIN subscriptions**: If subscribed to a JOIN query, mutations to EITHER table should trigger appropriate updates.

#### Edge Cases
- Subscription with ORDER BY + LIMIT: An INSERT might push an existing row OUT of the top-N results
- Subscription with aggregate: UPDATE a row so it no longer matches WHERE → aggregate values change
- Multiple subscriptions on same table: One mutation triggers callbacks for all matching subscriptions
- Subscription unsubscribed during callback execution → no crash, no further callbacks

### 5. Transactions
```javascript
db.transaction((tx) => {
    tx.exec("UPDATE accounts SET balance = balance - 100 WHERE id = 1");
    tx.exec("UPDATE accounts SET balance = balance + 100 WHERE id = 2");
    // If either fails, both roll back
    // Subscriptions should fire ONCE at commit with the net changes, not per-statement
});
```

- ACID semantics (within in-memory constraints)
- Subscriptions receive batched changes at transaction commit, not per-statement
- Rolled-back transactions trigger NO subscription callbacks

### 6. Indexes
- B-tree index for equality and range lookups
- Use indexes to speed up both one-shot queries and subscription evaluation
- `EXPLAIN` command shows whether a query uses an index

### 7. API Server
```
POST   /exec                    # Execute SQL statement
POST   /query                   # Execute query, return results
WS     /subscribe               # WebSocket for live queries
GET    /tables                  # List tables and schemas
GET    /subscriptions           # List active subscriptions
GET    /stats                   # Query stats, table sizes, index usage
POST   /transaction             # Execute transaction (array of statements)
```

WebSocket protocol:
```json
// Client sends:
{ "action": "subscribe", "id": "sub1", "query": "SELECT * FROM users WHERE age > 25" }

// Server sends initial results:
{ "id": "sub1", "type": "initial", "rows": [...] }

// Server sends incremental updates:
{ "id": "sub1", "type": "changes", "added": [...], "removed": [...], "updated": [...] }

// Client unsubscribes:
{ "action": "unsubscribe", "id": "sub1" }
```

## Verification Scenarios
1. Subscribe to `WHERE age > 25`, insert user with age 30 → callback with `added`
2. Subscribe to `WHERE age > 25`, update user from age 30 to 20 → callback with `removed`
3. Subscribe to `GROUP BY department`, insert user → only affected department''s count changes
4. Subscribe to JOIN query, insert into child table → callback fires correctly
5. Subscribe with `ORDER BY name LIMIT 5`, insert user that should be in top 5 → one added, one removed (pushed out)
6. Transaction with 3 INSERTs → subscription fires ONCE with all 3 rows
7. Transaction that rolls back → NO subscription callback
8. Modify column that subscription doesn''t depend on → NO callback (efficiency test)
9. 100 active subscriptions, 1 INSERT → only relevant subscriptions fire (not all 100)

## Constraints
- Node.js or Python
- No database engines (SQLite, DuckDB, etc.)
- No reactive libraries (RxJS, etc.) — implement the reactive layer yourself
- WebSocket for live subscriptions
- In-memory storage

## Evaluation Criteria
- **Live query correctness** (30%): Incremental changes match what a full re-query would show
- **Efficiency** (25%): Doesn''t re-run full queries; tracks column dependencies; uses indexes
- **Transaction support** (15%): ACID semantics, batched subscription notifications
- **Query engine** (15%): Correct SQL subset implementation
- **Edge cases** (15%): ORDER BY+LIMIT pushout, rolled-back transactions, concurrent subscriptions',
    'hard',
    'backend',
    '["database", "reactive", "live-queries", "sql", "subscriptions"]',
    120,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 032: Hard / Fullstack - Visual Workflow Builder
-- Why AI can't one-shot: Combines a drag-and-drop canvas (hit testing,
-- connection routing, zoom/pan), a DAG execution engine, a node type
-- registry with runtime type checking on edges, and undo/redo with
-- structural changes — all interacting simultaneously.
-- ============================================================
(
    'seed_challenge_032',
    'system',
    'Visual Workflow Automation Builder',
    'workflow-builder',
    'Build a node-based visual workflow editor with drag-and-drop, typed connections, a DAG execution engine, and undo/redo support.',
    '# Visual Workflow Automation Builder

## Objective
Build a visual programming environment where users construct workflows by dragging nodes onto a canvas, connecting them, configuring each node, and executing the resulting pipeline. Think Zapier/n8n meets a visual programming language.

## Architecture

```
┌──────────────────────────────────────────────┐
│                  Canvas (Frontend)            │
│  ┌──────┐    ┌──────────┐    ┌──────────┐   │
│  │HTTP  │───▶│Transform │───▶│  Send    │   │
│  │Trigger│    │  JSON    │    │  Email   │   │
│  └──────┘    └──────────┘    └──────────┘   │
│       ↘                                      │
│        ┌──────────┐    ┌──────────┐          │
│        │ Filter   │───▶│  Log to  │          │
│        │ Records  │    │  File    │          │
│        └──────────┘    └──────────┘          │
└──────────────────────────────────────────────┘
                    ↓
         [Execution Engine (Backend)]
```

## Requirements

### 1. Canvas & Node Editor (Frontend)

#### Canvas
- **Infinite canvas** with pan (drag background) and zoom (scroll wheel, pinch)
- **Grid snapping**: Nodes snap to a 20px grid
- **Minimap**: Small overview in corner showing all nodes
- **Multi-select**: Click+drag to select multiple nodes, move as group
- **Keyboard shortcuts**: Delete (remove selected), Ctrl+A (select all), Ctrl+Z/Y (undo/redo), Ctrl+C/V (copy/paste nodes)

#### Nodes
- Drag nodes from a sidebar palette onto the canvas
- Each node has:
  - Title and icon
  - **Input ports** (left side) and **output ports** (right side)
  - Configuration panel (appears on click/double-click)
  - Status indicator (idle, running, success, error)
- Nodes are resizable by dragging corners

#### Connections
- Drag from an output port to an input port to create a connection
- **Type-safe connections**: Each port has a type (string, number, boolean, object, array, any). Only compatible types can be connected. Show red highlight on incompatible hover.
- **Connection routing**: Bezier curves that avoid overlapping nodes (basic obstacle avoidance)
- Delete connection by clicking it and pressing Delete
- **Data preview**: Hover over a connection after execution to see the data that flowed through it

### 2. Node Type Registry

Implement at least these 12 node types across 4 categories:

**Triggers (1 input triggers the workflow)**
1. **HTTP Webhook**: Listens for incoming HTTP requests. Output: request body, headers, method.
2. **Schedule (Cron)**: Triggers on a cron schedule. Output: timestamp, run count.
3. **Manual Trigger**: Button to trigger manually. Output: timestamp.

**Data Processing**
4. **Transform/Map**: Apply a JavaScript expression to transform data. Config: expression string. Input: any → Output: any.
5. **Filter**: Pass data through only if condition is met. Config: condition expression. Input: any → Output: any (or nothing if filtered).
6. **Split Array**: Take an array input and emit items one-by-one. Input: array → Output: single item (runs downstream once per item).
7. **Merge**: Wait for inputs from ALL connected upstream nodes, then combine into one object. Multiple inputs → single output.

**Integrations (simulated)**
8. **HTTP Request**: Make an HTTP call. Config: URL, method, headers, body template. Input: trigger data → Output: response.
9. **Send Email** (simulated): Config: to, subject, body template. Input: data for template → Output: send result.
10. **Read/Write File**: Config: file path, operation (read/write/append). Output: file contents or write confirmation.

**Logic**
11. **If/Else Branch**: Route data down different paths based on condition. Config: condition. One input → two outputs (true/false).
12. **Delay**: Wait for N seconds before passing data through. Config: delay seconds.

Each node type defines:
```javascript
{
    type: "http-request",
    category: "integrations",
    label: "HTTP Request",
    icon: "🌐",
    inputs: [{ name: "trigger", type: "object" }],
    outputs: [{ name: "response", type: "object" }],
    configSchema: {
        url: { type: "string", required: true },
        method: { type: "enum", options: ["GET", "POST", "PUT", "DELETE"] },
        headers: { type: "key-value" },
        body: { type: "json-template" }
    },
    execute: async (input, config, ctx) => { ... }
}
```

### 3. Execution Engine (Backend)

#### DAG Execution
- Parse the canvas graph into a DAG
- **Topological execution**: Respect dependency order
- **Parallel execution**: Independent branches run concurrently
- **Cycle detection**: Reject workflows with cycles (show error on canvas)

#### Execution Flow
```javascript
// 1. Trigger fires (webhook receives request)
// 2. Engine resolves execution order
// 3. Each node executes with upstream data as input
// 4. Branching: If/Else sends data down one of two paths
// 5. Split: Runs downstream N times (once per array item)
// 6. Merge: Waits for all upstream nodes to complete
// 7. Results collected for each node
```

#### Error Handling
- Node execution timeout (configurable per node, default 30s)
- Error in one branch does NOT stop other branches
- Retry failed nodes (configurable: 0-3 retries with backoff)
- Error output: Nodes have an optional "error" output port for error-path handling

#### Execution Log
- Every execution run is logged with:
  - Start/end time per node
  - Input/output data per node
  - Error messages and stack traces
  - Total execution time

### 4. Undo/Redo System
Must track all canvas operations:
- Add/remove nodes
- Add/remove connections
- Move nodes (batch position changes into single undo)
- Resize nodes
- Change node configuration
- Multi-node operations (move group, delete group)

Implementation: Command pattern with inverse operations.
- Undo stack + redo stack
- Redo stack clears when a new action is performed
- Support at least 50 undo levels

### 5. Persistence & API
```
POST   /workflows               # Create workflow (save canvas state)
GET    /workflows               # List workflows
GET    /workflows/:id           # Get workflow (canvas state + config)
PUT    /workflows/:id           # Update workflow
DELETE /workflows/:id           # Delete workflow
POST   /workflows/:id/execute   # Trigger execution
GET    /workflows/:id/runs      # List execution runs
GET    /runs/:id                # Get execution run details with per-node data
GET    /runs/:id/nodes/:nodeId  # Get specific node input/output data
```

Workflow is serialized as:
```json
{
    "nodes": [
        { "id": "n1", "type": "http-webhook", "position": { "x": 100, "y": 200 }, "config": {...} }
    ],
    "connections": [
        { "from": { "nodeId": "n1", "port": "response" }, "to": { "nodeId": "n2", "port": "trigger" } }
    ]
}
```

### 6. Template Workflows
Provide 3 pre-built workflow templates:
1. **API → Transform → Email**: Webhook receives data, transforms it, sends email notification
2. **Schedule → HTTP → Filter → File**: Cron-triggered API polling, filter new items, write to file
3. **Webhook → Branch → (Email OR Log)**: Route based on request content

## Verification Scenarios
1. **Basic flow**: Create 3-node workflow, execute, verify data flows correctly
2. **Branching**: If/Else routes data correctly based on condition
3. **Parallel execution**: Two independent branches execute concurrently
4. **Split + Merge**: Array of 5 items → split → process each → merge results
5. **Type safety**: Try connecting string output to number input → rejected
6. **Undo/Redo**: Add 5 nodes, undo 3 times, verify 2 nodes remain, redo 1, verify 3 nodes
7. **Error handling**: Node fails → error branch executes → main branch continues
8. **Persistence**: Save workflow, reload page, verify canvas state restored exactly

## Constraints
- Frontend: Vanilla JS or React (render canvas with HTML/SVG, not `<canvas>`)
- Backend: Node.js or Python
- No workflow libraries (n8n, Node-RED, etc.)
- No canvas/diagramming libraries (ReactFlow, JointJS, etc.) — build the canvas yourself
- In-memory storage
- WebSocket for real-time execution status updates on canvas

## Evaluation Criteria
- **Canvas UX** (25%): Pan/zoom, drag-and-drop, connection drawing, visual polish
- **Execution engine** (25%): DAG resolution, parallel execution, split/merge, error handling
- **Type system** (15%): Port types, connection validation, runtime type checking
- **Undo/Redo** (15%): Correct command pattern, handles all operations
- **Node variety** (10%): All 12 node types work correctly
- **Persistence** (10%): Save/load preserves exact canvas state',
    'hard',
    'fullstack',
    '["workflow", "dag", "visual-programming", "drag-and-drop", "automation"]',
    120,
    NULL,
    '{}',
    1,
    1
);

PRAGMA foreign_keys = ON;