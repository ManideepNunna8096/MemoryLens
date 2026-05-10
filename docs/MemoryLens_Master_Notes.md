# MemoryLens Master Notes

## 1. Project Overview
- **Project Name:** MemoryLens
- **Main Purpose:** An AI-powered photo organizer that classifies photos, searches them semantically, groups them into event albums, detects duplicates, and helps users manage gallery folders.
- **Problem Statement:** Large photo collections are hard to search and organize manually. MemoryLens solves this by combining scene classification, vector search, album grouping, duplicate detection, and timeline browsing.
- **Why this project exists:** To turn a plain image library into a smart, searchable photo workspace.
- **Real-world use case:** A user uploads family, campus, travel, and work photos and later finds them by text like `beach trip` or browses them by year/month/day.
- **Target users:** Students, families, reviewers, and anyone with a growing photo library.
- **Main features:** Login, upload, AI classification, CLIP search, event albums, custom folders, timeline view, duplicate detection, share/export, backup, and health checks.
- **Project goals:** Fast photo organization, good usability, PostgreSQL-first storage, and a polished product suitable for final-year review.
- **What problem it solves:** It replaces manual sorting with an AI-assisted workflow that is easier to browse, search, and maintain.

## 2. Full Architecture Explanation
- **Overall architecture:** Static frontend pages call a Flask backend API. The backend stores metadata in PostgreSQL, files on disk, embeddings in pgvector, and long-running work in background jobs.
- **Frontend architecture:** Plain HTML, CSS, and JavaScript pages. A shared `api.js` file handles auth, API calls, downloads, and image hydration.
- **Backend architecture:** Flask app factory with blueprints for auth, photos, search, timeline, events, duplicates, folders, jobs, share, and admin.
- **Database architecture:** PostgreSQL is the runtime database. It stores users, photos, events, jobs, and vector embeddings through `pgvector`.
- **Service layer:** ML helpers, vector search, duplicate detection, backup creation, share tokens, event metadata, and date helpers are split into utility modules.
- **API communication flow:** Browser page -> `frontend/js/api.js` -> Flask route -> SQLAlchemy models/filesystem/ML -> JSON or file response.
- **Authentication flow:** Register/login returns JWT access and refresh tokens. The frontend stores them in `localStorage` and refreshes them when needed.
- **Data storage flow:** Image files go to `backend/uploads`. Metadata goes to PostgreSQL. Backups go to `backend/backups`.
- **Request-response lifecycle:** User action triggers an API request, backend validates JWT, reads/writes DB/files, returns JSON or download, frontend updates UI and may poll `/jobs/<id>`.

### Simplified architecture diagram
```text
User Browser -> Frontend HTML/CSS/JS -> api.js + JWT
            -> Flask Blueprints -> PostgreSQL + pgvector
            -> backend/uploads -> AI helpers -> job status/result
```

## 3. Complete Folder Structure Explanation
- **Top level**
  - `.env.example`: Example environment variables.
  - `.gitignore`: Ignores uploads, backups, venv, caches, and generated files.
  - `docker-compose.yml`: Optional PostgreSQL + pgvector setup.
  - `README.md`: Setup, backup, migration, and usage documentation.
- **`backend/`**
  - Flask app, database models, routes, ML orchestration, scripts, migrations, tests, uploads, backups, and the local venv.
- **`backend/app.py`**
  - App factory, extension setup, blueprints, logging, CLI commands, and startup.
- **`backend/config/`**
  - Environment-based app configuration loader.
- **`backend/models/`**
  - SQLAlchemy models for users, photos, events, and jobs.
- **`backend/routes/`**
  - API blueprints for each feature area.
- **`backend/scripts/`**
  - One-time SQLite-to-PostgreSQL import, PostgreSQL backup script, and Windows bootstrap helper.
- **`backend/tests/`**
  - `unittest` smoke suite and pytest-style tests.
- **`backend/migrations/`**
  - Alembic migration history.
- **`backend/uploads/`**
  - Stored image files.
- **`backend/backups/`**
  - Generated database dumps, upload archives, and manifests.
- **`backend/instance/`**
  - Legacy/generated runtime folder; SQLite DB files were removed during migration.
- **`backend/utils/`**
  - Logging helper and support utilities.
- **`frontend/`**
  - Static client application.
