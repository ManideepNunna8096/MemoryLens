import os
from datetime import timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback for environments missing python-dotenv
    def load_dotenv(*args, **kwargs):
        return False


BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

for env_file in (PROJECT_ROOT / '.env', BACKEND_DIR / '.env'):
    if env_file.exists():
        load_dotenv(env_file)


def _as_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {'1', 'true', 'yes', 'on'}


def _as_int(name, default):
    return int(os.getenv(name, default))


def _as_list(name, default):
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    return [item.strip() for item in raw_value.split(',') if item.strip()]


def _normalize_database_url(raw_value):
    value = str(raw_value or '').strip()
    if not value:
        return None
    if value.startswith('postgres://'):
        return 'postgresql://' + value[len('postgres://') :]
    return value


def _database_uri():
    return _normalize_database_url(os.getenv('DATABASE_URL'))


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-only-secret-change-me')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'dev-only-jwt-secret-change-me')
    JWT_ERROR_MESSAGE_KEY = 'error'
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=_as_int('JWT_ACCESS_MINUTES', 15))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=_as_int('JWT_REFRESH_DAYS', 30))

    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}
    DATABASE_LABEL = 'PostgreSQL'

    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', str(BACKEND_DIR / 'uploads'))
    MAX_CONTENT_LENGTH = _as_int('MAX_CONTENT_LENGTH_MB', 50) * 1024 * 1024
    ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'heic', 'webp', 'jfif', 'jfiff'}
    ML_FOLDER = os.getenv('ML_FOLDER', str(PROJECT_ROOT / 'ml'))
    VECTOR_BACKEND = os.getenv('VECTOR_BACKEND', 'pgvector')
    CLIP_VECTOR_DIM = _as_int('CLIP_VECTOR_DIM', 512)

    CORS_ORIGINS = _as_list(
        'FRONTEND_ORIGINS',
        [
            'http://127.0.0.1:5500',
            'http://localhost:5500',
            'http://127.0.0.1:3000',
            'http://localhost:3000',
        ],
    )
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
    AUTH_RATE_LIMIT = os.getenv('AUTH_RATE_LIMIT', '5 per minute')
    RATELIMIT_STORAGE_URI = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')
    TASKS_EAGER = _as_bool('TASKS_EAGER', False)

    DEBUG = _as_bool('FLASK_DEBUG', False)
    HOST = os.getenv('HOST', '127.0.0.1')
    PORT = _as_int('PORT', 5000)
    JSON_SORT_KEYS = False
    DISPLAY_TIMEZONE = os.getenv('DISPLAY_TIMEZONE')
