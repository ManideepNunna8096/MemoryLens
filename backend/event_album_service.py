from collections import Counter

from models import db
from models.photo import Photo


def event_photos_query(user_id, event_id):
    return Photo.query.filter(
        Photo.user_id == user_id,
        Photo.event_id == event_id,
    )


def visible_event_photos_query(user_id, event_id):
    return event_photos_query(user_id, event_id).filter(
        Photo.trashed_at.is_(None),
    )


def summarize_event_scene(photos):
    scenes = [str(photo.scene or '').strip() for photo in photos if str(photo.scene or '').strip()]
    if not scenes:
        return None

    scene_counts = Counter(scenes)
    if len(scene_counts) == 1:
        return next(iter(scene_counts))

    total = sum(scene_counts.values())
    top_two = scene_counts.most_common(2)
    top_scene, top_count = top_two[0]

    if top_count / max(total, 1) >= 0.6:
        return top_scene

    if len(top_two) >= 2:
        second_scene, second_count = top_two[1]
        if second_count / max(total, 1) >= 0.25:
            return f'{top_scene} + {second_scene}'

    return 'Mixed'


def recompute_event_metadata(event):
    photos = visible_event_photos_query(event.user_id, event.id).all()
    if not photos:
        event.dominant_scene = None
        return 0

    event.dominant_scene = summarize_event_scene(photos)
    return len(photos)


def delete_orphaned_event(event):
    visible_count = recompute_event_metadata(event)
    if event_photos_query(event.user_id, event.id).count() == 0:
        db.session.delete(event)
        return True
    return visible_count == 0


def get_visible_event(event_id, user_id):
    from models.event import Event

    event = Event.query.filter_by(id=event_id, user_id=user_id).first()
    if not event:
        return None
    if visible_event_photos_query(user_id, event.id).count() == 0:
        return None
    return event
