"""Align pgvector runtime column/index setup for PostgreSQL.

Revision ID: 20260421_01
Revises: 20260420_01
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa


revision = '20260421_01'
down_revision = '20260420_01'
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


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'photos'):
        return

    if bind.dialect.name != 'postgresql':
        return

    if not _pgvector_extension_available(bind):
        return

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


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'photos'):
        return

    if bind.dialect.name != 'postgresql':
        return

    existing_columns = _column_names(inspector, 'photos')
    existing_indexes = _index_names(inspector, 'photos')

    if 'ix_photos_clip_vector_pg_ivfflat' in existing_indexes:
        op.execute('DROP INDEX IF EXISTS ix_photos_clip_vector_pg_ivfflat')

    if 'clip_vector_pg' in existing_columns:
        op.execute('ALTER TABLE photos DROP COLUMN clip_vector_pg')
