"""Add custom photo folder labels for gallery organization.

Revision ID: 20260420_01
Revises: 20260419_02
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa


revision = '20260420_01'
down_revision = '20260419_02'
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def _column_names(inspector, table_name):
    return {column['name'] for column in inspector.get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'photos'):
        return

    existing_columns = _column_names(inspector, 'photos')
    if 'custom_folder' in existing_columns:
        return

    with op.batch_alter_table('photos') as batch_op:
        batch_op.add_column(sa.Column('custom_folder', sa.String(length=120), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'photos'):
        return

    existing_columns = _column_names(inspector, 'photos')
    if 'custom_folder' not in existing_columns:
        return

    with op.batch_alter_table('photos') as batch_op:
        batch_op.drop_column('custom_folder')
