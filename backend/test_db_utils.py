import os
from pathlib import Path

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv
from sqlalchemy.engine import make_url


BACKEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_ROOT.parent
for env_file in (PROJECT_ROOT / '.env', BACKEND_ROOT / '.env'):
    if env_file.exists():
        load_dotenv(env_file, override=True)


SOURCE_DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://memorylens:memorylens@127.0.0.1:5432/memorylens')


def _default_test_database_url():
    url = make_url(SOURCE_DATABASE_URL)
    database_name = url.database or 'memorylens'
    if not database_name.endswith('_test'):
        database_name = f'{database_name}_test'
    return str(url.set(database=database_name))


TEST_DATABASE_URL = os.getenv(
    'TEST_DATABASE_URL',
    _default_test_database_url(),
)

os.environ.setdefault('DATABASE_URL', TEST_DATABASE_URL)


def _admin_url(database_url=TEST_DATABASE_URL):
    url = make_url(database_url)
    return url.set(database=os.getenv('TEST_DATABASE_ADMIN_DB', 'postgres'))


def ensure_test_database(database_url=TEST_DATABASE_URL):
    url = make_url(database_url)
    try:
        connection = psycopg2.connect(str(url))
        connection.close()
        return
    except psycopg2.OperationalError:
        pass

    candidate_urls = [_admin_url(database_url), make_url(SOURCE_DATABASE_URL)]
    last_error = None
    for candidate in candidate_urls:
        connection = None
        try:
            connection = psycopg2.connect(str(candidate))
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', (url.database,))
                if cursor.fetchone() is None:
                    cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(url.database)))
            return
        except Exception as exc:
            last_error = exc
        finally:
            if connection is not None:
                connection.close()

    if last_error:
        raise last_error


def ensure_vector_extension(database_url=TEST_DATABASE_URL):
    connection = psycopg2.connect(database_url)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS vector')
    finally:
        connection.close()
