import json
import uuid

from models import db
from time_utils import utcnow


class BackgroundJob(db.Model):
    __tablename__ = 'jobs'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(32), nullable=False, default='queued')
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    total_items = db.Column(db.Integer, nullable=False, default=0)
    completed_items = db.Column(db.Integer, nullable=False, default=0)
    result_payload = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def result(self):
        if not self.result_payload:
            return None
        try:
            return json.loads(self.result_payload)
        except json.JSONDecodeError:
            return None

    def to_dict(self):
        progress = 0
        if self.total_items:
            progress = int(round((self.completed_items / self.total_items) * 100))

        return {
            'id': self.id,
            'job_type': self.job_type,
            'status': self.status,
            'total_items': self.total_items,
            'completed_items': self.completed_items,
            'progress': progress,
            'error_message': self.error_message,
            'result': self.result(),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }
