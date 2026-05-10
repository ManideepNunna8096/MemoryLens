"""Repair missing gallery metadata columns on PostgreSQL photos table.

Revision ID: 20260421_03
Revises: 20260421_02
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa


revision = '20260421_03'
down_revision = '20260421_02'
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def _column_names(inspector, table_name):
    return {column['name'] for column in inspector.get_columns(table_name)}


def _index_names(inspector, table_name):
    return {index['name'] for index in inspector.get_indexes(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if bind.dialect.name != 'postgresql':
        raise RuntimeError('MemoryLens migrations now require PostgreSQL.')

    if not _table_exists(inspector, 'photos'):
        return

    existing_columns = _column_names(inspector, 'photos')
    existing_indexes = _index_names(inspector, 'photos')

    with op.batch_alter_table('photos') as batch_op:
        if 'display_name' not in existing_columns:
            batch_op.add_column(sa.Column('display_name', sa.String(length=200), nullable=True))
        if 'sha256_hash' not in existing_columns:
            batch_op.add_column(sa.Column('sha256_hash', sa.String(length=64), nullable=True))
        if 'dhash' not in existing_columns:
            batch_op.add_column(sa.Column('dhash', sa.String(length=16), nullable=True))
        if 'is_favorite' not in existing_columns:
            batch_op.add_column(
                sa.Column('is_favorite', sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if 'is_archived' not in existing_columns:
            batch_op.add_column(
                sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if 'trashed_at' not in existing_columns:
            batch_op.add_column(sa.Column('trashed_at', sa.DateTime(), nullable=True))

    if 'ix_photos_sha256_hash' not in existing_indexes:
        op.create_index('ix_photos_sha256_hash', 'photos', ['sha256_hash'], unique=False)
    if 'ix_photos_dhash' not in existing_indexes:
        op.create_index('ix_photos_dhash', 'photos', ['dhash'], unique=False)

    op.execute("UPDATE photos SET is_favorite = FALSE WHERE is_favorite IS NULL")
    op.execute("UPDATE photos SET is_archived = FALSE WHERE is_archived IS NULL")

    with op.batch_alter_table('photos') as batch_op:
        batch_op.alter_column('is_favorite', server_default=None)
        batch_op.alter_column('is_archived', server_default=None)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if bind.dialect.name != 'postgresql':
        raise RuntimeError('MemoryLens migrations now require PostgreSQL.')

    if not _table_exists(inspector, 'photos'):
        return

    existing_columns = _column_names(inspector, 'photos')
    existing_indexes = _index_names(inspector, 'photos')

    if 'ix_photos_sha256_hash' in existing_indexes:
        op.drop_index('ix_photos_sha256_hash', table_name='photos')
    if 'ix_photos_dhash' in existing_indexes:
        op.drop_index('ix_photos_dhash', table_name='photos')

    with op.batch_alter_table('photos') as batch_op:
        if 'trashed_at' in existing_columns:
            batch_op.drop_column('trashed_at')
        if 'is_archived' in existing_columns:
            batch_op.drop_column('is_archived')
        if 'is_favorite' in existing_columns:
            batch_op.drop_column('is_favorite')
        if 'dhash' in existing_columns:
            batch_op.drop_column('dhash')
        if 'sha256_hash' in existing_columns:
            batch_op.drop_column('sha256_hash')
        if 'display_name' in existing_columns:
            batch_op.drop_column('display_name')
