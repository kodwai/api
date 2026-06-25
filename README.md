# kodwai — API

The backend API for [kodwai](https://kodwai.com), the AI-agent coding platform.

## Tech Stack

- **FastAPI** (Python 3.12+)
- **Turso/libSQL** database
- **JWT** authentication
- **AES-256-GCM** API key encryption

## Getting Started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API runs at [http://localhost:8000](http://localhost:8000). Docs at `/docs`.

### Environment Variables

Copy `.env.example` to `.env.local`:

```
TURSO_DATABASE_URL=
TURSO_AUTH_TOKEN=
JWT_SECRET=
ENCRYPTION_KEY=
RESEND_API_KEY=
CLIENT_URL=http://localhost:3000
```

## Architecture

### Routers
- `auth` — Signup, login, email verification
- `organizations` — Company team management
- `api_keys` — Anthropic key encryption/storage
- `projects` — Interview challenge definitions
- `sessions` — Interview session lifecycle
- `scores` — AI + manual scoring
- `proxy` — Anthropic API proxy with cost tracking
- `challenges` — Developer challenge library
- `submissions` — Developer challenge submissions
- `leaderboard` — Global rankings
- `developer_profiles` — Public profiles
- `badges` — Achievement system

### Admin Routers (`/api/admin/*`)
- `auth` — Admin login with separate JWT
- `dashboard` — Platform stats
- `users` — User management (verify, ban, roles)
- `challenges` — Challenge CRUD
- `organizations` — Org overview
- `projects` — Interview project overview
- `sessions` — Session monitoring + force-end
- `submissions` — Re-scoring
- `analytics` — Time-series data
- `badges` — Badge CRUD
- `api_keys` — Key overview
- `system` — Health check + audit log
- `leaderboard` — Rank management

### Services
- `auth_service` — User registration/login
- `scoring_service` — AI interview scoring
- `challenge_scoring` — Developer challenge scoring (objective + analytical)
- `badge_engine` — Badge criteria evaluation
- `encryption_service` — AES-256-GCM key encryption
- `email_service` — Transactional emails via Resend
- `session_cleanup` — Background expired session handler

## Database

Turso (libSQL) with auto-applied SQL migrations in `migrations/`. Tables:

`users`, `organizations`, `api_keys`, `projects`, `sessions`, `session_events`, `file_changes`, `final_files`, `scores`, `comments`, `invitations`, `challenges`, `developer_profiles`, `submissions`, `leaderboard_entries`, `badges`, `developer_badges`, `admin_audit_log`

## License

This project is licensed under the **PolyForm Noncommercial License 1.0.0**.

You may use, modify, and distribute it for personal, educational, research, and noncommercial purposes. **Commercial use, including using this code to operate or promote your own product, is not permitted** without a separate commercial license from kodwai.

See [LICENSE](LICENSE) for the full text. For commercial licensing inquiries, contact **hakan@ksenda.com**.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security issues: see [SECURITY.md](SECURITY.md).
