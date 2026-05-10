import mimetypes
import os
import uuid

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import case, func
from werkzeug.utils import secure_filename

from background_tasks import submit_photo_processing_job
from duplicate_detection import compute_duplicate_signatures
from event_album_service import delete_orphaned_event, recompute_event_metadata
from models import db
from models.event import Event
from models.job import BackgroundJob
from models.photo import Photo
from photo_collections import photo_collection_query
from share_utils import build_photo_archive, create_share_token
from time_utils import utcnow
from utils.logger import get_logger


photo_bp = Blueprint('photos', __name__)
upload_logger = get_logger('UPLOAD')
done_logger = get_logger('DONE')


def allowed_file(filename):
    allowed = current_app.config['ALLOWED_EXTENSIONS']
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def _photo_collection_query(user_id, collection='active'):
    return photo_collection_query(user_id, collection)


def _apply_sort(query, sort_key):
    sort_key = str(sort_key or 'newest').strip().lower()
    date_expr = func.coalesce(Photo.captured_at, Photo.uploaded_at)
    folder_expr = func.lower(func.coalesce(Photo.custom_folder, Photo.scene, ''))

    if sort_key == 'oldest':
        return query.order_by(date_expr.asc(), Photo.id.asc())
    if sort_key == 'scene':
        return query.order_by(folder_expr.asc(), date_expr.desc())
    if sort_key == 'processing':
        status_rank = case(
            (Photo.processing_status == 'failed', 0),
            (Photo.processing_status == 'queued', 1),
            (Photo.processing_status == 'in_progress', 2),
            (Photo.processing_status == 'ready', 3),
            else_=4,
        )
        return query.order_by(status_rank.asc(), date_expr.desc())

    return query.order_by(date_expr.desc(), Photo.id.desc())


def _parse_photo_ids(data):
    ids = data.get('photo_ids') or []
    if not isinstance(ids, list):
        return []
    parsed = []
    for photo_id in ids:
        try:
            parsed.append(int(photo_id))
        except (TypeError, ValueError):
            continue
    return sorted(set(parsed))


def _owned_photos(user_id, photo_ids):
    if not photo_ids:
        return []
    return (
        Photo.query.filter(
            Photo.user_id == user_id,
            Photo.id.in_(photo_ids),
        )
        .order_by(Photo.uploaded_at.desc())
        .all()
    )


def _delete_photo_file(photo):
    filepath = photo.filepath(current_app.config['UPLOAD_FOLDER'])
    if os.path.exists(filepath):
        os.remove(filepath)


def _normalized_display_name(raw_name):
    candidate = str(raw_name or '').strip()
    candidate = candidate.replace('\\', ' ').replace('/', ' ')
    candidate = ' '.join(candidate.split())
    candidate = os.path.basename(candidate)
    if not candidate:
        return None

    max_length = 200
    candidate = candidate[:max_length].strip()
    return candidate or None


def _normalized_folder_name(raw_name):
    candidate = str(raw_name or '').strip()
    candidate = candidate.replace('\\', ' ').replace('/', ' ')
    candidate = ' '.join(candidate.split())
    candidate = os.path.basename(candidate)
    if not candidate:
        return None

    max_length = 120
    candidate = candidate[:max_length].strip()
    return candidate or None


def _refresh_touched_events(user_id, event_ids):
    payload = []
    for event_id in sorted({int(event_id) for event_id in event_ids if event_id}):
        event = Event.query.filter_by(id=event_id, user_id=user_id).first()
        if not event:
            continue
        delete_orphaned_event(event)
        if db.session.deleted and event in db.session.deleted:
            continue
        payload.append(event.to_dict())
    return payload


