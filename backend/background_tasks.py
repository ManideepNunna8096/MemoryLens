import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import perf_counter

from duplicate_detection import compute_duplicate_signatures
from models import db
from models.event import Event
from models.job import BackgroundJob
from models.photo import Photo
from event_album_service import recompute_event_metadata
from event_organizer import CATEGORY_META, _categorize_scene
from ml_services import get_clip_embedding_fn, get_scene_classifier
from photo_metadata import extract_photo_metadata
from utils.logger import get_logger


SCENE_MODEL_VERSION = 'resnet18-places365'
CLIP_MODEL_VERSION = 'clip-vit-b32'
EVENT_ALGORITHM_VERSION = 'clip-kmeans-v2'

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='memorylens-worker')

job_logger = get_logger('JOB')
step_logger = get_logger('STEP')
result_logger = get_logger('RESULT')
done_logger = get_logger('DONE')
error_logger = get_logger('ERROR')


def _set_job_result(job, payload):
    job.result_payload = json.dumps(payload)


def _normalize_label(value):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower())).strip()


def _category_label(category):
    return CATEGORY_META.get(category, {'label': category})['label']


def _canonicalize_user_albums(user_id):
    events = Event.query.filter_by(user_id=user_id).all()
    grouped = {}

    for event in events:
        label_key = _normalize_label(event.label)
        grouped.setdefault(label_key, []).append(event)

    merged_count = 0
    canonical_events = []

    for label_key, items in grouped.items():
        canonical = sorted(items, key=lambda item: (item.created_at or datetime.min, item.id))[0]
        canonical_events.append(canonical)

        for duplicate in items:
            if duplicate.id == canonical.id:
                continue
            moved_count = (
                db.session.query(Photo)
                .filter(Photo.user_id == user_id, Photo.event_id == duplicate.id)
                .update({Photo.event_id: canonical.id}, synchronize_session=False)
            )
            db.session.delete(duplicate)
            merged_count += 1
            if moved_count:
                db.session.flush()

        recompute_event_metadata(canonical)

    if merged_count:
        db.session.flush()

    return canonical_events, merged_count


def _match_existing_album(events, category):
    target = _normalize_label(_category_label(category))
    for event in sorted(events, key=lambda item: (item.created_at or datetime.min, item.id), reverse=True):
        event_label = _normalize_label(event.label)
        if not event_label:
            continue
        if event_label == target or event_label.startswith(target) or target in event_label:
            return event
    return None


def _ensure_category_album(events, user_id, category, photo_scene):
    matching_event = _match_existing_album(events, category)
    if matching_event:
        return matching_event, False

    event = Event(
        label=_category_label(category),
        dominant_scene=photo_scene or _category_label(category),
        user_id=user_id,
    )
    db.session.add(event)
    db.session.flush()
    events.append(event)
    return event, True


def _run_or_submit(app, worker, *args):
    if app.config.get('TASKS_EAGER'):
        worker(app, *args)
        return None
    return _EXECUTOR.submit(worker, app, *args)


def submit_photo_processing_job(app, job_id, photo_ids):
    return _run_or_submit(app, _process_photo_job, job_id, photo_ids)


def submit_event_organization_job(app, job_id, user_id):
    return _run_or_submit(app, _process_event_job, job_id, user_id)


