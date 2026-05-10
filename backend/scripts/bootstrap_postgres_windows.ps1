param(
    [string]$FlaskApp = "app:create_app"
)

$ErrorActionPreference = "Stop"

function Fail($message) {
    Write-Host "[ERROR] $message" -ForegroundColor Red
    exit 1
}

if (-not $env:DATABASE_URL) {
    Fail "DATABASE_URL is not set. Create the project .env first."
}

if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
    Fail "psql was not found on PATH. Install PostgreSQL and re-open the terminal."
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail "python was not found on PATH."
}

$env:FLASK_APP = $FlaskApp

Write-Host "[DB] Ensuring pgvector extension exists..." -ForegroundColor Cyan
psql $env:DATABASE_URL -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;"

Write-Host "[DB] Running Alembic migrations..." -ForegroundColor Cyan
python -m flask db upgrade

Write-Host "[VECTOR] Checking vector runtime status..." -ForegroundColor Cyan
python -m flask vectors status

Write-Host "[DONE] PostgreSQL bootstrap complete." -ForegroundColor Green
