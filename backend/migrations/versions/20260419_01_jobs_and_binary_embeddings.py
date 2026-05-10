"""Add jobs, binary embeddings, and photo processing metadata.

Revision ID: 20260419_01
Revises:
Create Date: 2026-04-19
"""

from datetime import datetime
import json

from alembic import op
import numpy as np
import sqlalchemy as sa


revision = '20260419_01'
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def _column_names(inspector, table_name):
    return {column['name'] for column in inspector.get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'users'):
        op.create_table(
            'users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('email', sa.String(length=150), nullable=False),
            sa.Column('password', sa.String(length=200), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True, default=datetime.utcnow),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('email'),
        )

    if not _table_exists(inspector, 'events'):
        op.create_table(
            'events',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('label', sa.String(length=150), nullable=False),
            sa.Column('dominant_scene', sa.String(length=100), nullable=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True, default=datetime.utcnow),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _table_exists(inspector, 'photos'):
        op.create_table(
            'photos',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('filename', sa.String(length=200), nullable=False),
            sa.Column('original_filename', sa.String(length=200), nullable=True),
            sa.Column('scene', sa.String(length=100), nullable=False, server_default='Processing'),
            sa.Column('clip_vector', sa.Text(), nullable=True),
            sa.Column('clip_vector_blob', sa.LargeBinary(), nullable=True),
            sa.Column('clip_vector_dim', sa.Integer(), nullable=True),
            sa.Column('clip_model_version', sa.String(length=64), nullable=True),
            sa.Column('scene_model_version', sa.String(length=64), nullable=True),
            sa.Column('processing_status', sa.String(length=32), nullable=False, server_default='queued'),
            sa.Column('processing_error', sa.Text(), nullable=True),
            sa.Column('captured_at', sa.DateTime(), nullable=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('event_id', sa.Integer(), nullable=True),
            sa.Column('uploaded_at', sa.DateTime(), nullable=True, default=datetime.utcnow),
            sa.ForeignKeyConstraint(['event_id'], ['events.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    inspector = sa.inspect(bind)
    if not _table_exists(inspector, 'jobs'):
        op.create_table(
            'jobs',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('job_type', sa.String(length=50), nullable=False),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='queued'),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('total_items', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('completed_items', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('result_payload', sa.Text(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_jobs_user_id'), 'jobs', ['user_id'], unique=False)

    inspector = sa.inspect(bind)
    if _table_exists(inspector, 'photos'):
        existing_columns = _column_names(inspector, 'photos')
        with op.batch_alter_table('photos') as batch_op:
            if 'original_filename' not in existing_columns:
                batch_op.add_column(sa.Column('original_filename', sa.String(length=200), nullable=True))
            if 'clip_vector_blob' not in existing_columns:
                batch_op.add_column(sa.Column('clip_vector_blob', sa.LargeBinary(), nullable=True))
            if 'clip_vector_dim' not in existing_columns:
                batch_op.add_column(sa.Column('clip_vector_dim', sa.Integer(), nullable=True))
            if 'clip_model_version' not in existing_columns:
                batch_op.add_column(sa.Column('clip_model_version', sa.String(length=64), nullable=True))
            if 'scene_model_version' not in existing_columns:
                batch_op.add_column(sa.Column('scene_model_version', sa.String(length=64), nullable=True))
            if 'processing_status' not in existing_columns:
                batch_op.add_column(sa.Column('processing_status', sa.String(length=32), nullable=False, server_default='ready'))
            if 'processing_error' not in existing_columns:
                batch_op.add_column(sa.Column('processing_error', sa.Text(), nullable=True))
            if 'captured_at' not in existing_columns:
                batch_op.add_column(sa.Column('captured_at', sa.DateTime(), nullable=True))

        op.execute("UPDATE photos SET original_filename = filename WHERE original_filename IS NULL")
        op.execute(
            "UPDATE photos SET processing_status = CASE "
            "WHEN processing_status IS NULL AND (clip_vector IS NOT NULL OR clip_vector_blob IS NOT NULL) THEN 'ready' "
            "WHEN processing_status IS NULL THEN 'queued' "
            "ELSE processing_status END"
        )
        op.execute("UPDATE photos SET scene_model_version = 'resnet18-places365' WHERE scene_model_version IS NULL")
        op.execute(
            "UPDATE photos SET clip_model_version = 'clip-vit-b32' "
            "WHERE clip_model_version IS NULL AND (clip_vector IS NOT NULL OR clip_vector_blob IS NOT NULL)"
        )

        rows = bind.execute(sa.text("SELECT id, clip_vector FROM photos WHERE clip_vector IS NOT NULL AND clip_vector_blob IS NULL")).fetchall()
        for row in rows:
            try:
                values = json.loads(row.clip_vector)
                array = np.asarray(values, dtype=np.float32)
                bind.execute(
                    sa.text(
                        "UPDATE photos SET clip_vector_blob = :blob, clip_vector_dim = :dim WHERE id = :photo_id"
                    ),
                    {
                        'blob': array.tobytes(),
                        'dim': int(array.size),
                        'photo_id': row.id,
                    },
                )
            except Exception:
                continue


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, 'photos'):
        existing_columns = _column_names(inspector, 'photos')
        with op.batch_alter_table('photos') as batch_op:
            for column_name in (
                'captured_at',
                'processing_error',
                'processing_status',
                'scene_model_version',
                'clip_model_version',
                'clip_vector_dim',
                'clip_vector_blob',
                'original_filename',
            ):
                if column_name in existing_columns:
                    batch_op.drop_column(column_name)

    if _table_exists(inspector, 'jobs'):
        if 'ix_jobs_user_id' in {index['name'] for index in inspector.get_indexes('jobs')}:
            op.drop_index(op.f('ix_jobs_user_id'), table_name='jobs')
        op.drop_table('jobs')
