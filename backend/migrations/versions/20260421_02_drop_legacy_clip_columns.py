"""Backfill pgvector embeddings and drop legacy clip storage columns.

Revision ID: 20260421_02
Revises: 20260421_01
Create Date: 2026-04-21
"""

import json

from alembic import op
import numpy as np
import sqlalchemy as sa


revision = '20260421_02'
down_revision = '20260421_01'
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def _column_names(inspector, table_name):
    return {column['name'] for column in inspector.get_columns(table_name)}


def _index_names(inspector, table_name):
    return {index['name'] for index in inspector.get_indexes(table_name)}


def _pgvector_extension_available(bind):
    row = bind.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector' LIMIT 1")
    ).scalar()
    return bool(row)


def _vector_literal(vector):
    values = np.asarray(vector, dtype=np.float32).reshape(-1).tolist()
    return '[' + ','.join(f'{value:.8f}' for value in values) + ']'


def _coerce_embedding(row):
    blob_value = row.get('clip_vector_blob')
    if blob_value is not None:
        if isinstance(blob_value, memoryview):
            blob_value = blob_value.tobytes()
        blob_value = bytes(blob_value)
        vector = np.frombuffer(blob_value, dtype=np.float32)
        dim = row.get('clip_vector_dim')
        if dim:
            vector = vector[: int(dim)]
        if vector.size:
            return vector

    json_value = row.get('clip_vector')
    if json_value:
        try:
            vector = np.asarray(json.loads(json_value), dtype=np.float32).reshape(-1)
            if vector.size:
                return vector
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    return None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if bind.dialect.name != 'postgresql':
        raise RuntimeError('MemoryLens migrations now require PostgreSQL.')

    if not _table_exists(inspector, 'photos'):
        return

    if not _pgvector_extension_available(bind):
        raise RuntimeError('pgvector extension is not available in this PostgreSQL instance.')

    existing_columns = _column_names(inspector, 'photos')
    existing_indexes = _index_names(inspector, 'photos')

    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    if 'clip_vector_pg' not in existing_columns:
        op.execute('ALTER TABLE photos ADD COLUMN clip_vector_pg vector(512)')

    if 'ix_photos_clip_vector_pg_ivfflat' not in existing_indexes:
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_photos_clip_vector_pg_ivfflat
            ON photos USING ivfflat (clip_vector_pg vector_cosine_ops)
            WITH (lists = 100)
            """
        )

    legacy_columns = {name for name in ('clip_vector', 'clip_vector_blob', 'clip_vector_dim') if name in existing_columns}
    if legacy_columns:
        rows = bind.execute(
            sa.text(
                """
                SELECT id, clip_vector, clip_vector_blob, clip_vector_dim
                FROM photos
                WHERE clip_vector_pg IS NULL
                  AND (clip_vector_blob IS NOT NULL OR clip_vector IS NOT NULL)
                ORDER BY id
                """
            )
        ).mappings()
        for row in rows:
            vector = _coerce_embedding(row)
            if vector is None:
                continue
            bind.execute(
                sa.text(
                    """
                    UPDATE photos
                    SET clip_vector_pg = CAST(:embedding AS vector)
                    WHERE id = :photo_id
                    """
                ),
                {
                    'embedding': _vector_literal(vector),
                    'photo_id': int(row['id']),
                },
            )

        with op.batch_alter_table('photos') as batch_op:
            if 'clip_vector' in legacy_columns:
                batch_op.drop_column('clip_vector')
            if 'clip_vector_blob' in legacy_columns:
                batch_op.drop_column('clip_vector_blob')
            if 'clip_vector_dim' in legacy_columns:
                batch_op.drop_column('clip_vector_dim')


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if bind.dialect.name != 'postgresql':
        raise RuntimeError('MemoryLens migrations now require PostgreSQL.')

    if not _table_exists(inspector, 'photos'):
        return

    existing_columns = _column_names(inspector, 'photos')

    with op.batch_alter_table('photos') as batch_op:
        if 'clip_vector' not in existing_columns:
            batch_op.add_column(sa.Column('clip_vector', sa.Text(), nullable=True))
        if 'clip_vector_blob' not in existing_columns:
            batch_op.add_column(sa.Column('clip_vector_blob', sa.LargeBinary(), nullable=True))
        if 'clip_vector_dim' not in existing_columns:
            batch_op.add_column(sa.Column('clip_vector_dim', sa.Integer(), nullable=True))