@photo_bp.route('/upload', methods=['POST'])
@jwt_required()
def upload_photos():
    user_id = int(get_jwt_identity())
    files = request.files.getlist('files')

    if not files:
        return jsonify({'error': 'No files uploaded'}), 400

    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)

    supported_files = []
    rejected_files = []
    upload_logger.info(f'Received upload request from user_id={user_id} with {len(files)} file(s)')
    for file in files:
        if file and allowed_file(file.filename):
            upload_logger.info(f'Received file="{file.filename}" for user_id={user_id}')
            supported_files.append(file)
        else:
            rejected_files.append(
                {
                    'filename': getattr(file, 'filename', 'unknown'),
                    'error': 'Unsupported file type',
                }
        )

    if not supported_files:
        return jsonify({'error': 'No supported image files were uploaded', 'rejected': rejected_files}), 400

    if rejected_files:
        upload_logger.info(f'Rejected {len(rejected_files)} unsupported file(s) for user_id={user_id}')

    job = BackgroundJob(
        job_type='photo_processing',
        user_id=user_id,
        status='queued',
        total_items=len(supported_files),
        completed_items=0,
    )
    db.session.add(job)

    queued_photos = []
    for file in supported_files:
        original_name = file.filename or 'upload'
        safe_name = secure_filename(original_name) or f'photo-{uuid.uuid4().hex}.jpg'
        ext = safe_name.rsplit('.', 1)[1].lower()
        filename = f'{uuid.uuid4().hex}.{ext}'
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)

        sha256_hash, dhash = compute_duplicate_signatures(filepath)

        photo = Photo(
            filename=filename,
            original_filename=original_name,
            scene='Processing',
            processing_status='queued',
            sha256_hash=sha256_hash,
            dhash=dhash,
            user_id=user_id,
        )
        db.session.add(photo)
        queued_photos.append(photo)

    db.session.commit()

    photo_ids = [photo.id for photo in queued_photos]
    submit_photo_processing_job(current_app._get_current_object(), job.id, photo_ids)
    done_logger.info(
        f'Queued photo processing job_id={job.id} for user_id={user_id} with {len(photo_ids)} photo(s)'
    )
    db.session.expire_all()

    refreshed_job = db.session.get(BackgroundJob, job.id)
    refreshed_photos = Photo.query.filter(Photo.id.in_(photo_ids)).order_by(Photo.uploaded_at.desc()).all()
    return (
        jsonify(
            {
                'job': refreshed_job.to_dict(),
                'photos': [photo.to_dict() for photo in refreshed_photos],
                'rejected': rejected_files,
            }
        ),
        202,
    )


@photo_bp.route('/all', methods=['GET'])
@jwt_required()
def get_all_photos():
    user_id = int(get_jwt_identity())
    scene = request.args.get('scene')
    status = request.args.get('status')
    collection = request.args.get('collection', 'active')
    sort_key = request.args.get('sort', 'newest')

    query = _photo_collection_query(user_id, collection)
    if scene:
        query = query.filter(func.coalesce(Photo.custom_folder, Photo.scene) == scene)
    if status:
        query = query.filter(Photo.processing_status == status)

    query = _apply_sort(query, sort_key)

    if request.args.get('page') or request.args.get('page_size'):
        page = max(request.args.get('page', default=1, type=int), 1)
        page_size = min(max(request.args.get('page_size', default=24, type=int), 1), 100)
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return (
            jsonify(
                {
                    'items': [photo.to_dict() for photo in items],
                    'page': page,
                    'page_size': page_size,
                    'total': total,
                    'has_more': page * page_size < total,
                }
            ),
            200,
        )

    photos = query.all()
    return jsonify([photo.to_dict() for photo in photos]), 200