- **`frontend/css/`**
  - Shared theme and component styles.
- **`frontend/js/`**
  - Shared API wrapper and page-specific logic.
- **`frontend/pages/`**
  - Gallery, upload, search, events, timeline, duplicates, share, and health pages.
- **`ml/`**
  - Scene classifier, CLIP embeddings, event organizer, and Places365 assets.

## 4. Frontend Deep Explanation
- **HTML structure:** Each page is a standalone HTML file with a shared navigation bar and page-specific content.
- **CSS styling system:** `frontend/css/main.css` defines the dark theme, typography, cards, buttons, inputs, badges, toasts, and empty states.
- **JavaScript flow:** `frontend/js/api.js` is the shared API layer. Page scripts focus on page-specific UI logic.
- **Pages**
  - `index.html`: Sign in / register page.
  - `pages/gallery.html`: Main library, folders, photo grid, details drawer.
  - `pages/upload.html`: Drag-and-drop upload page.
  - `pages/search.html`: Semantic search page.
  - `pages/events.html`: Event album management page.
  - `pages/timeline.html`: Year/month/day browsing page.
  - `pages/duplicates.html`: Duplicate review page.
  - `pages/share.html`: Public share viewer.
  - `pages/admin-health.html`: Runtime health and backup dashboard.
- **Components:** Cards, stat blocks, chips, photo grids, modals, drawers, toasts, lightbox, and folder sidebar.
- **Event handling:** Plain DOM listeners and onclick handlers; no frontend framework is used.
- **API calling mechanism:** `api.js` attaches JWTs, refreshes expiring tokens, parses JSON, and downloads files.
- **State management:** Each page script keeps its own state in module-level variables.
- **User interaction flow:** User clicks buttons, page scripts call `Auth`, `Photos`, `Folders`, `Jobs`, `Search`, `Timeline`, `Duplicates`, `Events`, or `Shared`.
- **Upload flow:** File picker -> preview -> upload request -> job polling -> results -> gallery refresh.
- **Search flow:** Query -> CLIP text embedding -> backend similarity search -> ranked results.
- **Timeline flow:** Group by year/month/day -> preview expansion -> drilldown -> lightbox.
- **Duplicate detection flow:** Scan hashes -> group exact and similar copies -> keep or trash.
- **Event album flow:** Organize new photos -> scene/category matching -> canonical album merge -> manual album tools.

## 5. Backend Deep Explanation
- **Flask app structure:** `create_app()` loads config, validates PostgreSQL, creates directories, configures logging, CORS, JWT, limiter, SQLAlchemy, and migrations.
- **App initialization:** `backend/app.py` is the runtime entrypoint.
- **Blueprint routing:** Each feature area has its own blueprint under `/auth`, `/admin`, `/duplicates`, `/photos`, `/folders`, `/search`, `/timeline`, `/events`, `/jobs`, and `/share`.
- **Middleware:** Request logging and response timing are attached in the logging helper.
- **Extensions:** JWT, limiter, migrate, and SQLAlchemy are initialized centrally.
- **JWT/authentication:** Access and refresh JWTs are created at login/register. Protected endpoints require bearer tokens.
- **Database connection:** SQLAlchemy reads `DATABASE_URL`. PostgreSQL is mandatory; SQLite is not used at runtime.
- **Error handling:** JSON error handlers return HTTP and unexpected exceptions in API-friendly form.
- **Logging:** Structured logs include timestamp, level, and a tag like `UPLOAD`, `STEP`, `DONE`, `ERROR`, or `BACKUP`.
- **Config loading:** `config/settings.py` loads `.env` from root and backend and turns env vars into app settings.
- **Service architecture:** Heavy logic is split into helpers instead of living in routes.
- **Request handling:** Routes validate inputs, query user-owned rows, perform actions, and return JSON or downloads.
- **Response handling:** Most endpoints return JSON; exports and downloads use `send_file`.

## 6. PostgreSQL Database Notes
- **Tables**
  - `users`: account owners.
  - `photos`: image metadata, embeddings, hashes, scene labels, folder info, event link, and processing state.
  - `events`: album groups.
  - `jobs`: background work tracker.
- **Relationships**
  - `users.id -> photos.user_id`
  - `users.id -> events.user_id`
  - `users.id -> jobs.user_id`
  - `events.id -> photos.event_id`
