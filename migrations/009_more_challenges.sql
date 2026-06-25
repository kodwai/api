-- Migration 009: Second batch of challenges (13-22)
-- Fills gaps in: system-design, data, frontend, fullstack
-- Brings total from 12 to 22

PRAGMA foreign_keys = OFF;

INSERT OR IGNORE INTO challenges (id, created_by, title, slug, description, problem_statement_md, difficulty, category, tags, time_limit_minutes, test_suite, scoring_config, is_public, is_featured)
VALUES
-- ============================================================
-- Challenge 013: Easy / Backend - URL Shortener
-- ============================================================
(
    'seed_challenge_013',
    'system',
    'URL Shortener Service',
    'url-shortener',
    'Build a URL shortening service with custom aliases, click tracking, and expiration support.',
    '# URL Shortener Service

## Objective
Build a working URL shortener API — the classic backend exercise, done properly.

## Requirements
1. **POST /shorten** - Create a short URL
   - Body: `{ "url": "https://example.com/very/long/path", "alias": "my-link" (optional), "expires_in": 3600 (optional, seconds) }`
   - Returns: `{ "short_url": "http://localhost:3000/abc123", "alias": "abc123", "expires_at": "..." }`
2. **GET /:alias** - Redirect to the original URL (HTTP 301)
3. **GET /stats/:alias** - Return click statistics
   - `{ "original_url": "...", "clicks": 42, "created_at": "...", "last_clicked_at": "..." }`
4. **DELETE /:alias** - Delete a short URL

## Constraints
- Use in-memory storage (no database)
- Generate short aliases using base62 encoding (a-z, A-Z, 0-9)
- Aliases must be unique — return 409 Conflict on duplicates
- Expired URLs return 410 Gone
- Validate URLs (reject invalid formats)

## Bonus
- Rate limiting: max 10 shortens per minute per IP
- QR code generation: `GET /qr/:alias` returns a QR code PNG
- Bulk shorten: `POST /shorten/batch` accepts an array

## Evaluation Criteria
- HTTP semantics (correct status codes, redirects)
- Input validation
- Code organization
- Edge case handling',
    'easy',
    'backend',
    '["api", "url-shortener", "rest"]',
    45,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 014: Easy / Data - Log File Analyzer
-- ============================================================
(
    'seed_challenge_014',
    'system',
    'Log File Analyzer',
    'log-file-analyzer',
    'Parse and analyze web server access logs to extract traffic patterns, top endpoints, and error rates.',
    '# Log File Analyzer

## Objective
Build a tool that parses web server access logs and generates insights.

## Input Format
Apache Combined Log Format:
```
127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] "GET /apache_pb.gif HTTP/1.0" 200 2326 "http://www.example.com/start.html" "Mozilla/4.08"
```

## Requirements
1. **Parse** each log line into structured data (IP, timestamp, method, path, status, size, referrer, user-agent)
2. **Generate report** with:
   - Total requests and unique visitors (by IP)
   - Requests per HTTP method (GET, POST, etc.)
   - Top 10 most visited paths
   - Status code distribution (2xx, 3xx, 4xx, 5xx)
   - Error rate (4xx + 5xx / total)
   - Traffic by hour (histogram)
   - Top 5 referrers
   - Total bandwidth (sum of response sizes)
3. **CLI interface**: `node analyzer.js access.log`
4. **Output formats**: `--format table` (default) or `--format json`

## Sample Output
```
=== Traffic Report ===
Total Requests:    14,523
Unique Visitors:   1,203
Error Rate:        3.2%
Total Bandwidth:   142.5 MB

=== Top Paths ===
/api/users         3,201 (22.0%)
/api/products      2,847 (19.6%)
/                  1,523 (10.5%)
...
```

## Constraints
- Handle files up to 100MB efficiently (stream, don''t load all into memory)
- Handle malformed lines gracefully (skip and count them)
- Use any language

## Evaluation Criteria
- Parsing robustness
- Memory efficiency (streaming)
- Report clarity and usefulness
- Error handling',
    'easy',
    'data',
    '["parsing", "data-analysis", "cli", "logs"]',
    45,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 015: Easy / Frontend - Theme Switcher
-- ============================================================
(
    'seed_challenge_015',
    'system',
    'Theme Switcher with CSS Variables',
    'theme-switcher',
    'Build a theme system using CSS custom properties with light/dark/custom themes, smooth transitions, and localStorage persistence.',
    '# Theme Switcher with CSS Variables

## Objective
Create a theming system that uses CSS custom properties for instant, flicker-free theme switching.

## Requirements
1. **Three built-in themes**: Light, Dark, and a custom "Sunset" theme
2. **CSS Variables** for all theme-able properties:
   - `--color-bg`, `--color-text`, `--color-primary`, `--color-secondary`
   - `--color-border`, `--color-surface`, `--color-muted`
   - `--font-body`, `--font-heading`
   - `--radius`, `--shadow`
3. **Theme toggle** component (dropdown or segmented control)
4. **Smooth transitions** when switching (300ms on background/color)
5. **Persistence**: Save selection to `localStorage`, apply on page load WITHOUT flash
6. **System preference**: Default to OS dark/light via `prefers-color-scheme`
7. **Demo page** showcasing the theme on:
   - Navigation bar, buttons (primary, secondary, outline)
   - Card components, form inputs
   - Typography (h1-h4, body, muted text)

## Anti-flash technique
The theme must be applied BEFORE the page renders. No white flash on dark theme reload.

## Constraints
- Vanilla HTML/CSS/JS (no frameworks, no Tailwind)
- All styles must use CSS variables (no hardcoded colors)
- Must work without JavaScript (fallback to light theme)

## Evaluation Criteria
- No flash on page load (critical)
- CSS variable architecture
- Transition smoothness
- Accessibility (sufficient contrast ratios in all themes)',
    'easy',
    'frontend',
    '["css", "theming", "vanilla-js", "css-variables"]',
    40,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 016: Medium / System Design - Webhook Delivery System
-- ============================================================
(
    'seed_challenge_016',
    'system',
    'Webhook Delivery System',
    'webhook-delivery-system',
    'Design and implement a webhook delivery system with retry logic, signature verification, and delivery status tracking.',
    '# Webhook Delivery System

## Objective
Build a system that reliably delivers webhook events to registered endpoints.

## Requirements

### Registration API
1. `POST /webhooks` - Register a webhook endpoint
   - Body: `{ "url": "https://example.com/webhook", "events": ["order.created", "order.updated"], "secret": "whsec_..." }`
2. `GET /webhooks` - List registered webhooks
3. `DELETE /webhooks/:id` - Remove a webhook
4. `GET /webhooks/:id/deliveries` - View delivery history

### Event Dispatch
1. `POST /events` - Trigger an event
   - Body: `{ "type": "order.created", "data": { "order_id": "123", "amount": 99.99 } }`
2. System finds all webhooks subscribed to this event type
3. Delivers payload to each endpoint via HTTP POST

### Delivery Requirements
- **Signature**: HMAC-SHA256 of the payload using the webhook''s secret, sent in `X-Webhook-Signature` header
- **Timestamp**: Include `X-Webhook-Timestamp` to prevent replay attacks
- **Retries**: On failure (non-2xx or timeout), retry up to 5 times:
  - Attempt 1: immediate
  - Attempt 2: 10 seconds
  - Attempt 3: 1 minute
  - Attempt 4: 10 minutes
  - Attempt 5: 1 hour
- **Timeout**: 30 seconds per delivery attempt
- **Delivery log**: Store status (success/failed), response code, attempt count, timestamps

### Dashboard (optional bonus)
- Simple HTML page showing delivery status per webhook

## Constraints
- Use any language/framework
- In-memory storage is fine
- Must actually make HTTP requests to the registered URLs

## Evaluation Criteria
- Security (signature implementation)
- Reliability (retry logic)
- API design
- Delivery tracking completeness',
    'medium',
    'system-design',
    '["webhooks", "api", "system-design", "security"]',
    75,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 017: Medium / Fullstack - Markdown Note App
-- ============================================================
(
    'seed_challenge_017',
    'system',
    'Markdown Note-Taking App',
    'markdown-note-app',
    'Build a full-stack note-taking app with live Markdown preview, search, and folder organization.',
    '# Markdown Note-Taking App

## Objective
Build a minimal but functional note-taking app with Markdown support.

## Requirements

### Backend API
1. **CRUD** for notes: create, read, update, delete
2. **Folders**: Notes can be organized into folders
3. **Search**: Full-text search across note titles and content
4. **Auto-save**: Accept partial updates (PATCH) for auto-save

### Frontend
1. **Sidebar**: Folder tree + note list
2. **Editor**: Split-pane with Markdown editor (left) and live preview (right)
3. **Toolbar**: Bold, italic, heading, link, code, list buttons
4. **Search bar**: Filter notes by keyword
5. **Keyboard shortcuts**: Cmd/Ctrl+S (save), Cmd/Ctrl+B (bold), Cmd/Ctrl+N (new note)

### Data Model
```
Folder: { id, name, parent_id }
Note: { id, title, content, folder_id, created_at, updated_at }
```

## Technical Constraints
- Backend: Any language (Node.js, Python, etc.)
- Frontend: Any framework or vanilla JS
- In-memory storage (no database required)
- Markdown rendering: use a library (marked, markdown-it, etc.)

## Bonus
- Note pinning (pinned notes appear first)
- Word count in status bar
- Export note as HTML or PDF
- Dark mode

## Evaluation Criteria
- UI/UX quality (does it feel good to use?)
- Editor responsiveness
- Search implementation
- Code structure (frontend/backend separation)',
    'medium',
    'fullstack',
    '["fullstack", "markdown", "crud", "react"]',
    90,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 018: Medium / Frontend - Data Table Component
-- ============================================================
(
    'seed_challenge_018',
    'system',
    'Sortable Data Table with Pagination',
    'data-table-component',
    'Build a reusable data table component with sorting, filtering, pagination, and row selection.',
    '# Sortable Data Table with Pagination

## Objective
Build a production-quality data table component from scratch.

## Requirements

### Core Features
1. **Column sorting**: Click header to sort (asc → desc → none)
2. **Filtering**: Text input per column header for filtering
3. **Pagination**: Page size selector (10, 25, 50, 100) + prev/next navigation
4. **Row selection**: Checkbox column with select-all support
5. **Responsive**: Horizontal scroll on mobile, sticky first column

### Component API
```jsx
<DataTable
  data={users}
  columns={[
    { key: "name", label: "Name", sortable: true, filterable: true },
    { key: "email", label: "Email", sortable: true, filterable: true },
    { key: "role", label: "Role", sortable: true },
    { key: "created", label: "Joined", sortable: true, render: (val) => formatDate(val) },
  ]}
  pageSize={25}
  onSelectionChange={(selected) => console.log(selected)}
  emptyState={<p>No users found</p>}
/>
```

### Sample Data
- Generate 500 mock users with: name, email, role (Admin/Editor/Viewer), created_at, status (active/inactive)

### Performance
- Must handle 10,000 rows without jank
- Use virtualization OR efficient DOM rendering
- Debounce filter inputs (300ms)

## Constraints
- Use React (TypeScript preferred)
- No table libraries (no TanStack Table, AG Grid, etc.)
- Style it to look professional

## Evaluation Criteria
- Feature completeness
- Performance with large datasets
- Component API design
- Visual polish',
    'medium',
    'frontend',
    '["react", "component", "table", "typescript"]',
    75,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 019: Hard / System Design - Event Sourcing Store
-- ============================================================
(
    'seed_challenge_019',
    'system',
    'Event Sourcing Store',
    'event-sourcing-store',
    'Implement an event sourcing system with an append-only event store, projections, and snapshot support.',
    '# Event Sourcing Store

## Objective
Build an event sourcing library that can be used as the foundation for any domain.

## Requirements

### Event Store
1. `store.append(streamId, events, expectedVersion)` - Append events to a stream
   - **Optimistic concurrency**: Reject if `expectedVersion` does not match current version
2. `store.getStream(streamId, fromVersion?)` - Read events from a stream
3. `store.getAllEvents(fromPosition?)` - Read all events globally (for projections)
4. Each event has: `{ streamId, type, data, metadata, version, position, timestamp }`

### Aggregate Pattern
```javascript
class BankAccount {
  static create(id, owner) {
    return [{ type: "AccountCreated", data: { id, owner, balance: 0 } }];
  }
  static deposit(state, amount) {
    if (amount <= 0) throw new Error("Invalid amount");
    return [{ type: "MoneyDeposited", data: { amount } }];
  }
  static withdraw(state, amount) {
    if (amount > state.balance) throw new Error("Insufficient funds");
    return [{ type: "MoneyWithdrawn", data: { amount } }];
  }
  static apply(state, event) {
    switch (event.type) {
      case "AccountCreated": return { ...event.data };
      case "MoneyDeposited": return { ...state, balance: state.balance + event.data.amount };
      case "MoneyWithdrawn": return { ...state, balance: state.balance - event.data.amount };
    }
  }
}
```

### Projections
1. **Synchronous projection**: Build read models from event stream
2. Example: `BalanceProjection` that maintains current balance per account
3. Projections must be rebuildable from scratch

### Snapshots
1. `store.saveSnapshot(streamId, state, version)` - Save aggregate state at a version
2. `store.loadAggregate(streamId)` - Load from snapshot + replay newer events
3. Snapshots reduce replay time for long-lived aggregates

## Constraints
- In-memory storage
- Must handle concurrent appends safely
- Write at least 20 test cases covering happy paths and edge cases

## Evaluation Criteria
- Correctness of event ordering and versioning
- Concurrency control (optimistic locking)
- Snapshot/replay efficiency
- Test comprehensiveness
- API design clarity',
    'hard',
    'system-design',
    '["event-sourcing", "system-design", "cqrs", "architecture"]',
    90,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 020: Medium / Backend - GraphQL API from Scratch
-- ============================================================
(
    'seed_challenge_020',
    'system',
    'GraphQL API from Scratch',
    'graphql-api-scratch',
    'Build a GraphQL API for a bookstore with queries, mutations, relationships, and pagination.',
    '# GraphQL API from Scratch

## Objective
Build a fully functional GraphQL API for a bookstore.

## Data Model
```
Author: { id, name, bio, born_year }
Book: { id, title, author_id, genre, published_year, rating, price }
Review: { id, book_id, reviewer_name, rating, comment, created_at }
```

## Requirements

### Queries
1. `books(genre, minRating, limit, offset)` - List books with filtering and pagination
2. `book(id)` - Get a single book with its author and reviews
3. `authors` - List all authors
4. `author(id)` - Get an author with their books
5. `search(query)` - Search books and authors by name/title

### Mutations
1. `addBook(input)` - Add a new book
2. `addReview(bookId, input)` - Add a review to a book
3. `updateBook(id, input)` - Update book details
4. `deleteBook(id)` - Delete a book and its reviews

### Relationships
- Book → Author (many-to-one)
- Book → Reviews (one-to-many)
- Author → Books (one-to-many)

### Features
- **Input validation** on mutations
- **N+1 prevention**: Implement DataLoader pattern or batch loading
- **Error handling**: Proper GraphQL error format
- **Pagination**: Cursor-based or offset-based on book listings

## Constraints
- Use any GraphQL server library (Apollo, graphql-yoga, Mercurius, etc.)
- In-memory data store with seed data (5 authors, 15 books, 20 reviews)
- Include a GraphQL playground/sandbox

## Evaluation Criteria
- Schema design quality
- N+1 query prevention
- Input validation and error handling
- Code organization',
    'medium',
    'backend',
    '["graphql", "api", "backend", "data-loading"]',
    75,
    NULL,
    '{}',
    1,
    0
),
-- ============================================================
-- Challenge 021: Hard / Fullstack - Real-Time Kanban Board
-- ============================================================
(
    'seed_challenge_021',
    'system',
    'Real-Time Kanban Board',
    'realtime-kanban-board',
    'Build a collaborative Kanban board with drag-and-drop, real-time sync between users, and optimistic updates.',
    '# Real-Time Kanban Board

## Objective
Build a collaborative task board where multiple users see changes in real-time.

## Requirements

### Backend
1. **REST API** for CRUD operations on boards, columns, and cards
2. **WebSocket** server for real-time sync
3. **Data model**:
   - Board: `{ id, name }`
   - Column: `{ id, board_id, name, position }`
   - Card: `{ id, column_id, title, description, assignee, labels, position }`

### Frontend
1. **Board view**: Columns laid out horizontally, cards stacked vertically
2. **Drag and drop**: Move cards between columns and reorder within columns
3. **Real-time sync**: Changes from one browser tab appear instantly in another
4. **Optimistic updates**: UI updates immediately, syncs in background
5. **Card modal**: Click a card to edit title, description, assignee, labels
6. **Add column**: Button to add new columns to the board
7. **Add card**: Button at bottom of each column to add cards

### Real-Time Events
- `card.moved` - Card moved to different column or reordered
- `card.created` / `card.updated` / `card.deleted`
- `column.created` / `column.reordered`

### Conflict Resolution
- Last-write-wins for card content edits
- Server-authoritative for card positions (prevent desync)

## Constraints
- Any language/framework
- WebSocket for real-time (not polling)
- Must work with 2+ browser tabs simultaneously
- In-memory storage

## Evaluation Criteria
- Real-time sync correctness
- Drag-and-drop UX quality
- Optimistic update handling
- Code architecture (clean separation of concerns)',
    'hard',
    'fullstack',
    '["websocket", "realtime", "kanban", "drag-and-drop"]',
    90,
    NULL,
    '{}',
    1,
    1
),
-- ============================================================
-- Challenge 022: Easy / Backend - Middleware Chain
-- ============================================================
(
    'seed_challenge_022',
    'system',
    'HTTP Middleware Chain',
    'http-middleware-chain',
    'Build an Express-style middleware system from scratch with request/response pipeline, error handling, and route matching.',
    '# HTTP Middleware Chain

## Objective
Implement the middleware pattern used by Express.js, Koa, and similar frameworks — from scratch.

## Requirements

### Core Framework
```javascript
const app = createApp();

// Global middleware
app.use(logger);
app.use(cors({ origin: "*" }));

// Route-specific middleware
app.get("/api/users", auth, listUsers);
app.post("/api/users", auth, adminOnly, createUser);

// Error handler (4 args)
app.use((err, req, res, next) => {
  res.status(500).json({ error: err.message });
});

app.listen(3000);
```

### Middleware Signature
```javascript
function middleware(req, res, next) {
  // do something
  next(); // call next middleware
  // or next(error) to skip to error handler
}
```

### Must Implement
1. `app.use(middleware)` - Add global middleware
2. `app.get/post/put/delete(path, ...handlers)` - Route-specific handlers
3. **Path matching**: Exact match + parameter extraction (`/users/:id`)
4. **next()**: Call next middleware in chain
5. **next(error)**: Skip to error-handling middleware
6. **res.json(data)**: Send JSON response with Content-Type header
7. **res.status(code)**: Set HTTP status code (chainable)
8. **Early exit**: If a middleware sends a response, skip remaining middleware

### Built-in Middleware to Create
1. **Logger**: Logs `METHOD /path STATUS TIME_MSms`
2. **CORS**: Sets Access-Control headers
3. **Auth**: Checks `Authorization: Bearer <token>` header

## Constraints
- Node.js, using only `http` module (no Express, no frameworks)
- Must handle async middleware (middleware that returns promises)
- Must match routes with URL parameters

## Evaluation Criteria
- Middleware chain correctness
- Route matching implementation
- Error handling flow
- Clean API design',
    'easy',
    'backend',
    '["node", "middleware", "http", "framework"]',
    50,
    NULL,
    '{}',
    1,
    0
);

PRAGMA foreign_keys = ON;