@photo_bp.route('/scenes', methods=['GET'])
@jwt_required()
def get_scenes():
    user_id = int(get_jwt_identity())
    collection = request.args.get('collection', 'active')

    photos = (
        _photo_collection_query(user_id, collection)
        .filter(Photo.processing_status == 'ready')
        .all()
    )

    counts = {}
    for photo in photos:
        folder_label = photo.folder_label()
        counts[folder_label] = counts.get(folder_label, 0) + 1

    scenes = [{'scene': scene, 'count': count} for scene, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    return jsonify(scenes), 200


@photo_bp.route('/bulk', methods=['POST'])
@jwt_required()
def bulk_photo_action():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    action = str(data.get('action', '')).strip().lower()
    photo_ids = _parse_photo_ids(data)

    if not action:
        return jsonify({'error': 'Action is required'}), 400
    if not photo_ids:
        return jsonify({'error': 'Select at least 1 photo'}), 400

    photos = _owned_photos(user_id, photo_ids)
    if len(photos) != len(photo_ids):
        return jsonify({'error': 'One or more selected photos were not found'}), 404

    touched_event_ids = {photo.event_id for photo in photos if photo.event_id}
    message = 'Updated photos'

    if action == 'delete':
        for photo in photos:
            _delete_photo_file(photo)
            db.session.delete(photo)
        message = 'Deleted selected photos'
    elif action == 'favorite':
        for photo in photos:
            photo.is_favorite = True
        message = 'Added to favorites'
    elif action == 'unfavorite':
        for photo in photos:
            photo.is_favorite = False
        message = 'Removed from favorites'
    elif action == 'archive':
        for photo in photos:
            photo.is_archived = True
            photo.trashed_at = None
        message = 'Archived selected photos'
    elif action == 'unarchive':
        for photo in photos:
            photo.is_archived = False
        message = 'Moved photos back to the gallery'
    elif action == 'trash':
        now = utcnow()
        for photo in photos:
            photo.trashed_at = now
            photo.is_archived = False
        message = 'Moved photos to trash'
    elif action == 'restore':
        for photo in photos:
            photo.trashed_at = None
        message = 'Restored photos'
    elif action == 'move_to_event':
        target_event_id = data.get('event_id')
        try:
            target_event_id = int(target_event_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Select an album to move these photos into'}), 400

        target_event = Event.query.filter_by(id=target_event_id, user_id=user_id).first()
        if not target_event:
            return jsonify({'error': 'Target album not found'}), 404

        for photo in photos:
            photo.event_id = target_event.id
        touched_event_ids.add(target_event.id)
        recompute_event_metadata(target_event)
        message = 'Moved photos to album'
    elif action == 'set_folder':
        normalized_folder = _normalized_folder_name(data.get('folder_name'))
        for photo in photos:
            scene_label = str(photo.scene or '').strip()
            if normalized_folder and normalized_folder.casefold() != scene_label.casefold():
                photo.custom_folder = normalized_folder
            else:
                photo.custom_folder = None
        message = normalized_folder or 'Moved photos back to AI folders'
    else:
        return jsonify({'error': 'Unsupported bulk action'}), 400

    db.session.flush()
    updated_events = _refresh_touched_events(user_id, touched_event_ids)
    db.session.commit()

    return jsonify({'message': message, 'updated_count': len(photos), 'events': updated_events}), 200


@photo_bp.route('/retry', methods=['POST'])
@jwt_required()
def retry_failed_photos():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    photo_ids = _parse_photo_ids(data)

    query = Photo.query.filter(Photo.user_id == user_id, Photo.processing_status == 'failed')
    if photo_ids:
        query = query.filter(Photo.id.in_(photo_ids))

    photos = query.all()
    if not photos:
        return jsonify({'error': 'No failed photos were found to retry'}), 400

    job = BackgroundJob(
        job_type='photo_processing',
        user_id=user_id,
        status='queued',
        total_items=len(photos),
        completed_items=0,
    )
    db.session.add(job)

    for photo in photos:
        photo.scene = 'Processing'
        photo.processing_status = 'queued'
        photo.processing_error = None
        photo.clip_vector_pg = None
        photo.clip_model_version = None
        photo.scene_model_version = None

    db.session.commit()
    submit_photo_processing_job(current_app._get_current_object(), job.id, [photo.id for photo in photos])
    db.session.expire_all()
    refreshed_job = db.session.get(BackgroundJob, job.id)

    return jsonify({'job': refreshed_job.to_dict(), 'message': 'Retry started'}), 202


@photo_bp.route('/export', methods=['POST'])
@jwt_required()
def export_photos():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    photo_ids = _parse_photo_ids(data)
    if not photo_ids:
        return jsonify({'error': 'Select at least 1 photo to download'}), 400

    photos = _owned_photos(user_id, photo_ids)
    if len(photos) != len(photo_ids):
        return jsonify({'error': 'One or more selected photos were not found'}), 404

    response = build_photo_archive(
        photos,
        current_app.config['UPLOAD_FOLDER'],
        data.get('label') or 'gallery-selection',
        manifest_extra={'kind': 'photo_export'},
    )
    if not response:
        return jsonify({'error': 'No photo files were available to export'}), 404
    return response


@photo_bp.route('/share', methods=['POST'])
@jwt_required()
def share_photos():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    photo_ids = _parse_photo_ids(data)
    if not photo_ids:
        return jsonify({'error': 'Select at least 1 photo to share'}), 400

    photos = _owned_photos(user_id, photo_ids)
    if len(photos) != len(photo_ids):
        return jsonify({'error': 'One or more selected photos were not found'}), 404

    label = str(data.get('label', '')).strip() or (
        photos[0].original_filename if len(photos) == 1 else f'{len(photos)} shared photos'
    )
    token, expires_at = create_share_token(
        'photos',
        {
            'user_id': user_id,
            'photo_ids': [photo.id for photo in photos],
            'label': label[:150],
        },
        expires_in_hours=data.get('expires_in_hours', 72),
    )
    return (
        jsonify(
            {
                'token': token,
                'kind': 'photos',
                'label': label[:150],
                'expires_at': expires_at.isoformat(),
                'api_path': f'/share/photos/{token}',
                'download_path': f'/share/photos/{token}/download',
            }
        ),
        200,
    )


@photo_bp.route('/<int:photo_id>', methods=['PATCH'])
@photo_bp.route('/<int:photo_id>/rename', methods=['POST'])
@jwt_required()
def rename_photo(photo_id):
    user_id = int(get_jwt_identity())
    photo = Photo.query.filter_by(id=photo_id, user_id=user_id).first()
    if not photo:
        return jsonify({'error': 'Photo not found'}), 404

    data = request.get_json() or {}
    name = str(data.get('name', '')).strip()
    if not name:
        return jsonify({'error': 'Photo name is required'}), 400

    normalized_name = _normalized_display_name(name)
    if not normalized_name:
        return jsonify({'error': 'Photo name is required'}), 400

    photo.display_name = normalized_name
    db.session.commit()
    return jsonify(photo.to_dict()), 200


@photo_bp.route('/<int:photo_id>/file', methods=['GET'])
@jwt_required()
def serve_photo(photo_id):
    user_id = int(get_jwt_identity())
    photo = Photo.query.filter_by(id=photo_id, user_id=user_id).first()

    if not photo:
        return jsonify({'error': 'Photo not found'}), 404

    filepath = photo.filepath(current_app.config['UPLOAD_FOLDER'])
    if not os.path.exists(filepath):
        return jsonify({'error': 'Photo file is missing'}), 404

    mimetype, _ = mimetypes.guess_type(filepath)
    return send_file(filepath, mimetype=mimetype or 'application/octet-stream', conditional=True)


@photo_bp.route('/<int:photo_id>', methods=['DELETE'])
@jwt_required()
def delete_photo(photo_id):
    user_id = int(get_jwt_identity())
    photo = Photo.query.filter_by(id=photo_id, user_id=user_id).first()

    if not photo:
        return jsonify({'error': 'Photo not found'}), 404

    touched_event_ids = {photo.event_id} if photo.event_id else set()
    _delete_photo_file(photo)
    db.session.delete(photo)
    db.session.flush()
    _refresh_touched_events(user_id, touched_event_ids)
    db.session.commit()
    return jsonify({'message': 'Deleted'}), 200
