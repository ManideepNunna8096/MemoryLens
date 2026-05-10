from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from background_tasks import submit_event_organization_job
from event_album_service import (
    delete_orphaned_event,
    get_visible_event,
    recompute_event_metadata,
    visible_event_photos_query,
)
from models import db
from models.event import Event
from models.job import BackgroundJob
from models.photo import Photo
from share_utils import build_photo_archive, create_share_token


event_bp = Blueprint('events', __name__)


def _visible_event_payloads(user_id):
    events = Event.query.filter_by(user_id=user_id).order_by(Event.created_at.desc()).all()
    payloads = []
    for event in events:
        payload = event.to_dict()
        if payload['photo_count'] > 0:
            payloads.append(payload)
    return payloads


@event_bp.route('/organize', methods=['POST'])
@jwt_required()
def organize():
    user_id = int(get_jwt_identity())

    job = BackgroundJob(
        job_type='event_organization',
        user_id=user_id,
        status='queued',
        total_items=0,
        completed_items=0,
    )
    db.session.add(job)
    db.session.commit()

    submit_event_organization_job(current_app._get_current_object(), job.id, user_id)
    db.session.expire_all()
    refreshed_job = db.session.get(BackgroundJob, job.id)

    return jsonify({'job': refreshed_job.to_dict()}), 202


@event_bp.route('/all', methods=['GET'])
@jwt_required()
def get_all_events():
    user_id = int(get_jwt_identity())
    return jsonify(_visible_event_payloads(user_id)), 200


@event_bp.route('/<int:event_id>/photos', methods=['GET'])
@jwt_required()
def get_event_photos(event_id):
    user_id = int(get_jwt_identity())
    event = get_visible_event(event_id, user_id)

    if not event:
        return jsonify({'error': 'Event not found'}), 404

    photos = visible_event_photos_query(user_id, event.id).order_by(
        db.func.coalesce(Photo.captured_at, Photo.uploaded_at).desc()
    ).all()
    return jsonify([photo.to_dict() for photo in photos]), 200


@event_bp.route('/<int:event_id>', methods=['PATCH'])
@jwt_required()
def rename_event(event_id):
    user_id = int(get_jwt_identity())
    event = Event.query.filter_by(id=event_id, user_id=user_id).first()
    if not event:
        return jsonify({'error': 'Event not found'}), 404

    data = request.get_json() or {}
    label = str(data.get('label', '')).strip()
    if not label:
        return jsonify({'error': 'Event label is required'}), 400
    if len(label) > 150:
        return jsonify({'error': 'Event label must be 150 characters or less'}), 400

    event.label = label
    db.session.commit()
    return jsonify(event.to_dict()), 200


@event_bp.route('/merge', methods=['POST'])
@jwt_required()
def merge_events():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    event_ids = data.get('event_ids') or []
    label = str(data.get('label', '')).strip()

    unique_ids = sorted({int(event_id) for event_id in event_ids if str(event_id).isdigit()})
    if len(unique_ids) < 2:
        return jsonify({'error': 'Select at least 2 events to merge'}), 400

    events = Event.query.filter(Event.user_id == user_id, Event.id.in_(unique_ids)).all()
    if len(events) != len(unique_ids):
        return jsonify({'error': 'One or more selected events were not found'}), 404

    all_photos = Photo.query.filter(Photo.user_id == user_id, Photo.event_id.in_(unique_ids)).all()
    if not all_photos:
        return jsonify({'error': 'Selected events do not contain photos'}), 400

    if not label:
        label = f"Merged {events[0].label}"

    merged_event = Event(
        label=label[:150],
        dominant_scene='Mixed',
        user_id=user_id,
    )
    db.session.add(merged_event)
    db.session.flush()

    for photo in all_photos:
        photo.event_id = merged_event.id

    recompute_event_metadata(merged_event)

    for event in events:
        db.session.delete(event)

    db.session.commit()
    return jsonify(merged_event.to_dict()), 200


@event_bp.route('/<int:event_id>/split', methods=['POST'])
@jwt_required()
def split_event(event_id):
    user_id = int(get_jwt_identity())
    source_event = Event.query.filter_by(id=event_id, user_id=user_id).first()
    if not source_event:
        return jsonify({'error': 'Event not found'}), 404

    data = request.get_json() or {}
    selected_ids = data.get('photo_ids') or []
    new_label = str(data.get('new_label', '')).strip()

    selected_photo_ids = sorted({int(photo_id) for photo_id in selected_ids if str(photo_id).isdigit()})
    if not selected_photo_ids:
        return jsonify({'error': 'Select at least 1 photo to split'}), 400

    selected_photos = Photo.query.filter(
        Photo.user_id == user_id,
        Photo.event_id == source_event.id,
        Photo.id.in_(selected_photo_ids),
        Photo.trashed_at.is_(None),
    ).all()
    if len(selected_photos) != len(selected_photo_ids):
        return jsonify({'error': 'Some selected photos are not part of this event'}), 400

    if not new_label:
        new_label = f"{source_event.label} Split"

    new_event = Event(
        label=new_label[:150],
        dominant_scene='Mixed',
        user_id=user_id,
    )
    db.session.add(new_event)
    db.session.flush()

    for photo in selected_photos:
        photo.event_id = new_event.id

    recompute_event_metadata(new_event)
    source_visible_count = recompute_event_metadata(source_event)
    delete_orphaned_event(source_event)

    db.session.commit()
    return (
        jsonify(
            {
                'new_event': new_event.to_dict(),
                'source_event': source_event.to_dict() if source_visible_count > 0 else None,
            }
        ),
        200,
    )


