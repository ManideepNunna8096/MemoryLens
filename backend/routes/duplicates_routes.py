import os
from collections import OrderedDict

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import func

from duplicate_detection import (
    SIMILAR_DHASH_THRESHOLD,
    compute_duplicate_signatures,
    dhash_confidence,
    dhash_distance,
)
from event_album_service import delete_orphaned_event
from models import db
from models.event import Event
from models.photo import Photo
from time_utils import utcnow


duplicates_bp = Blueprint('duplicates', __name__)


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


def _visible_photos_query(user_id, include_trashed=False):
    query = Photo.query.filter(Photo.user_id == user_id)
    if not include_trashed:
        query = query.filter(Photo.trashed_at.is_(None))
    return query


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


def _serialize_duplicate_photo(photo):
    payload = photo.to_dict()
    payload['event_label'] = photo.event.label if getattr(photo, 'event', None) else None
    return payload


def _build_exact_groups(user_id):
    duplicate_hash_rows = (
        db.session.query(Photo.sha256_hash, func.count(Photo.id).label('photo_count'))
        .filter(
            Photo.user_id == user_id,
            Photo.trashed_at.is_(None),
            Photo.sha256_hash.is_not(None),
            Photo.sha256_hash != '',
        )
        .group_by(Photo.sha256_hash)
        .having(func.count(Photo.id) > 1)
        .all()
    )

    duplicate_counts = {row.sha256_hash: int(row.photo_count) for row in duplicate_hash_rows}
    duplicate_hashes = list(duplicate_counts.keys())
    if not duplicate_hashes:
        return [], set()

    photos = (
        _visible_photos_query(user_id)
        .filter(Photo.sha256_hash.in_(duplicate_hashes))
        .order_by(Photo.sha256_hash.asc(), Photo.uploaded_at.asc(), Photo.id.asc())
        .all()
    )

    groups = OrderedDict()
    exact_photo_ids = set()
    for photo in photos:
        exact_photo_ids.add(photo.id)
        group = groups.setdefault(
            photo.sha256_hash,
            {
                'hash': photo.sha256_hash,
                'type': 'exact',
                'confidence_score': 100,
                'count': duplicate_counts.get(photo.sha256_hash, 0),
                'photos': [],
                'last_uploaded_at': photo.uploaded_at,
            },
        )
        group['photos'].append(_serialize_duplicate_photo(photo))
        if photo.uploaded_at > group['last_uploaded_at']:
            group['last_uploaded_at'] = photo.uploaded_at

    payload_groups = list(groups.values())
    for group in payload_groups:
        group['reclaimable_count'] = max(group['count'] - 1, 0)
        group['kept_photo_id'] = group['photos'][0]['id'] if group['photos'] else None

    return payload_groups, exact_photo_ids


def _similar_group_components(photos):
    components = []
    if len(photos) < 2:
        return components

    visited = set()
    for index, photo in enumerate(photos):
        if photo.id in visited:
            continue

        stack = [index]
        component_indexes = []
        while stack:
            current_index = stack.pop()
            current_photo = photos[current_index]
            if current_photo.id in visited:
                continue

            visited.add(current_photo.id)
            component_indexes.append(current_index)
            for next_index, candidate in enumerate(photos):
                if candidate.id in visited:
                    continue
                distance = dhash_distance(current_photo.dhash, candidate.dhash)
                if distance is not None and distance <= SIMILAR_DHASH_THRESHOLD:
                    stack.append(next_index)

        if len(component_indexes) > 1:
            components.append([photos[item_index] for item_index in sorted(component_indexes)])

    return components


def _build_similar_groups(user_id, excluded_photo_ids):
    query = (
        _visible_photos_query(user_id)
        .filter(Photo.dhash.is_not(None), Photo.dhash != '', Photo.scene.is_not(None), Photo.scene != '')
        .order_by(Photo.scene.asc(), Photo.uploaded_at.asc(), Photo.id.asc())
    )
    if excluded_photo_ids:
        query = query.filter(Photo.id.notin_(sorted(excluded_photo_ids)))

    photos = query.all()
    scene_buckets = OrderedDict()
    for photo in photos:
        scene_key = str(photo.scene or '').strip().casefold()
        scene_buckets.setdefault(scene_key, []).append(photo)

    groups = []
    for bucket in scene_buckets.values():
        for component in _similar_group_components(bucket):
            pairwise_distances = []
            for index, left in enumerate(component):
                for right in component[index + 1:]:
                    distance = dhash_distance(left.dhash, right.dhash)
                    if distance is not None:
                        pairwise_distances.append(distance)

            max_distance = max(pairwise_distances) if pairwise_distances else 0
            confidence_score = dhash_confidence(max_distance)
            groups.append(
                {
                    'hash': component[0].dhash,
                    'type': 'similar',
                    'confidence_score': confidence_score,
                    'count': len(component),
                    'distance': max_distance,
                    'photos': [_serialize_duplicate_photo(photo) for photo in component],
                    'last_uploaded_at': max(photo.uploaded_at for photo in component),
                    'reclaimable_count': max(len(component) - 1, 0),
                    'kept_photo_id': component[0].id,
                }
            )

    return groups


