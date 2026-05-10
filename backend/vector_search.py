import json

import numpy as np
import sqlalchemy as sa
from flask import current_app

from models import db
from models.photo import Photo
from utils.logger import get_logger


vector_logger = get_logger('VECTOR')


def _configured_backend():
    value = str(current_app.config.get('VECTOR_BACKEND', 'auto')).strip().lower()
    if value in {'auto', 'pgvector'}:
        return value
    return 'pgvector'


def _expected_dimension():
    return int(current_app.config.get('CLIP_VECTOR_DIM', 512))


def _has_pgvector_column():
    try:
        inspector = sa.inspect(db.engine)
        if 'photos' not in inspector.get_table_names():
            return False
        columns = {column['name'] for column in inspector.get_columns('photos')}
        return 'clip_vector_pg' in columns
    except Exception:
        vector_logger.error('pgvector column probe failed', exc_info=True)
        return False


def pgvector_enabled():
    if db.engine.dialect.name != 'postgresql':
        return False
    return _has_pgvector_column()


def pgvector_runtime_status():
    dialect = db.engine.dialect.name
    has_column = _has_pgvector_column() if dialect == 'postgresql' else False

    summary = {
        'configured_backend': _configured_backend(),
        'database_dialect': dialect,
        'pgvector_column_present': has_column,
        'pgvector_enabled': dialect == 'postgresql' and has_column,
    }

    if dialect != 'postgresql':
        summary['reason'] = 'Current DATABASE_URL is not using PostgreSQL.'
        return summary

    if not has_column:
        summary['reason'] = 'clip_vector_pg column is missing. Run flask db upgrade first.'
        return summary

    return summary


def _vector_literal(vector):
    values = np.asarray(vector, dtype=np.float32).reshape(-1).tolist()
    return '[' + ','.join(f'{value:.8f}' for value in values) + ']'


def similarity_search_pgvector(user_id, query_embedding, limit):
    vector = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
    if vector.size == 0:
        return []
    if vector.size != _expected_dimension():
        vector_logger.warning('query embedding dimension mismatch')
        return []

    query = sa.text(
        """
        SELECT id, (1 - (clip_vector_pg <=> CAST(:query_vector AS vector))) AS clip_score
        FROM photos
        WHERE user_id = :user_id
          AND processing_status = 'ready'
          AND trashed_at IS NULL
          AND clip_vector_pg IS NOT NULL
        ORDER BY clip_vector_pg <=> CAST(:query_vector AS vector)
        LIMIT :limit
        """
    )
    rows = (
        db.session.execute(
            query,
            {
                'query_vector': _vector_literal(vector),
                'user_id': int(user_id),
                'limit': int(limit),
            },
        )
        .mappings()
        .all()
    )
    if not rows:
        return []

    photo_ids = [int(row['id']) for row in rows]
    photos = (
        Photo.query.filter(
            Photo.user_id == user_id,
            Photo.id.in_(photo_ids),
            Photo.processing_status == 'ready',
            Photo.trashed_at.is_(None),
        )
        .all()
    )
    photo_by_id = {photo.id: photo for photo in photos}

    scored = []
    for row in rows:
        photo = photo_by_id.get(int(row['id']))
        if not photo:
            continue
        clip_score = float(row['clip_score'] or 0.0)
        scored.append({'photo': photo, 'clip_score': max(-1.0, min(1.0, clip_score))})

    return scored


def score_ready_photos(user_id, query_embedding, limit=200):
    if not pgvector_enabled():
        return [], 'pgvector'
    return similarity_search_pgvector(user_id, query_embedding, limit), 'pgvector'


