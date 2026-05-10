from pathlib import Path
from datetime import datetime

import sqlalchemy as sa
from flask import Blueprint, current_app, jsonify

import ml_services  # noqa: F401 - ensures the ml/ directory is on sys.path
from backup_cli import create_backup_package
from models import BackgroundJob, Event, Photo, User, db
from time_utils import utcnow
from utils.logger import get_logger
from vector_search import pgvector_runtime_status

try:
    import scene_classifier as scene_classifier_module
except Exception:  # pragma: no cover - import is expected to work in normal runtime
    scene_classifier_module = None

try:
    import clip_search as clip_search_module
except Exception:  # pragma: no cover - import is expected to work in normal runtime
    clip_search_module = None

try:
    import event_organizer as event_organizer_module
except Exception:  # pragma: no cover - import is expected to work in normal runtime
    event_organizer_module = None


admin_logger = get_logger('ADMIN')
admin_bp = Blueprint('admin', __name__)


def _safe_count(model):
    return int(db.session.query(sa.func.count(model.id)).scalar() or 0)


def _path_or_none(value):
    if not value:
        return None
    try:
        return Path(value)
    except OSError:
        return None


def _scene_model_status():
    model_path = _path_or_none(getattr(scene_classifier_module, 'MODEL_PATH', None))
    labels_path = _path_or_none(getattr(scene_classifier_module, 'LABELS_PATH', None))
    return {
        'ready': bool(scene_classifier_module) and bool(model_path and labels_path and model_path.exists() and labels_path.exists()),
        'warm_loaded': bool(getattr(scene_classifier_module, '_model', None)),
        'files': {
            'weights_present': bool(model_path and model_path.exists()),
            'labels_present': bool(labels_path and labels_path.exists()),
        },
        'paths': {
            'weights': str(model_path) if model_path else None,
            'labels': str(labels_path) if labels_path else None,
        },
    }


def _clip_model_status():
    model_loaded = bool(getattr(clip_search_module, '_clip_model', None))
    preprocess_loaded = bool(getattr(clip_search_module, '_clip_preprocess', None))
    return {
        'ready': bool(clip_search_module),
        'warm_loaded': model_loaded and preprocess_loaded,
        'model_name': 'ViT-B/32',
        'backend': 'cpu',
    }


def _event_model_status():
    places_path = _path_or_none(getattr(event_organizer_module, 'PLACES365_PATH', None))
    return {
        'ready': bool(event_organizer_module) and bool(places_path and places_path.exists()),
        'warm_loaded': False,
        'files': {
            'places365_labels_present': bool(places_path and places_path.exists()),
        },
        'paths': {
            'places365_labels': str(places_path) if places_path else None,
        },
    }


def _backup_status():
    backups_dir = Path(current_app.root_path) / 'backups'
    if not backups_dir.exists():
        return {
            'available': False,
            'path': str(backups_dir),
            'latest': None,
        }

    candidates = [candidate for candidate in backups_dir.glob('*.manifest.json') if candidate.is_file()]
    if not candidates:
        candidates = [candidate for candidate in backups_dir.glob('*.dump') if candidate.is_file()]
    if not candidates:
        candidates = [candidate for candidate in backups_dir.glob('*.zip') if candidate.is_file()]
    if not candidates:
        return {
            'available': False,
            'path': str(backups_dir),
            'latest': None,
        }

    latest = max(candidates, key=lambda item: item.stat().st_mtime)
    return {
        'available': True,
        'path': str(backups_dir),
        'latest': {
            'name': latest.name,
            'modified_at': datetime.fromtimestamp(latest.stat().st_mtime).isoformat(),
        },
    }


@admin_bp.get('/health')
def health():
    try:
        db.session.execute(sa.text('SELECT 1'))

        counts = {
            'users': _safe_count(User),
            'photos': _safe_count(Photo),
            'events': _safe_count(Event),
            'jobs': _safe_count(BackgroundJob),
        }
        visible_photo_count = int(
            db.session.query(sa.func.count(Photo.id))
            .filter(Photo.trashed_at.is_(None))
            .scalar()
            or 0
        )
        ready_photo_count = int(
            db.session.query(sa.func.count(Photo.id))
            .filter(Photo.trashed_at.is_(None), Photo.processing_status == 'ready')
            .scalar()
            or 0
        )

        vector_status = pgvector_runtime_status()
        scene_status = _scene_model_status()
        clip_status = _clip_model_status()
        event_status = _event_model_status()
        backup_status = _backup_status()
        payload = {
            'status': 'ok',
            'timestamp': utcnow().isoformat(),
            'database': {
                'active': True,
                'dialect': db.engine.dialect.name,
                'counts': counts,
                'visible_photo_count': visible_photo_count,
                'ready_photo_count': ready_photo_count,
            },
            'vector': vector_status,
            'models': {
                'scene_classifier': scene_status,
                'clip': clip_status,
                'event_grouping': event_status,
            },
            'backup': backup_status,
        }

        payload['status'] = 'ok' if vector_status.get('pgvector_enabled') else 'degraded'
        payload['summary'] = {
            'database': 'connected',
            'vector': 'ready' if vector_status.get('pgvector_enabled') else 'pending',
            'scene_classifier': 'ready' if scene_status['ready'] else 'missing assets',
            'clip': 'ready' if clip_status['ready'] else 'missing',
            'events': 'ready' if event_status['ready'] else 'missing assets',
            'backup': 'available' if backup_status.get('available') else 'not found',
        }

        return jsonify(payload), 200 if vector_status.get('pgvector_enabled') else 503
    except Exception as error:
        admin_logger.error('health check failed', exc_info=True)
        return (
            jsonify(
                {
                    'status': 'error',
                    'timestamp': utcnow().isoformat(),
                    'error': str(error),
                    'database': {'active': False},
                    'vector': {'pgvector_enabled': False},
                    'models': {},
                    'backup': {'available': False},
                }
            ),
            503,
        )


@admin_bp.post('/backup')
def backup_now():
    try:
        stats = create_backup_package()
        return jsonify({'status': 'ok', 'backup': stats}), 201
    except Exception as error:
        admin_logger.error('backup creation failed', exc_info=True)
        return jsonify({'status': 'error', 'error': str(error)}), 500