- **Primary keys:** `users.id`, `photos.id`, `events.id`, `jobs.id`.
- **Foreign keys:** Photos and events belong to users; photos may belong to one event.
- **Constraints:** Unique email, non-null ownership fields, and state columns for safe filtering.
- **Indexes:** Hash columns and job owner columns are indexed for speed.
- **Storage logic:** Files live on disk; the database stores filenames and metadata only.
- **Query flow:** Gallery, timeline, search, and events all filter PostgreSQL rows by user and state.
- **Why PostgreSQL was chosen:** Strong relational integrity, migrations, and pgvector support.
- **How data is stored internally:** Passwords are hashed; embeddings are stored in `clip_vector_pg`; timestamps are stored as UTC-naive values and converted for display.

## 7. SQLAlchemy Models Explanation
- **`User`**
  - Purpose: account owner.
  - Fields: `id`, `name`, `email`, `password`, `created_at`.
  - Relationships: photos and jobs.
- **`Photo`**
  - Purpose: main media record.
  - Fields: filename, original filename, scene, `clip_vector_pg`, model versions, processing status/error, capture time, display name, custom folder, SHA256, dHash, favorite/archive/trash state, `user_id`, `event_id`, uploaded time.
  - Relationships: belongs to a user and optionally to an event.
  - Meaning: one uploaded image plus all AI and organization metadata.
- **`Event`**
  - Purpose: event album.
  - Fields: `id`, `label`, `dominant_scene`, `user_id`, `created_at`.
  - Relationships: many photos.
  - Meaning: a curated album grouping related photos.
- **`BackgroundJob`**
  - Purpose: tracks long-running work.
  - Fields: job id, job type, status, owner, totals, result payload, error message, timestamps.
  - Meaning: used for upload processing and event organization.

## 8. API Documentation
- **Auth**
  - `POST /auth/register`: create user, validate password, return JWTs.
  - `POST /auth/login`: verify credentials and return JWTs.
  - `POST /auth/refresh`: rotate access token.
- **Photos**
  - `POST /photos/upload`: upload one or more images.
  - `GET /photos/all`: list photos with filters.
  - `GET /photos/scenes`: return folder/scene counts.
  - `POST /photos/bulk`: favorite/archive/trash/restore/delete/move actions.
  - `POST /photos/retry`: retry failed processing.
  - `POST /photos/export`: create ZIP download.
  - `POST /photos/share`: create share token.
  - `POST /photos/<id>/rename`: rename photo.
  - `GET /photos/<id>/file`: protected file download.
  - `DELETE /photos/<id>`: permanent delete.
- **Folders**
  - `GET /folders/all`: list folders and counts.
  - `POST /folders/move-photos`: move photos between folders.
  - `POST /folders/rename`: rename folder.
  - `POST /folders/merge`: merge folders.
  - `POST /folders/delete`: delete custom folder.
- **Search**
  - `GET /search?q=...`: semantic search.
- **Timeline**
  - `GET /timeline`: grouped by year/month/day.
- **Duplicates**
  - `GET /duplicates`: duplicate groups.
  - `POST /duplicates/scan`: recompute hashes.
  - `POST /duplicates/trash`: trash duplicates.
  - `POST /duplicates/keep`: keep one and trash the rest.
- **Events**
  - `POST /events/organize`: organize new photos into matching albums.
  - `GET /events/all`: list albums.
  - `GET /events/<id>/photos`: album photos.
  - `PATCH /events/<id>`: rename album.
  - `POST /events/merge`: merge albums.
  - `POST /events/<id>/split`: split selected photos into a new album.
  - `POST /events/move-photos`: move photos between albums.
  - `POST /events/<id>/remove-photos`: remove photos from album.
  - `GET /events/<id>/export`: album ZIP download.
  - `POST /events/<id>/share`: create share token.
  - `DELETE /events/<id>`: delete album.
- **Jobs**
  - `GET /jobs/<job_id>`: poll background job progress.
- **Admin**
  - `GET /admin/health`: runtime health report.
  - `POST /admin/backup`: create PostgreSQL backup package.

