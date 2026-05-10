import calendar
from collections import OrderedDict
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import func

from photo_collections import photo_collection_query
from models.photo import Photo
from time_utils import utc_naive_to_local


timeline_bp = Blueprint('timeline', __name__)


def _normalize_group(value):
    group = str(value or 'day').strip().lower()
    return group if group in {'day', 'month', 'year'} else None


def _timeline_query(user_id, collection='active'):
    return photo_collection_query(user_id, collection)


def _photo_timestamp(photo):
    if photo.captured_at:
        return photo.captured_at
    return utc_naive_to_local(photo.uploaded_at, current_app.config.get('DISPLAY_TIMEZONE'))


def _bucket_key(timestamp, group):
    if group == 'year':
        return f'{timestamp.year:04d}'
    if group == 'month':
        return f'{timestamp.year:04d}-{timestamp.month:02d}'
    return timestamp.date().isoformat()


def _bucket_metadata(timestamp, group):
    if group == 'year':
        start = datetime(timestamp.year, 1, 1)
        end = datetime(timestamp.year + 1, 1, 1) - timedelta(microseconds=1)
        return {
            'label': f'{timestamp.year}',
            'start': start,
            'end': end,
            'sort': start,
        }

    if group == 'month':
        start = datetime(timestamp.year, timestamp.month, 1)
        if timestamp.month == 12:
            end = datetime(timestamp.year + 1, 1, 1) - timedelta(microseconds=1)
        else:
            end = datetime(timestamp.year, timestamp.month + 1, 1) - timedelta(microseconds=1)
        return {
            'label': f'{calendar.month_name[timestamp.month]} {timestamp.year}',
            'start': start,
            'end': end,
            'sort': start,
        }

    start = datetime.combine(timestamp.date(), datetime.min.time())
    end = datetime.combine(timestamp.date(), datetime.max.time())
    return {
        'label': timestamp.strftime('%d %b %Y'),
        'start': start,
        'end': end,
        'sort': start,
    }


def _parse_filter_datetime(value):
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


@timeline_bp.route('', methods=['GET'])
@jwt_required()
def get_timeline():
    user_id = int(get_jwt_identity())
    group = _normalize_group(request.args.get('group', 'day'))
    if not group:
        return jsonify({'error': 'Unsupported timeline group. Use day, month, or year.'}), 400

    collection = request.args.get('collection', 'active')
    start_filter = _parse_filter_datetime(request.args.get('start'))
    end_filter = _parse_filter_datetime(request.args.get('end'))
    if request.args.get('start') and start_filter is None:
        return jsonify({'error': 'Invalid timeline start filter.'}), 400
    if request.args.get('end') and end_filter is None:
        return jsonify({'error': 'Invalid timeline end filter.'}), 400
    if start_filter and end_filter and start_filter > end_filter:
        return jsonify({'error': 'Timeline start filter must be before end filter.'}), 400

    timestamp_expr = func.coalesce(Photo.captured_at, Photo.uploaded_at)
    photos = (
        _timeline_query(user_id, collection)
        .order_by(timestamp_expr.desc(), Photo.id.desc())
        .all()
    )

    periods = OrderedDict()
    for photo in photos:
        timestamp = _photo_timestamp(photo)
        if not timestamp:
            continue
        if start_filter and timestamp < start_filter:
            continue
        if end_filter and timestamp > end_filter:
            continue

        key = _bucket_key(timestamp, group)
        if key not in periods:
            meta = _bucket_metadata(timestamp, group)
            periods[key] = {
                'key': key,
                'label': meta['label'],
                'start': meta['start'].isoformat(),
                'end': meta['end'].isoformat(),
                'sort': meta['sort'],
                'count': 0,
                'photos': [],
            }

        payload = photo.to_dict()
        payload['event_label'] = photo.event.label if getattr(photo, 'event', None) else None
        periods[key]['count'] += 1
        periods[key]['photos'].append(payload)

    timeline_payload = sorted(periods.values(), key=lambda item: item['sort'], reverse=True)
    for item in timeline_payload:
        item.pop('sort', None)

    return jsonify({'group': group, 'periods': timeline_payload}), 200
