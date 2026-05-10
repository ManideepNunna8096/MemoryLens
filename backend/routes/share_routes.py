import os

from flask import Blueprint, current_app, jsonify, send_file

from event_album_service import get_visible_event, visible_event_photos_query
from models.photo import Photo
from share_utils import build_photo_archive, load_share_token


share_bp = Blueprint('share', __name__)


def _shared_photo_file_response(photo):
    filepath = photo.filepath(current_app.config['UPLOAD_FOLDER'])
    if not filepath or not os.path.exists(filepath):
        return jsonify({'error': 'Photo file is missing'}), 404
    return send_file(filepath, conditional=True)


@share_bp.route('/photos/<token>', methods=['GET'])
def get_shared_photos(token):
    token_data, error = load_share_token(token, 'photos')
    if error:
        return error

    payload = token_data['payload']
    user_id = int(payload.get('user_id', 0))
    photo_ids = payload.get('photo_ids') or []

    photos = (
        Photo.query.filter(
            Photo.user_id == user_id,
            Photo.id.in_(photo_ids),
            Photo.trashed_at.is_(None),
        )
        .order_by(Photo.uploaded_at.desc())
        .all()
    )

    if not photos:
        return jsonify({'error': 'This share no longer has available photos'}), 404

    return jsonify(
        {
            'kind': 'photos',
            'label': payload.get('label') or 'Shared Photos',
            'expires_at': token_data['expires_at'].isoformat(),
            'photos': [photo.to_dict() for photo in photos],
        }
    ), 200


@share_bp.route('/photos/<token>/file/<int:photo_id>', methods=['GET'])
def get_shared_photo_file(token, photo_id):
    token_data, error = load_share_token(token, 'photos')
    if error:
        return error

    payload = token_data['payload']
    photo_ids = {int(item) for item in (payload.get('photo_ids') or [])}
    if photo_id not in photo_ids:
        return jsonify({'error': 'Photo not found in this share'}), 404

    photo = Photo.query.filter(
        Photo.id == photo_id,
        Photo.user_id == int(payload.get('user_id', 0)),
        Photo.trashed_at.is_(None),
    ).first()
    if not photo:
        return jsonify({'error': 'Photo not found'}), 404

    return _shared_photo_file_response(photo)


@share_bp.route('/photos/<token>/download', methods=['GET'])
def download_shared_photos(token):
    token_data, error = load_share_token(token, 'photos')
    if error:
        return error

    payload = token_data['payload']
    photos = (
        Photo.query.filter(
            Photo.user_id == int(payload.get('user_id', 0)),
            Photo.id.in_(payload.get('photo_ids') or []),
            Photo.trashed_at.is_(None),
        )
        .order_by(Photo.uploaded_at.desc())
        .all()
    )
    response = build_photo_archive(
        photos,
        current_app.config['UPLOAD_FOLDER'],
        payload.get('label') or 'shared-photos',
        manifest_extra={'kind': 'shared_photos'},
    )
    if not response:
        return jsonify({'error': 'No photos are available to download'}), 404
    return response


@share_bp.route('/events/<token>', methods=['GET'])
def get_shared_event(token):
    token_data, error = load_share_token(token, 'event')
    if error:
        return error

    payload = token_data['payload']
    event = get_visible_event(int(payload.get('event_id', 0)), int(payload.get('user_id', 0)))
    if not event:
        return jsonify({'error': 'This shared album is no longer available'}), 404

    photos = visible_event_photos_query(event.user_id, event.id).order_by(Photo.uploaded_at.desc()).all()
    return jsonify(
        {
            'kind': 'event',
            'label': event.label,
            'expires_at': token_data['expires_at'].isoformat(),
            'event': event.to_dict(),
            'photos': [photo.to_dict() for photo in photos],
        }
    ), 200


@share_bp.route('/events/<token>/file/<int:photo_id>', methods=['GET'])
def get_shared_event_photo(token, photo_id):
    token_data, error = load_share_token(token, 'event')
    if error:
        return error

    payload = token_data['payload']
    event = get_visible_event(int(payload.get('event_id', 0)), int(payload.get('user_id', 0)))
    if not event:
        return jsonify({'error': 'This shared album is no longer available'}), 404

    photo = Photo.query.filter(
        Photo.id == photo_id,
        Photo.user_id == event.user_id,
        Photo.event_id == event.id,
        Photo.trashed_at.is_(None),
    ).first()
    if not photo:
        return jsonify({'error': 'Photo not found'}), 404

    return _shared_photo_file_response(photo)


@share_bp.route('/events/<token>/download', methods=['GET'])
def download_shared_event(token):
    token_data, error = load_share_token(token, 'event')
    if error:
        return error

    payload = token_data['payload']
    event = get_visible_event(int(payload.get('event_id', 0)), int(payload.get('user_id', 0)))
    if not event:
        return jsonify({'error': 'This shared album is no longer available'}), 404

    photos = visible_event_photos_query(event.user_id, event.id).order_by(Photo.uploaded_at.desc()).all()
    response = build_photo_archive(
        photos,
        current_app.config['UPLOAD_FOLDER'],
        event.label,
        manifest_extra={'kind': 'shared_event', 'event_id': event.id},
    )
    if not response:
        return jsonify({'error': 'No photos are available to download'}), 404
    return response