## 9. YAML / Config / Environment Files
- **`docker-compose.yml`** starts PostgreSQL with pgvector.
- **`.env.example`** shows required variables and placeholders.
- **Environment variables**
  - `DATABASE_URL`
  - `SECRET_KEY`
  - `JWT_SECRET_KEY`
  - `UPLOAD_FOLDER`
  - `ML_FOLDER`
  - `VECTOR_BACKEND`
  - `CLIP_VECTOR_DIM`
  - `FRONTEND_ORIGINS`
  - `TASKS_EAGER`
- **Why config separation exists:** It keeps secrets out of code and lets the same app run in local, demo, or deployment environments.

## 10. Complete Project Workflow
- User opens the sign-in page.
- User registers or logs in.
- Frontend stores JWTs and redirects to Gallery.
- User uploads one or more photos.
- Backend saves files to `backend/uploads` and creates `Photo` rows.
- Background processing extracts EXIF metadata, runs CLIP embeddings, classifies scene labels, computes duplicate hashes, and marks photos `ready`.
- Gallery refreshes and shows processed photos.
- Search uses CLIP text embeddings and pgvector similarity.
- Timeline groups by year/month/day.
- Duplicates groups exact and similar copies.
- Events organize photos into canonical scene-category albums.
- Health shows runtime status.
- Backup exports PostgreSQL plus an uploads archive.

## 11. Execution Flow
- `python app.py` runs first.
- `create_app()` loads config from `.env`.
- It validates that `DATABASE_URL` is PostgreSQL.
- It ensures directories exist.
- It configures logging, CORS, JWT, limiter, SQLAlchemy, and migrations.
- It logs PostgreSQL and pgvector readiness.
- It registers blueprints and CLI commands.
- Flask starts the HTTP server.
- Frontend pages load `api.js` and then page-specific scripts.
- Protected pages call `requireAuth()` before use.

## 12. Authentication Flow
- `POST /auth/register` creates a new user with a hashed password.
- `POST /auth/login` checks the password and returns access and refresh JWTs.
- Frontend stores tokens in `localStorage`.
- `api.js` auto-refreshes the access token before expiry.
- Protected endpoints require `Authorization: Bearer <token>`.
- Frontend pages redirect to login if no session is present.
- Password policy requires uppercase, lowercase, number, and minimum length.

## 13. AI/Model Flow
- **Scene classification**
  - `ml/scene_classifier.py` loads ResNet-18 Places365.
  - It classifies each image into a scene label such as `Beach`, `Temple Asia`, or `Office`.
- **CLIP embeddings**
  - `ml/clip_search.py` loads CLIP `ViT-B/32`.
  - It produces normalized 512-dimensional image and text embeddings.
- **Duplicate detection**
  - `backend/duplicate_detection.py` computes SHA-256 and perceptual dHash.
- **Event grouping**
  - `ml/event_organizer.py` maps raw Places365 scenes into broader album categories like `Vacation & Outdoors`, `Campus & Learning`, and `Sacred & Heritage`.
- **Current organizer behavior**
  - The active organizer flow in `backend/background_tasks.py` maps each ready photo into its category album and merges same-label duplicates canonically.
- **Model loading**
  - CLIP and ResNet are loaded lazily on first use and then cached in memory.

## 14. PostgreSQL + pgvector Flow
- Photos store CLIP embeddings in `clip_vector_pg`.
- The column type is a `pgvector` vector with dimension 512.
- Search uses the PostgreSQL `<=>` vector distance operator.
- `score_ready_photos()` searches only ready, non-trashed photos.
- Results are re-ranked with a small scene boost.
- `flask vectors status` shows whether the vector column and extension are ready.
- `flask vectors backfill` can migrate old legacy embedding columns into `clip_vector_pg`.

