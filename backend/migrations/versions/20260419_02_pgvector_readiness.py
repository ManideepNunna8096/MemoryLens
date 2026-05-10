"""Add pgvector-ready embedding column on PostgreSQL.

Revision ID: 20260419_02
Revises: 20260419_01
Create Date: 2026-04-19
"""

from alembic import op
import sqlalchemy as sa


revision = '20260419_02'
down_revision = '20260419_01'
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def _column_names(inspector, table_name):
    return {column['name'] for column in inspector.get_columns(table_name)}


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
        raise RuntimeError('MemoryLens migrations now require PostgreSQL.')

    existing_columns = _column_names(inspector, 'photos')
    if 'clip_vector_pg' in existing_columns:
        return

    if not _pgvector_extension_available(bind):
        raise RuntimeError('pgvector extension is not available in this PostgreSQL instance.')

    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute('ALTER TABLE photos ADD COLUMN clip_vector_pg vector(512)')
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

    existing_columns = _column_names(inspector, 'photos')
    if 'clip_vector_pg' not in existing_columns:
        return

    if bind.dialect.name != 'postgresql':
        raise RuntimeError('MemoryLens migrations now require PostgreSQL.')

    op.execute('DROP INDEX IF EXISTS ix_photos_clip_vector_pg_ivfflat')
    op.execute('ALTER TABLE photos DROP COLUMN clip_vector_pg')
