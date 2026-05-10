import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO

from flask import current_app, jsonify, send_file
from itsdangerous import BadSignature, URLSafeSerializer
from werkzeug.utils import secure_filename


SHARE_SALT = 'memorylens-share'


def _serializer():
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt=SHARE_SALT)


def _utc_now():
    return datetime.now(timezone.utc)


def create_share_token(kind, payload, expires_in_hours=72):
    expires_in_hours = max(1, min(int(expires_in_hours or 72), 24 * 30))
    expires_at = _utc_now() + timedelta(hours=expires_in_hours)
    token_payload = {
        'kind': kind,
        'payload': payload,
        'expires_at': expires_at.isoformat(),
    }
    return _serializer().dumps(token_payload), expires_at


def load_share_token(token, expected_kind):
    try:
        data = _serializer().loads(token)
    except BadSignature:
        return None, (jsonify({'error': 'Invalid share link'}), 404)

    if data.get('kind') != expected_kind:
        return None, (jsonify({'error': 'Invalid share link'}), 404)

    try:
        expires_at = datetime.fromisoformat(data['expires_at'])
    except (KeyError, TypeError, ValueError):
        return None, (jsonify({'error': 'Invalid share link'}), 404)

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= _utc_now():
        return None, (jsonify({'error': 'This share link has expired'}), 410)

    return {'payload': data.get('payload') or {}, 'expires_at': expires_at}, None


def archive_download_name(label, suffix='zip'):
    safe = secure_filename(label or 'memorylens-export') or 'memorylens-export'
    return f'{safe}.{suffix}'


def _photo_archive_entry_name(photo):
    source_name = secure_filename(photo.original_filename or photo.filename) or photo.filename
    _source_root, source_ext = os.path.splitext(source_name)
    source_ext = source_ext or '.jpg'

    display_name = str(photo.display_name or '').strip()
    if display_name:
        safe_display = secure_filename(display_name) or f'photo-{photo.id}'
        return f'{safe_display}{source_ext}'

    return source_name


def build_photo_archive(photos, upload_root, archive_label, manifest_extra=None):
    available = []
    for photo in photos:
        filepath = photo.filepath(upload_root)
        if os.path.exists(filepath):
            available.append((photo, filepath))

    if not available:
        return None

    buffer = BytesIO()
    manifest = {
        'exported_at': _utc_now().isoformat(),
        'photo_count': len(available),
        'photos': [],
    }
    if manifest_extra:
        manifest.update(manifest_extra)

    used_names = {}
    with zipfile.ZipFile(buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
        for photo, filepath in available:
            base_name = _photo_archive_entry_name(photo)
            name, ext = os.path.splitext(base_name)
            duplicate_count = used_names.get(base_name, 0)
            used_names[base_name] = duplicate_count + 1
            archive_name = base_name if duplicate_count == 0 else f'{name}-{duplicate_count + 1}{ext}'

            archive.write(filepath, arcname=archive_name)
            manifest['photos'].append(
                {
                    'id': photo.id,
                    'filename': archive_name,
                    'scene': photo.scene,
                    'captured_at': photo.captured_at.isoformat() if photo.captured_at else None,
                    'uploaded_at': photo.uploaded_at.isoformat() if photo.uploaded_at else None,
                }
            )

        archive.writestr('manifest.json', json.dumps(manifest, indent=2))

    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=archive_download_name(archive_label),
    )
