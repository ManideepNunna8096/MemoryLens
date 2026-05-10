from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import func

from models import db
from models.photo import Photo
from photo_collections import photo_collection_query


folder_bp = Blueprint('folders', __name__)


def _normalized_folder_name(raw_name):
    candidate = str(raw_name or '').strip()
    candidate = candidate.replace('\\', ' ').replace('/', ' ')
    candidate = ' '.join(candidate.split())
    if not candidate:
        return None

    max_length = 120
    candidate = candidate[:max_length].strip()
    return candidate or None


def _folder_label_expression():
    return func.coalesce(Photo.custom_folder, Photo.scene)


def _photo_collection_query(user_id, collection='active'):
    return photo_collection_query(user_id, collection)


def _ready_folder_query(user_id, collection='active'):
    return _photo_collection_query(user_id, collection).filter(Photo.processing_status == 'ready')


def _folder_records(user_id, collection='active'):
    counts = {}
    photos = _ready_folder_query(user_id, collection).all()
    for photo in photos:
        folder_name = photo.folder_label()
        entry = counts.setdefault(
            folder_name,
            {
                'name': folder_name,
                'count': 0,
                'custom_count': 0,
                'ai_count': 0,
            },
        )
        entry['count'] += 1
        if str(photo.custom_folder or '').strip():
            entry['custom_count'] += 1
        else:
            entry['ai_count'] += 1

    payloads = []
    for entry in counts.values():
        if entry['custom_count'] and entry['ai_count']:
            kind = 'mixed'
        elif entry['custom_count']:
            kind = 'custom'
        else:
            kind = 'ai'
        payloads.append(
            {
                **entry,
                'kind': kind,
                'deletable': entry['custom_count'] > 0 and entry['ai_count'] == 0,
            }
        )

    return sorted(payloads, key=lambda item: (-item['count'], item['name'].lower()))


def _folder_photos(user_id, folder_name):
    normalized_folder = _normalized_folder_name(folder_name)
    if not normalized_folder:
        return []

    return Photo.query.filter(
        Photo.user_id == user_id,
        func.lower(_folder_label_expression()) == normalized_folder.lower(),
    ).all()


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


def _apply_folder_assignment(photo, folder_name):
    normalized_folder = _normalized_folder_name(folder_name)
    scene_name = str(photo.scene or '').strip()
    if not normalized_folder or normalized_folder.lower() == scene_name.lower():
        photo.custom_folder = None
    else:
        photo.custom_folder = normalized_folder


@folder_bp.route('/all', methods=['GET'])
@jwt_required()
def get_all_folders():
    user_id = int(get_jwt_identity())
    collection = request.args.get('collection', 'active')
    return jsonify(_folder_records(user_id, collection)), 200


@folder_bp.route('/move-photos', methods=['POST'])
@jwt_required()
def move_photos_to_folder():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    photo_ids = _parse_photo_ids(data)
    if not photo_ids:
        return jsonify({'error': 'Select at least 1 photo to move'}), 400

    photos = Photo.query.filter(Photo.user_id == user_id, Photo.id.in_(photo_ids)).all()
    if len(photos) != len(photo_ids):
        return jsonify({'error': 'One or more selected photos were not found'}), 404

    target_folder = _normalized_folder_name(data.get('target_folder'))
    for photo in photos:
        _apply_folder_assignment(photo, target_folder)

    db.session.commit()
    return (
        jsonify(
            {
                'moved_count': len(photos),
                'folder_name': target_folder,
                'message': target_folder or 'Moved photos back to AI folders',
            }
        ),
        200,
    )


@folder_bp.route('/rename', methods=['POST'])
@jwt_required()
def rename_folder():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    source_folder = _normalized_folder_name(data.get('source_folder'))
    target_folder = _normalized_folder_name(data.get('target_folder'))

    if not source_folder:
        return jsonify({'error': 'Folder name is required'}), 400
    if not target_folder:
        return jsonify({'error': 'New folder name is required'}), 400
    if source_folder.lower() == target_folder.lower():
        return jsonify({'error': 'Choose a different folder name'}), 400

    photos = _folder_photos(user_id, source_folder)
    if not photos:
        return jsonify({'error': 'Folder not found'}), 404

    for photo in photos:
        _apply_folder_assignment(photo, target_folder)

    db.session.commit()
    return (
        jsonify(
            {
                'renamed_count': len(photos),
                'source_folder': source_folder,
                'target_folder': target_folder,
            }
        ),
        200,
    )


@folder_bp.route('/merge', methods=['POST'])
@jwt_required()
def merge_folders():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    raw_sources = data.get('source_folders') or []
    target_folder = _normalized_folder_name(data.get('target_folder'))

    source_folders = []
    seen = set()
    for item in raw_sources:
        normalized = _normalized_folder_name(item)
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        source_folders.append(normalized)

    if not target_folder:
        return jsonify({'error': 'Target folder name is required'}), 400

    source_folders = [name for name in source_folders if name.lower() != target_folder.lower()]
    if not source_folders:
        return jsonify({'error': 'Select at least 1 source folder to merge'}), 400

    lower_sources = [name.lower() for name in source_folders]
    photos = Photo.query.filter(
        Photo.user_id == user_id,
        func.lower(_folder_label_expression()).in_(lower_sources),
    ).all()
    if not photos:
        return jsonify({'error': 'No photos were found in the selected folders'}), 404

    for photo in photos:
        _apply_folder_assignment(photo, target_folder)

    db.session.commit()
    return (
        jsonify(
            {
                'merged_count': len(photos),
                'source_folders': source_folders,
                'target_folder': target_folder,
            }
        ),
        200,
    )


@folder_bp.route('/delete', methods=['POST'])
@jwt_required()
def delete_folder():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    folder_name = _normalized_folder_name(data.get('folder_name'))
    if not folder_name:
        return jsonify({'error': 'Folder name is required'}), 400

    photos = _folder_photos(user_id, folder_name)
    if not photos:
        return jsonify({'deleted_count': 0, 'message': 'Folder already gone'}), 200

    ai_backed_photos = [photo for photo in photos if not str(photo.custom_folder or '').strip()]
    if ai_backed_photos:
        return jsonify({'error': 'AI scene folders cannot be deleted directly. Rename or merge them instead.'}), 400

    for photo in photos:
        photo.custom_folder = None

    db.session.commit()
    return jsonify({'deleted_count': len(photos), 'message': 'Folder deleted'}), 200