@event_bp.route('/move-photos', methods=['POST'])
@jwt_required()
def move_event_photos():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    photo_ids = data.get('photo_ids') or []
    target_event_id = data.get('target_event_id')

    selected_photo_ids = sorted({int(photo_id) for photo_id in photo_ids if str(photo_id).isdigit()})
    if not selected_photo_ids:
        return jsonify({'error': 'Select at least 1 photo to move'}), 400

    try:
        target_event_id = int(target_event_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Select a destination album'}), 400

    target_event = Event.query.filter_by(id=target_event_id, user_id=user_id).first()
    if not target_event:
        return jsonify({'error': 'Destination album not found'}), 404

    photos = Photo.query.filter(
        Photo.user_id == user_id,
        Photo.id.in_(selected_photo_ids),
        Photo.trashed_at.is_(None),
    ).all()
    if len(photos) != len(selected_photo_ids):
        return jsonify({'error': 'One or more selected photos could not be moved'}), 400

    source_event_ids = {photo.event_id for photo in photos if photo.event_id and photo.event_id != target_event.id}
    if not source_event_ids and all(photo.event_id == target_event.id for photo in photos):
        return jsonify({'error': 'These photos are already in that album'}), 400

    for photo in photos:
        photo.event_id = target_event.id

    recompute_event_metadata(target_event)
    source_payloads = []
    for source_event_id in sorted(source_event_ids):
        source_event = Event.query.filter_by(id=source_event_id, user_id=user_id).first()
        if not source_event:
            continue
        visible_count = recompute_event_metadata(source_event)
        delete_orphaned_event(source_event)
        if visible_count > 0:
            source_payloads.append(source_event.to_dict())

    db.session.commit()
    return (
        jsonify(
            {
                'moved_count': len(photos),
                'target_event': target_event.to_dict(),
                'source_events': source_payloads,
            }
        ),
        200,
    )


@event_bp.route('/<int:event_id>/remove-photos', methods=['POST'])
@jwt_required()
def remove_event_photos(event_id):
    user_id = int(get_jwt_identity())
    event = Event.query.filter_by(id=event_id, user_id=user_id).first()
    if not event:
        return jsonify({'error': 'Event not found'}), 404

    data = request.get_json() or {}
    photo_ids = data.get('photo_ids') or []
    selected_photo_ids = sorted({int(photo_id) for photo_id in photo_ids if str(photo_id).isdigit()})
    if not selected_photo_ids:
        return jsonify({'error': 'Select at least 1 photo to remove'}), 400

    photos = Photo.query.filter(
        Photo.user_id == user_id,
        Photo.event_id == event.id,
        Photo.id.in_(selected_photo_ids),
    ).all()
    if len(photos) != len(selected_photo_ids):
        return jsonify({'error': 'Some selected photos are not part of this album'}), 400

    for photo in photos:
        photo.event_id = None

    db.session.flush()
    delete_orphaned_event(event)
    event_deleted = event in db.session.deleted
    payload = None if event_deleted else event.to_dict()
    db.session.commit()

    return (
        jsonify(
            {
                'removed_count': len(photos),
                'event': payload,
            }
        ),
        200,
    )


@event_bp.route('/<int:event_id>/export', methods=['GET'])
@jwt_required()
def export_event(event_id):
    user_id = int(get_jwt_identity())
    event = get_visible_event(event_id, user_id)
    if not event:
        return jsonify({'error': 'Event not found'}), 404

    photos = visible_event_photos_query(user_id, event.id).order_by(Photo.uploaded_at.desc()).all()
    response = build_photo_archive(
        photos,
        current_app.config['UPLOAD_FOLDER'],
        event.label,
        manifest_extra={'kind': 'event_export', 'event_id': event.id},
    )
    if not response:
        return jsonify({'error': 'No photos are available to export'}), 404
    return response


@event_bp.route('/<int:event_id>/share', methods=['POST'])
@jwt_required()
def share_event(event_id):
    user_id = int(get_jwt_identity())
    event = get_visible_event(event_id, user_id)
    if not event:
        return jsonify({'error': 'Event not found'}), 404

    data = request.get_json() or {}
    token, expires_at = create_share_token(
        'event',
        {
            'user_id': user_id,
            'event_id': event.id,
            'label': event.label,
        },
        expires_in_hours=data.get('expires_in_hours', 72),
    )
    return (
        jsonify(
            {
                'token': token,
                'kind': 'event',
                'label': event.label,
                'expires_at': expires_at.isoformat(),
                'api_path': f'/share/events/{token}',
                'download_path': f'/share/events/{token}/download',
            }
        ),
        200,
    )


@event_bp.route('/<int:event_id>', methods=['DELETE'])
@jwt_required()
def delete_event(event_id):
    user_id = int(get_jwt_identity())
    event = Event.query.filter_by(id=event_id, user_id=user_id).first()
    if not event:
        return jsonify({'error': 'Event not found'}), 404

    for photo in event.photos:
        photo.event_id = None

    db.session.delete(event)
    db.session.commit()
    return jsonify({'message': 'Event deleted'}), 200
