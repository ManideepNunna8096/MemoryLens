from __future__ import annotations

import argparse
import ast
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import create_app
from models import db
from models.event import Event
from models.job import BackgroundJob
from models.photo import Photo
from models.user import User
from time_utils import serialize_utc_naive, utcnow
from utils.logger import get_logger


logger = get_logger('MIGRATE')


DEFAULT_SOURCES = [
    BACKEND_DIR / 'instance' / 'memorylens.pre_migration_2026-04-19.db',
    BACKEND_DIR / 'instance' / 'memorylens.db',
]
UPLOAD_ROOT = BACKEND_DIR / 'uploads'


def _connect_sqlite(path: Path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _row_value(row, key, default=None):
    if key in row.keys():
        return row[key]
    return default


def _parse_datetime(value):
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace('Z', '+00:00')
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _canonical_datetime(value):
    parsed = _parse_datetime(value)
    return serialize_utc_naive(parsed) if parsed else None


def _parse_vector_text(value):
    if value in (None, ''):
        return None
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(parsed, (list, tuple)):
        return None
    try:
        return [float(item) for item in parsed]
    except (TypeError, ValueError):
        return None


def _vector_from_blob(blob):
    if blob in (None, b''):
        return None
    try:
        array = np.frombuffer(blob, dtype=np.float32).reshape(-1)
    except Exception:
        return None
    if not array.size:
        return None
    return array.tolist()


def _source_paths(selected):
    if selected:
        return [Path(item) for item in selected]
    return list(DEFAULT_SOURCES)


def _existing_user_map():
    return {user.email: user.id for user in User.query.all()}


def _existing_event_map():
    mapping = {}
    for event in Event.query.all():
        key = (
            event.user_id,
            event.label,
            event.dominant_scene,
            _canonical_datetime(event.created_at),
        )
        mapping[key] = event.id
    return mapping


def _existing_photo_key_map():
    mapping = {}
    for photo in Photo.query.all():
        if photo.sha256_hash:
            mapping[('sha', photo.user_id, photo.sha256_hash)] = photo.id
        mapping[
            (
                'legacy',
                photo.user_id,
                photo.filename,
                _canonical_datetime(photo.uploaded_at),
            )
        ] = photo.id
    return mapping


def _existing_job_ids():
    return {job.id for job in BackgroundJob.query.all()}


def _rewrite_job_payload(payload_text, photo_id_map):
    if not payload_text:
        return payload_text
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return payload_text

    if isinstance(payload, dict):
        photos = payload.get('photos')
        if isinstance(photos, list):
            for item in photos:
                if isinstance(item, dict):
                    old_photo_id = item.get('id')
                    if old_photo_id in photo_id_map:
                        item['id'] = photo_id_map[old_photo_id]
    return json.dumps(payload)


def _import_users(conn, existing_user_map):
    user_map = {}
    rows = conn.execute('SELECT * FROM users ORDER BY id').fetchall()
    imported = 0
    skipped = 0

    for row in rows:
        email = row['email']
        if email in existing_user_map:
            user_map[row['id']] = existing_user_map[email]
            skipped += 1
            continue

        user = User(
            name=row['name'],
            email=email,
            password=row['password'],
            created_at=_parse_datetime(_row_value(row, 'created_at')) or utcnow(),
        )
        db.session.add(user)
        db.session.flush()
        existing_user_map[email] = user.id
        user_map[row['id']] = user.id
        imported += 1

    return user_map, {'imported': imported, 'skipped': skipped}


def _import_events(conn, user_map, existing_event_map):
    event_map = {}
    rows = conn.execute('SELECT * FROM events ORDER BY id').fetchall()
    imported = 0
    skipped = 0

    for row in rows:
        source_user_id = row['user_id']
        if source_user_id not in user_map:
            skipped += 1
            continue

        mapped_user_id = user_map[source_user_id]
        key = (
            mapped_user_id,
            row['label'],
            _row_value(row, 'dominant_scene'),
            _canonical_datetime(_row_value(row, 'created_at')),
        )
        if key in existing_event_map:
            event_map[row['id']] = existing_event_map[key]
            skipped += 1
            continue

        event = Event(
            label=row['label'],
            dominant_scene=_row_value(row, 'dominant_scene'),
            user_id=mapped_user_id,
            created_at=_parse_datetime(_row_value(row, 'created_at')) or utcnow(),
        )
        db.session.add(event)
        db.session.flush()
        existing_event_map[key] = event.id
        event_map[row['id']] = event.id
        imported += 1

    return event_map, {'imported': imported, 'skipped': skipped}


def _photo_duplicate_key(row, mapped_user_id):
    sha256_hash = _row_value(row, 'sha256_hash')
    if sha256_hash:
        return ('sha', mapped_user_id, sha256_hash)

    return (
        'legacy',
        mapped_user_id,
        row['filename'],
        _canonical_datetime(_row_value(row, 'uploaded_at')),
    )


def _photo_embedding(row):
    if 'clip_vector_pg' in row.keys() and row['clip_vector_pg'] not in (None, ''):
        vector = _parse_vector_text(row['clip_vector_pg'])
        if vector:
            return vector

    vector = _parse_vector_text(_row_value(row, 'clip_vector'))
    if vector:
        return vector

    vector = _vector_from_blob(_row_value(row, 'clip_vector_blob'))
    if vector:
        return vector

    return None


def _import_photos(conn, user_map, event_map, existing_photo_keys):
    photo_id_map = {}
    rows = conn.execute('SELECT * FROM photos ORDER BY id').fetchall()
    imported = 0
    skipped = 0
    missing_files = []

    for row in rows:
        source_user_id = row['user_id']
        if source_user_id not in user_map:
            skipped += 1
            continue

        mapped_user_id = user_map[source_user_id]
        duplicate_key = _photo_duplicate_key(row, mapped_user_id)
        if duplicate_key in existing_photo_keys:
            photo_id_map[row['id']] = existing_photo_keys[duplicate_key]
            skipped += 1
            continue

        filename = row['filename']
        if not (UPLOAD_ROOT / filename).exists():
            missing_files.append(filename)

        photo = Photo(
            filename=filename,
            original_filename=_row_value(row, 'original_filename'),
            scene=_row_value(row, 'scene') or 'Processing',
            clip_model_version=_row_value(row, 'clip_model_version'),
            scene_model_version=_row_value(row, 'scene_model_version'),
            processing_status=_row_value(row, 'processing_status') or 'ready',
            processing_error=_row_value(row, 'processing_error'),
            captured_at=_parse_datetime(_row_value(row, 'captured_at')),
            display_name=_row_value(row, 'display_name'),
            custom_folder=_row_value(row, 'custom_folder'),
            sha256_hash=_row_value(row, 'sha256_hash'),
            dhash=_row_value(row, 'dhash'),
            is_favorite=bool(_row_value(row, 'is_favorite', False)),
            is_archived=bool(_row_value(row, 'is_archived', False)),
            trashed_at=_parse_datetime(_row_value(row, 'trashed_at')),
            user_id=mapped_user_id,
            event_id=event_map.get(_row_value(row, 'event_id')),
            uploaded_at=_parse_datetime(_row_value(row, 'uploaded_at')) or utcnow(),
        )
        embedding = _photo_embedding(row)
        if embedding:
            photo.set_clip_embedding(embedding)

        db.session.add(photo)
        db.session.flush()

        existing_photo_keys[duplicate_key] = photo.id
        photo_id_map[row['id']] = photo.id
        imported += 1

    return photo_id_map, {'imported': imported, 'skipped': skipped, 'missing_files': missing_files}


def _import_jobs(conn, user_map, photo_id_map, existing_job_ids):
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs' LIMIT 1"
    ).fetchone()
    if not table_exists:
        return {'imported': 0, 'skipped': 0}

    rows = conn.execute('SELECT * FROM jobs ORDER BY created_at, id').fetchall()
    imported = 0
    skipped = 0

    for row in rows:
        job_id = row['id']
        if job_id in existing_job_ids:
            skipped += 1
            continue

        source_user_id = row['user_id']
        if source_user_id not in user_map:
            skipped += 1
            continue

        result_payload = _rewrite_job_payload(_row_value(row, 'result_payload'), photo_id_map)
        job = BackgroundJob(
            id=job_id,
            job_type=row['job_type'],
            status=row['status'],
            user_id=user_map[source_user_id],
            total_items=_row_value(row, 'total_items', 0) or 0,
            completed_items=_row_value(row, 'completed_items', 0) or 0,
            result_payload=result_payload,
            error_message=_row_value(row, 'error_message'),
            created_at=_parse_datetime(_row_value(row, 'created_at')) or utcnow(),
            updated_at=_parse_datetime(_row_value(row, 'updated_at')) or utcnow(),
        )
        db.session.add(job)
        existing_job_ids.add(job_id)
        imported += 1

    return {'imported': imported, 'skipped': skipped}


