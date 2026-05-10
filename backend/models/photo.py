import os

import numpy as np
from pgvector.sqlalchemy import Vector

from models import db
from time_utils import serialize_utc_naive, utcnow

DEFAULT_CLIP_VECTOR_DIM = int(os.getenv('CLIP_VECTOR_DIM', '512'))


class Photo(db.Model):
    __tablename__ = 'photos'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(200), nullable=True)
    scene = db.Column(db.String(100), nullable=False, default='Processing')
    clip_vector_pg = db.Column(Vector(DEFAULT_CLIP_VECTOR_DIM), nullable=True)
    clip_model_version = db.Column(db.String(64), nullable=True)
    scene_model_version = db.Column(db.String(64), nullable=True)
    processing_status = db.Column(db.String(32), nullable=False, default='queued')
    processing_error = db.Column(db.Text, nullable=True)
    captured_at = db.Column(db.DateTime, nullable=True)
    display_name = db.Column(db.String(200), nullable=True)
    custom_folder = db.Column(db.String(120), nullable=True)
    sha256_hash = db.Column(db.String(64), nullable=True, index=True)
    dhash = db.Column(db.String(16), nullable=True, index=True)
    is_favorite = db.Column(db.Boolean, nullable=False, default=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    trashed_at = db.Column(db.DateTime, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=utcnow)

    def filepath(self, upload_root):
        return os.path.join(upload_root, self.filename)

    def set_clip_embedding(self, vector):
        array = np.asarray(vector, dtype=np.float32).reshape(-1)
        self.clip_vector_pg = array.tolist()

    def get_clip_embedding(self):
        if self.clip_vector_pg is None:
            return None
        try:
            vector = np.asarray(self.clip_vector_pg, dtype=np.float32).reshape(-1)
        except (TypeError, ValueError):
            return None
        return vector if vector.size else None

    def folder_label(self):
        label = (self.custom_folder or self.scene or '').strip()
        return label or 'Uncategorized'

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'original_filename': self.original_filename or self.filename,
            'scene': self.scene,
            'user_id': self.user_id,
            'event_id': self.event_id,
            'processing_status': self.processing_status,
            'processing_error': self.processing_error,
            'display_name': self.display_name,
            'custom_folder': self.custom_folder,
            'sha256_hash': self.sha256_hash,
            'dhash': self.dhash,
            'folder_label': self.folder_label(),
            'is_favorite': bool(self.is_favorite),
            'is_archived': bool(self.is_archived),
            'is_trashed': self.trashed_at is not None,
            'trashed_at': self.trashed_at.isoformat() if self.trashed_at else None,
            'captured_at': self.captured_at.isoformat() if self.captured_at else None,
            'uploaded_at': serialize_utc_naive(self.uploaded_at),
        }