def store_pgvector_embedding(photo_id, vector):
    if not pgvector_enabled():
        return False

    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    if array.size == 0:
        return False
    if array.size != _expected_dimension():
        vector_logger.warning('photo embedding dimension mismatch')
        return False

    try:
        db.session.execute(
            sa.text(
                """
                UPDATE photos
                SET clip_vector_pg = CAST(:embedding AS vector)
                WHERE id = :photo_id
                """
            ),
            {
                'embedding': _vector_literal(array),
                'photo_id': int(photo_id),
            },
        )
        return True
    except Exception:
        vector_logger.error('pgvector embedding update failed', exc_info=True)
        return False


persist_pgvector_embedding = store_pgvector_embedding


def backfill_missing_pgvector_embeddings(batch_size=100, limit=None):
    status = pgvector_runtime_status()
    summary = {
        **status,
        'processed': 0,
        'updated': 0,
        'skipped': 0,
        'failed': 0,
        'remaining': 0,
        'limit': int(limit) if limit else None,
        'batch_size': int(batch_size),
    }

    if not status.get('pgvector_enabled'):
        return summary

    inspector = sa.inspect(db.engine)
    columns = {column['name'] for column in inspector.get_columns('photos')}
    legacy_columns = {name for name in ('clip_vector', 'clip_vector_blob', 'clip_vector_dim') if name in columns}
    if not legacy_columns:
        summary['reason'] = 'No legacy embedding columns remain to backfill.'
        pending_query = sa.text(
            """
            SELECT COUNT(*)
            FROM photos
            WHERE processing_status = 'ready'
              AND trashed_at IS NULL
              AND clip_vector_pg IS NULL
            """
        )
        summary['remaining'] = int(db.session.execute(pending_query).scalar_one())
        return summary

    select_columns = ['id']
    if 'clip_vector' in legacy_columns:
        select_columns.append('clip_vector')
    else:
        select_columns.append('NULL AS clip_vector')
    if 'clip_vector_blob' in legacy_columns:
        select_columns.append('clip_vector_blob')
    else:
        select_columns.append('NULL AS clip_vector_blob')
    if 'clip_vector_dim' in legacy_columns:
        select_columns.append('clip_vector_dim')
    else:
        select_columns.append('NULL AS clip_vector_dim')

    pending_query = sa.text(
        f"""
        SELECT {', '.join(select_columns)}
        FROM photos
        WHERE processing_status = 'ready'
          AND trashed_at IS NULL
          AND clip_vector_pg IS NULL
          AND (clip_vector_blob IS NOT NULL OR clip_vector IS NOT NULL)
        ORDER BY id
        """
    )
    rows = db.session.execute(pending_query).mappings().all()
    if limit:
        rows = rows[: int(limit)]

    processed = 0
    for offset in range(0, len(rows), int(batch_size)):
        batch_rows = rows[offset : offset + int(batch_size)]
        for row in batch_rows:
            embedding = None
            blob_value = row.get('clip_vector_blob')
            if blob_value is not None:
                if isinstance(blob_value, memoryview):
                    blob_value = blob_value.tobytes()
                blob_value = bytes(blob_value)
                embedding = np.frombuffer(blob_value, dtype=np.float32)
                dim = row.get('clip_vector_dim')
                if dim:
                    embedding = embedding[: int(dim)]
            elif row.get('clip_vector'):
                try:
                    embedding = np.asarray(json.loads(row['clip_vector']), dtype=np.float32).reshape(-1)
                except (TypeError, ValueError, json.JSONDecodeError):
                    embedding = None

            if embedding is None or np.asarray(embedding).size == 0:
                summary['skipped'] += 1
                processed += 1
                continue

            if store_pgvector_embedding(int(row['id']), embedding):
                summary['updated'] += 1
                db.session.commit()
            else:
                summary['failed'] += 1
                db.session.rollback()

            processed += 1

        summary['processed'] = processed

    remaining_query = sa.text(
        """
        SELECT COUNT(*)
        FROM photos
        WHERE processing_status = 'ready'
          AND trashed_at IS NULL
          AND clip_vector_pg IS NULL
        """
    )
    summary['remaining'] = int(db.session.execute(remaining_query).scalar_one())

    return summary
