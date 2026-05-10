# MemoryLens

MemoryLens is an AI-powered photo organizer with:

- scene classification using Places365
- natural language photo search using CLIP
- event album generation using CLIP embeddings plus clustering

## Project Structure

```text
MemoryLens/
├── frontend/   # HTML, CSS, JavaScript client
├── backend/    # Flask API, auth, uploads, jobs, tests, migrations
├── ml/         # ML inference modules and model assets
└── .env.example
```

## What This Upgrade Added

- backend configuration moved to environment variables
- restricted CORS and environment-controlled debug mode
- structured request logging and centralized error handling
- stronger auth with refresh tokens and rate limiting
- private authenticated photo delivery
- lightweight background jobs for photo processing and event organization
- PostgreSQL-first embedding storage using pgvector
- legacy CLIP embedding migration path for older rows
- local Docker Compose setup for PostgreSQL + pgvector as the only supported database
- Flask CLI command path for pgvector status and backfills
- EXIF capture-time ingestion for better event grouping
- Flask-Migrate scaffolding and an initial migration file
- frontend polling and processing-state UI for long-running upload and event jobs
- event album rename, merge, and split workflows
- automated backend tests, including a runnable `unittest` suite
- a lightweight `/admin/health` endpoint and UI page for PostgreSQL, pgvector, and model readiness checks

## Backend Setup

1. Create `.env` from `.env.example`.
2. Install dependencies:

```bash
cd backend
pip install -r requirements.txt
pip install git+https://github.com/openai/CLIP.git
```

3. Set the Flask app:

```bash
set FLASK_APP=app:create_app
```

4. Apply migrations:

```bash
flask db upgrade
```

5. Start the backend:

```bash
python app.py
```

## PostgreSQL Setup

PostgreSQL is now required for local development and runtime. `DATABASE_URL` must be set to a PostgreSQL database.

The repo includes a ready-to-run PostgreSQL + pgvector container.

1. Start PostgreSQL:

```bash
docker compose up -d postgres
```

2. In `.env`, keep the PostgreSQL URL enabled:

```bash
DATABASE_URL=postgresql://memorylens:memorylens@127.0.0.1:5432/memorylens
VECTOR_BACKEND=pgvector
```

3. Apply migrations:

```bash
cd backend
flask db upgrade
```

4. Start the backend:

```bash
python app.py
```

At startup the terminal will log which database is active:

- `[DB] PostgreSQL fully active`

The backend will also report vector readiness:

- `[VECTOR] pgvector enabled`

You can inspect and backfill vectors with:

- `flask vectors status`
- `flask vectors backfill`

If you still have legacy SQLite files from earlier runs and want to move that data into PostgreSQL once, use the importer:

```bash
cd backend
python scripts/import_sqlite_to_postgres.py
```

It will:

- import users, events, photos, and jobs into PostgreSQL
- reuse existing PostgreSQL rows when it finds the same user or photo
- verify the import result in PostgreSQL
- delete the SQLite source files afterward so the project stays PostgreSQL-only

If any historical photo file is already missing from `backend/uploads`, the script will warn you, but the database row will still be imported into PostgreSQL.

For ongoing protection, use the backup command to create a PostgreSQL dump plus an optional uploads archive:

```bash
cd backend
python scripts/backup_postgres.py
```

By default it writes a timestamped backup set into `backend/backups/`:

- a PostgreSQL custom-format dump
- a ZIP archive of the current upload files
- a JSON manifest with counts and missing-file warnings

You can also run it through Flask CLI:

```bash
flask backup create
```

If you need to keep the upload archive out of the backup, use:

```bash
flask backup create --no-uploads
```

To restore the database dump later, use `pg_restore` against a fresh PostgreSQL database. The uploads ZIP can be unpacked back into `backend/uploads/` if you want the photos visible again.

## Frontend Setup

Serve `frontend/` with Live Server or any static file server and make sure its origin is included in `FRONTEND_ORIGINS`.

For demo-time checks, open `frontend/pages/admin-health.html` to see PostgreSQL, pgvector, and model readiness in one place.

Included local origins:

- `http://127.0.0.1:5500`
- `http://localhost:5500`
- `http://127.0.0.1:3000`
- `http://localhost:3000`

## Environment Variables

Important values in `.env`:

- `SECRET_KEY`
- `JWT_SECRET_KEY`
- `DATABASE_URL` (required)
- `UPLOAD_FOLDER`
- `ML_FOLDER`
- `VECTOR_BACKEND`
- `CLIP_VECTOR_DIM`
- `FRONTEND_ORIGINS`
- `JWT_ACCESS_MINUTES`
- `JWT_REFRESH_DAYS`
- `AUTH_RATE_LIMIT`
- `TASKS_EAGER`

`TASKS_EAGER=true` is useful in tests or very small local debugging sessions. Keep it `false` for normal async behavior.

For PostgreSQL, set:

- `DATABASE_URL=postgresql://memorylens:memorylens@127.0.0.1:5432/memorylens`
- `VECTOR_BACKEND=pgvector`

## API Overview

### Auth

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`

### Photos

- `POST /photos/upload`
- `GET /photos/all`
- `GET /photos/scenes`
- `GET /photos/<id>/file`
- `DELETE /photos/<id>`

### Search

- `GET /search?q=...`

### Events

- `POST /events/organize`
- `GET /events/all`
- `GET /events/<id>/photos`
- `PATCH /events/<id>`
- `POST /events/merge`
- `POST /events/<id>/split`
- `DELETE /events/<id>`

### Jobs

- `GET /jobs/<job_id>`

### Admin

- `GET /admin/health`

Photo uploads and event organization now return job metadata immediately and continue processing in the background.

## Migrations

Migration scaffolding now lives in `backend/migrations/`, including migrations that:

- creates missing core tables on a fresh database
- adds job tracking
- adds binary embedding columns
- adds photo processing state and capture-time metadata
- backfills legacy JSON embeddings into binary storage when possible
- adds and aligns the pgvector column/index on PostgreSQL
- migrates legacy CLIP embedding storage into `clip_vector_pg` and removes old embedding columns
- supports a CLI status/backfill step for PostgreSQL vector maintenance

## Tests

Runnable backend test suite:

```bash
backend\venv\Scripts\python.exe -m unittest backend.tests.test_unittest_app -v
```

There is also a pytest-style suite in `backend/tests/` for teams that prefer pytest after installing it into the environment.

For a quick PostgreSQL smoke check, run:

```bash
cd backend
python -m unittest tests.test_smoke_postgres -v
```

That smoke file covers:

- auth
- upload
- gallery
- timeline
- events

## Remaining Next Steps

- move from in-process background threads to a durable worker queue like Celery or RQ for multi-instance deployment
- add API tests for job polling edge cases and failure recovery
- add admin/user-facing tools to manually review and re-run failed processing jobs
- collect event-grouping quality metrics from real user corrections