def _delete_sources(source_paths):
    deleted = []
    for path in source_paths:
        if path.exists():
            path.unlink()
            deleted.append(str(path))
    return deleted


def main():
    parser = argparse.ArgumentParser(description='Import legacy SQLite data into PostgreSQL and remove the SQLite sources.')
    parser.add_argument(
        '--source',
        action='append',
        dest='sources',
        help='SQLite database path to import. Repeat to import multiple files.',
    )
    parser.add_argument(
        '--keep-source',
        action='store_true',
        help='Import and verify data, but keep the SQLite source files.',
    )
    args = parser.parse_args()

    app = create_app()

    with app.app_context():
        source_paths = [path for path in _source_paths(args.sources) if path.exists()]
        if not source_paths:
            logger.info('No SQLite source files found. Nothing to import.')
            return 0

        logger.info('Starting SQLite to PostgreSQL import from %s', ', '.join(str(path) for path in source_paths))
        before = {
            'users': User.query.count(),
            'events': Event.query.count(),
            'photos': Photo.query.count(),
            'jobs': BackgroundJob.query.count(),
        }

        existing_user_map = _existing_user_map()
        existing_event_map = _existing_event_map()
        existing_photo_keys = _existing_photo_key_map()
        existing_job_ids = _existing_job_ids()

        import_summary = {
            'users': {'imported': 0, 'skipped': 0},
            'events': {'imported': 0, 'skipped': 0},
            'photos': {'imported': 0, 'skipped': 0, 'missing_files': []},
            'jobs': {'imported': 0, 'skipped': 0},
        }

        try:
            for source_path in source_paths:
                logger.info('Importing %s', source_path)
                conn = None
                try:
                    conn = _connect_sqlite(source_path)
                    user_map, user_stats = _import_users(conn, existing_user_map)
                    event_map, event_stats = _import_events(conn, user_map, existing_event_map)
                    photo_id_map, photo_stats = _import_photos(
                        conn,
                        user_map,
                        event_map,
                        existing_photo_keys,
                    )
                    job_stats = _import_jobs(conn, user_map, photo_id_map, existing_job_ids)

                    import_summary['users']['imported'] += user_stats['imported']
                    import_summary['users']['skipped'] += user_stats['skipped']
                    import_summary['events']['imported'] += event_stats['imported']
                    import_summary['events']['skipped'] += event_stats['skipped']
                    import_summary['photos']['imported'] += photo_stats['imported']
                    import_summary['photos']['skipped'] += photo_stats['skipped']
                    import_summary['photos']['missing_files'].extend(photo_stats['missing_files'])
                    import_summary['jobs']['imported'] += job_stats['imported']
                    import_summary['jobs']['skipped'] += job_stats['skipped']
                finally:
                    if conn:
                        conn.close()

            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('SQLite to PostgreSQL import failed')
            return 1

        after = {
            'users': User.query.count(),
            'events': Event.query.count(),
            'photos': Photo.query.count(),
            'jobs': BackgroundJob.query.count(),
        }

        logger.info(
            'Import summary users=%s events=%s photos=%s jobs=%s',
            import_summary['users'],
            import_summary['events'],
            import_summary['photos'],
            import_summary['jobs'],
        )
        logger.info('Counts before=%s after=%s', before, after)

        missing_files = sorted(set(import_summary['photos']['missing_files']))
        if missing_files:
            logger.warning('Imported photo metadata for %s missing file(s) that are no longer on disk.', len(missing_files))
            for filename in missing_files[:10]:
                logger.warning('Missing file: %s', filename)

        if not args.keep_source:
            deleted = _delete_sources(source_paths)
            logger.info('Deleted SQLite source files: %s', deleted)
        else:
            logger.info('SQLite source files were kept because --keep-source was set.')

        logger.info('SQLite import complete. PostgreSQL is now the only runtime database.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
