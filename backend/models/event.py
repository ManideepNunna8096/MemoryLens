from models import db
from event_album_service import visible_event_photos_query
from time_utils import utcnow


class Event(db.Model):
    __tablename__ = 'events'

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(150), nullable=False)
    dominant_scene = db.Column(db.String(100), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    photos = db.relationship('Photo', backref='event', lazy=True)

    def to_dict(self):
        from models.photo import Photo

        photos = (
            visible_event_photos_query(self.user_id, self.id)
            .order_by(db.func.coalesce(Photo.captured_at, Photo.uploaded_at).desc())
            .all()
        )
        preview_photos = photos[:3]
        return {
            'id': self.id,
            'label': self.label,
            'dominant_scene': self.dominant_scene,
            'photo_count': len(photos),
            'preview_photos': [
                {
                    'id': photo.id,
                    'filename': photo.filename,
                    'scene': photo.scene,
                }
                for photo in preview_photos
            ],
            'created_at': self.created_at.isoformat(),
        }