def _build_duplicate_payload(user_id):
    exact_groups, exact_photo_ids = _build_exact_groups(user_id)
    similar_groups = _build_similar_groups(user_id, exact_photo_ids)

    groups = exact_groups + similar_groups
    groups.sort(
        key=lambda item: (
            0 if item['type'] == 'exact' else 1,
            -item['count'],
            -item['confidence_score'],
            -item['last_uploaded_at'].timestamp(),
        )
    )

    unfingerprinted_count = (
        Photo.query.filter(
            Photo.user_id == user_id,
            Photo.trashed_at.is_(None),
            ((Photo.sha256_hash.is_(None)) | (Photo.sha256_hash == '') | (Photo.dhash.is_(None)) | (Photo.dhash == '')),
        ).count()
    )

    duplicate_photo_count = sum(group['count'] for group in groups)
    reclaimable_count = sum(group['reclaimable_count'] for group in groups)

    for group in groups:
        group.pop('last_uploaded_at', None)

    return {
        'groups': groups,
        'summary': {
            'group_count': len(groups),
            'duplicate_photo_count': duplicate_photo_count,
            'reclaimable_count': reclaimable_count,
            'unhashed_count': unfingerprinted_count,
        },
    }


def _find_duplicate_group_for_photo(user_id, photo_id):
    payload = _build_duplicate_payload(user_id)
    for group in payload['groups']:
        if any(photo['id'] == photo_id for photo in group['photos']):
            return group
    return None


@duplicates_bp.route('', methods=['GET'])
@jwt_required()
def get_duplicates():
    user_id = int(get_jwt_identity())
    return jsonify(_build_duplicate_payload(user_id)), 200


@duplicates_bp.route('/scan', methods=['POST'])
@jwt_required()
def scan_duplicates():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    force = bool(data.get('force'))

    query = Photo.query.filter(Photo.user_id == user_id)
    if not force:
        query = query.filter(
            (Photo.sha256_hash.is_(None))
            | (Photo.sha256_hash == '')
            | (Photo.dhash.is_(None))
            | (Photo.dhash == '')
        )

    photos = query.all()
    scanned_count = 0
    skipped_count = 0
    missing_files = []

    for photo in photos:
        filepath = photo.filepath(current_app.config['UPLOAD_FOLDER'])
        if not os.path.exists(filepath):
            missing_files.append({'id': photo.id, 'filename': photo.original_filename or photo.filename})
            skipped_count += 1
            continue

        photo.sha256_hash, photo.dhash = compute_duplicate_signatures(filepath)
        scanned_count += 1

    db.session.commit()
    payload = _build_duplicate_payload(user_id)
    return (
        jsonify(
            {
                'message': 'Duplicate scan completed',
                'scanned_count': scanned_count,
                'skipped_count': skipped_count,
                'missing_files': missing_files,
                **payload,
            }
        ),
        200,
    )


@duplicates_bp.route('/trash', methods=['POST'])
@jwt_required()
def trash_duplicates():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    photo_ids = _parse_photo_ids(data)
    if not photo_ids:
        return jsonify({'error': 'Select at least 1 duplicate photo to trash'}), 400

    photos = (
        Photo.query.filter(
            Photo.user_id == user_id,
            Photo.id.in_(photo_ids),
            Photo.trashed_at.is_(None),
        )
        .all()
    )
    if len(photos) != len(photo_ids):
        return jsonify({'error': 'One or more selected photos were not found'}), 404

    touched_event_ids = {photo.event_id for photo in photos if photo.event_id}
    now = utcnow()
    for photo in photos:
        photo.trashed_at = now
        photo.is_archived = False

    db.session.flush()
    updated_events = _refresh_touched_events(user_id, touched_event_ids)
    db.session.commit()

    return jsonify({'trashed_count': len(photos), 'events': updated_events, **_build_duplicate_payload(user_id)}), 200


@duplicates_bp.route('/keep', methods=['POST'])
@jwt_required()
def keep_duplicate():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    keep_photo_id = data.get('photo_id')
    try:
        keep_photo_id = int(keep_photo_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Choose the photo you want to keep'}), 400

    keep_photo = Photo.query.filter_by(id=keep_photo_id, user_id=user_id).first()
    if not keep_photo or keep_photo.trashed_at is not None:
        return jsonify({'error': 'Selected photo is unavailable for duplicate cleanup'}), 404

    group = _find_duplicate_group_for_photo(user_id, keep_photo.id)
    if not group:
        return jsonify({'error': 'This photo is no longer part of a duplicate group'}), 400

    group_photo_ids = [photo['id'] for photo in group['photos']]
    group_photos = (
        Photo.query.filter(
            Photo.user_id == user_id,
            Photo.id.in_(group_photo_ids),
            Photo.trashed_at.is_(None),
        )
        .order_by(Photo.uploaded_at.asc(), Photo.id.asc())
        .all()
    )

    if len(group_photos) < 2:
        return jsonify({'error': 'This photo is no longer part of a duplicate group'}), 400

    touched_event_ids = {photo.event_id for photo in group_photos if photo.event_id}
    now = utcnow()
    trashed_count = 0
    for photo in group_photos:
        if photo.id == keep_photo.id:
            continue
        photo.trashed_at = now
        photo.is_archived = False
        trashed_count += 1

    db.session.flush()
    updated_events = _refresh_touched_events(user_id, touched_event_ids)
    db.session.commit()

    return (
        jsonify(
            {
                'message': 'Kept selected photo and moved the other duplicates to trash',
                'kept_photo_id': keep_photo.id,
                'trashed_count': trashed_count,
                'events': updated_events,
                **_build_duplicate_payload(user_id),
            }
        ),
        200,
    )