## 15. Interview & Viva Questions
- **What is MemoryLens?** An AI photo organizer with PostgreSQL and pgvector.
- **Why PostgreSQL?** It supports relational integrity and vector search.
- **Why pgvector?** To run semantic similarity search on CLIP embeddings.
- **What is CLIP used for?** Image embeddings and text-to-photo search.
- **What is ResNet-18 Places365 used for?** Scene classification.
- **Why use Places365?** It gives scene labels that map well to albums.
- **How is a photo stored?** The file is on disk and metadata is in PostgreSQL.
- **How are passwords stored?** Hashed with Werkzeug.
- **Why JWT?** Stateless authentication for protected APIs.
- **Why refresh tokens?** To keep sessions alive without logging in again.
- **How does upload work?** Upload -> queue job -> AI processing -> ready photo.
- **What is a BackgroundJob?** A record that tracks long-running work.
- **Why background jobs?** So uploads and organize actions do not block the browser.
- **What is a photo scene?** The AI label returned by ResNet/Places365.
- **What is an event album?** A curated album grouping related photos.
- **What is a folder?** A gallery-level custom or AI-scene grouping label.
- **Why separate folders and events?** Folders are library organization; events are story albums.
- **How do duplicates work?** SHA-256 for exact and dHash for near-duplicates.
- **What is dHash?** A perceptual hash for image similarity.
- **Why store both hashes?** To catch exact copies and re-saved versions.
- **What is EXIF capture time?** Metadata from the image file.
- **Why use EXIF?** Better timeline and event ordering.
- **What is the timeline view?** A date-based browse by year, month, or day.
- **What is the health page?** A runtime dashboard for DB, vector, models, and backup.
- **Why backup PostgreSQL?** To protect data and support restore.
- **What does the backup contain?** A pg_dump dump, upload ZIP, and manifest.
- **Why use protected file delivery?** To keep image access tied to auth.
- **How does sharing work?** Signed tokens with expiration.
- **What is the biggest limitation?** The in-process job queue is not durable for production scale.
- **What would you use in production?** Celery/RQ or another durable worker queue.

## 16. Important Concepts To Remember
- `Photo.scene` is the AI scene label.
- `Photo.custom_folder` is the user override for gallery organization.
- `Event.label` is the album name.
- `clip_vector_pg` is the semantic embedding used for search.
- `BackgroundJob` tracks long-running actions.
- `backend/background_tasks.py` is the orchestration center.
- `frontend/js/api.js` is the communication layer.
- `pgvector` turns PostgreSQL into the vector search engine.
- `duplicates` uses exact and perceptual hashes.
- `timeline` is date-driven browsing.
- `health` is a demo-proof operational status page.

## 17. Project Strengths
- Strong end-to-end flow: auth, upload, AI processing, browse, search, organize, share, and backup.
- PostgreSQL-first design with pgvector is production-flavored.
- Good separation between frontend, routes, models, and services.
- Polished dark UI with consistent components.
- Practical AI use, not just a toy model.
- Health checks, backups, and rate-limited auth make it feel complete.
- Data integrity is respected with relations, migrations, and named entities.

## 18. Project Weaknesses
- In-process thread pool jobs are not durable.
- Admin backup and health endpoints should be restricted before public deployment.
- First model load can be slow because CLIP/ResNet warm up lazily.
- `RATELIMIT_STORAGE_URI=memory://` is fine locally but not for multi-instance deployment.
- The project is strong for demos and academic review, but not fully enterprise-hardened.

## 19. Full Data Flow Diagram
```text
User -> Frontend page -> api.js -> Flask blueprint -> PostgreSQL + pgvector
     -> backend/uploads -> AI helpers -> BackgroundJob -> UI refresh
```
- The user interacts with a page.
- The page calls `api.js`.
- `api.js` sends JWT-authenticated requests.
- Flask validates, reads or writes PostgreSQL and files, and may start background work.
- AI helpers generate scene labels, embeddings, and duplicate hashes.
- The frontend polls jobs and reloads UI data until the job completes.

## 20. Final Project Summary
MemoryLens is a full-stack AI photo organizer built around PostgreSQL, pgvector, and a static HTML/JS frontend. A user can register, log in, upload images, wait for AI classification, search semantically, browse by timeline, clean duplicates, manage event albums, and back up the database. The backend uses Flask blueprints, SQLAlchemy models, JWT auth, logging, migrations, and helper services for CLIP, ResNet Places365, dHash duplicate detection, event metadata, sharing, and backups. The result is a realistic, review-ready project that shows database design, AI integration, file storage, vector search, and polished UI together in one system.

## Sample Viva Questions
1. What is MemoryLens?
2. Why did you choose PostgreSQL?
3. Why use pgvector?
4. What is CLIP used for?
5. What is ResNet-18 Places365 used for?
6. How is an image stored in the system?
7. Why do you use JWT?
8. Why use background jobs?
9. What is the purpose of the Health page?
10. What is the role of the Events page?

