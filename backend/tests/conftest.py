from pathlib import Path
import sys

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from test_db_utils import TEST_DATABASE_URL, ensure_test_database, ensure_vector_extension
from app import create_app
from models import db


@pytest.fixture
def app(tmp_path):
    upload_dir = tmp_path / 'uploads'
    upload_dir.mkdir(parents=True, exist_ok=True)
    ensure_test_database(TEST_DATABASE_URL)
    ensure_vector_extension(TEST_DATABASE_URL)

    app = create_app(
        {
            'TESTING': True,
            'SECRET_KEY': 'test-secret-key-32-chars-minimum-okay!!',
            'JWT_SECRET_KEY': 'test-jwt-secret-key-32-chars-okay!!',
            'SQLALCHEMY_DATABASE_URI': TEST_DATABASE_URL,
            'UPLOAD_FOLDER': str(upload_dir),
            'TASKS_EAGER': True,
            'AUTH_RATE_LIMIT': '1000 per minute',
        }
    )

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def upload_dir(app):
    return Path(app.config['UPLOAD_FOLDER'])