def _process_photo_job(app, job_id, photo_ids):
    with app.app_context():
        job = db.session.get(BackgroundJob, job_id)
        if not job:
            return

        job.status = 'in_progress'
        db.session.commit()

        classify_scene = get_scene_classifier()
        get_clip_embedding = get_clip_embedding_fn()
        processed = []
        failures = []
        job_logger.info(f'Starting photo processing job_id={job_id} with {len(photo_ids)} photo(s)')

        for index, photo_id in enumerate(photo_ids, start=1):
            photo = db.session.get(Photo, photo_id)
            if not photo:
                continue

            photo_started_at = perf_counter()
            job_logger.info(f'Processing photo_id={photo.id} filename="{photo.original_filename or photo.filename}"')
            try:
                metadata = extract_photo_metadata(photo.filepath(app.config['UPLOAD_FOLDER']))
                if metadata.get('captured_at'):
                    photo.captured_at = metadata.get('captured_at')

                step_logger.info(f'photo_id={photo.id} [STEP 1] Generating CLIP embedding...')
                clip_embedding = get_clip_embedding(photo.filepath(app.config['UPLOAD_FOLDER']))
                photo.set_clip_embedding(clip_embedding)

                step_logger.info(f'photo_id={photo.id} [STEP 2] Running scene classification...')
                photo.scene = classify_scene(photo.filepath(app.config['UPLOAD_FOLDER']))
                result_logger.info(f'photo_id={photo.id} Scene: {photo.scene}')

                step_logger.info(f'photo_id={photo.id} [STEP 3] Checking duplicates...')
                if not photo.sha256_hash or not photo.dhash:
                    photo.sha256_hash, photo.dhash = compute_duplicate_signatures(
                        photo.filepath(app.config['UPLOAD_FOLDER'])
                    )
                result_logger.info(
                    f'photo_id={photo.id} Duplicate signatures ready'
                )

                step_logger.info(f'photo_id={photo.id} [STEP 4] Ready for event clustering...')
                photo.scene_model_version = SCENE_MODEL_VERSION
                photo.clip_model_version = CLIP_MODEL_VERSION
                photo.processing_status = 'ready'
                photo.processing_error = None
                processed.append(photo.to_dict())
                done_logger.info(
                    f'Completed photo_id={photo.id} in {perf_counter() - photo_started_at:.2f}s'
                )
            except Exception as error:
                photo.processing_status = 'failed'
                photo.processing_error = str(error)
                photo.scene = 'Processing Failed'
                failures.append(
                    {
                        'id': photo.id,
                        'filename': photo.original_filename or photo.filename,
                        'error': str(error),
                    }
                )
                error_logger.error(f'Failed processing photo_id={photo.id}: {error}', exc_info=True)

            job.completed_items = index
            db.session.commit()

        if processed and failures:
            job.status = 'completed_with_errors'
        elif processed:
            job.status = 'completed'
        else:
            job.status = 'failed'
            job.error_message = 'All uploaded photos failed to process.'

        _set_job_result(
            job,
            {
                'success_count': len(processed),
                'failure_count': len(failures),
                'photos': processed,
                'errors': failures,
                'scene_model_version': SCENE_MODEL_VERSION,
                'clip_model_version': CLIP_MODEL_VERSION,
            },
        )
        db.session.commit()
        done_logger.info(
            f'Photo processing job_id={job_id} finished: {len(processed)} succeeded, {len(failures)} failed'
        )
        db.session.remove()


def _process_event_job(app, job_id, user_id):
    with app.app_context():
        job = db.session.get(BackgroundJob, job_id)
        if not job:
            return

        job.status = 'in_progress'
        db.session.commit()
        job_started_at = perf_counter()
        job_logger.info(f'Starting event clustering job_id={job_id} for user_id={user_id}')

        photos = (
            Photo.query.filter(
                Photo.user_id == user_id,
                Photo.processing_status == 'ready',
                Photo.trashed_at.is_(None),
                Photo.event_id.is_(None),
            )
            .all()
        )
        photos_with_embeddings = [photo for photo in photos if photo.get_clip_embedding() is not None]
        job.total_items = len(photos_with_embeddings)
        db.session.commit()
        result_logger.info(
            f'user_id={user_id} has {len(photos_with_embeddings)} unorganized ready photo(s) with embeddings for clustering'
        )

        if not photos_with_embeddings:
            job.status = 'completed'
            job.error_message = None
            _set_job_result(
                job,
                {
                    'events_created': 0,
                    'skipped_reason': 'No unorganized ready photos found',
                    'algorithm_version': EVENT_ALGORITHM_VERSION,
                },
            )
            db.session.commit()
            done_logger.info(
                f'Event clustering skipped for user_id={user_id}: no unorganized ready photos were available'
            )
            db.session.remove()
            return

        existing_events, merged_duplicates = _canonicalize_user_albums(user_id)
        matched_event_ids = set()
        matched_count = 0
        created_events = 0

        for photo in photos_with_embeddings:
            category = _categorize_scene(photo.scene)
            matching_event, created = _ensure_category_album(existing_events, user_id, category, photo.scene)
            photo.event_id = matching_event.id
            matched_event_ids.add(matching_event.id)
            if created:
                created_events += 1
            else:
                matched_count += 1

        for event_id in matched_event_ids:
            event = db.session.get(Event, event_id)
            if event:
                recompute_event_metadata(event)

        job.completed_items = len(photos_with_embeddings)
        job.status = 'completed'
        job.error_message = None
        _set_job_result(
            job,
            {
                'events_created': created_events,
                'matched_existing_count': matched_count,
                'merged_duplicate_albums': merged_duplicates,
                'unassigned_count': 0,
                'algorithm_version': EVENT_ALGORITHM_VERSION,
            },
        )
        db.session.commit()
        done_logger.info(
            f'Completed event clustering job_id={job_id} for user_id={user_id} in {perf_counter() - job_started_at:.2f}s with {created_events} new event(s) and {matched_count} matched photo(s)'
        )
        db.session.remove()
        return
