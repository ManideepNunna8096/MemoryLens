import io
import shutil
import sys
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import sqlalchemy as sa
from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import create_app
from models import db
from models.event import Event
from models.photo import Photo


def _auth_headers(token):
    return {'Authorization': f'Bearer {token}'}


def _make_image_file(color='blue'):
    buffer = io.BytesIO()
    Image.new('RGB', (32, 32), color=color).save(buffer, format='JPEG')
    buffer.seek(0)
    return buffer


def _smoke_vector():
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    return vector


class PostgreSQLSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix='memorylens-smoke-'))
        self.upload_dir = self.tmpdir / 'uploads'
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.schema = f"smoke_{uuid.uuid4().hex[:10]}"

        self.app = create_app(
            {
                'TESTING': True,
                'SECRET_KEY': 'test-secret-key-32-chars-minimum-okay!!',
                'JWT_SECRET_KEY': 'test-jwt-secret-key-32-chars-okay!!',
                'UPLOAD_FOLDER': str(self.upload_dir),
                'TASKS_EAGER': True,
                'AUTH_RATE_LIMIT': '1000 per minute',
                'DISPLAY_TIMEZONE': 'Asia/Calcutta',
                'SQLALCHEMY_ENGINE_OPTIONS': {
                    'pool_pre_ping': True,
                    'connect_args': {'options': f'-csearch_path={self.schema},public'},
                },
            }
        )
        self.app_context = self.app.app_context()
        self.app_context.push()

        db.session.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"'))
        db.session.commit()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.session.execute(sa.text(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE'))
        db.session.commit()
        self.app_context.pop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _register_user(self, email, password='StrongPass123'):
        response = self.client.post(
            '/auth/register',
            json={
                'name': 'Smoke Test User',
                'email': email,
                'password': password,
            },
        )
        self.assertIn(response.status_code, {201, 409})
        if response.status_code == 409:
            response = self.client.post('/auth/login', json={'email': email, 'password': password})
            self.assertEqual(response.status_code, 200)
            return response.get_json()
        return response.get_json()

    def _create_ready_photo(self, user_id, filename, scene, captured_at=None):
        file_path = self.upload_dir / filename
        Image.new('RGB', (32, 32), color='green').save(file_path, format='JPEG')

        photo = Photo(
            filename=filename,
            original_filename=filename,
            scene=scene,
            processing_status='ready',
            user_id=user_id,
            captured_at=captured_at,
            uploaded_at=captured_at or datetime(2026, 4, 20, 10, 0),
        )
        photo.set_clip_embedding(_smoke_vector())
        db.session.add(photo)
        db.session.commit()
        return photo

    def test_auth_smoke(self):
        auth = self._register_user('smoke-auth@example.com')
        self.assertIn('access_token', auth)
        self.assertIn('refresh_token', auth)

        refresh = self.client.post('/auth/refresh', headers=_auth_headers(auth['refresh_token']))
        self.assertEqual(refresh.status_code, 200)
        self.assertIn('access_token', refresh.get_json())

    def test_admin_health_smoke(self):
        response = self.client.get('/admin/health')
        self.assertIn(response.status_code, {200, 503})
        payload = response.get_json()
        self.assertIn('status', payload)
        self.assertIn('database', payload)
        self.assertIn('vector', payload)
        self.assertIn('models', payload)

    def test_upload_and_gallery_smoke(self):
        auth = self._register_user('smoke-upload@example.com')
        headers = _auth_headers(auth['access_token'])

        with patch('background_tasks.get_scene_classifier', return_value=lambda path: 'Temple'), patch(
            'background_tasks.get_clip_embedding_fn',
            return_value=lambda path: _smoke_vector(),
        ):
            response = self.client.post(
                '/photos/upload',
                headers=headers,
                content_type='multipart/form-data',
                data={'files': [(_make_image_file('red'), 'smoke-upload.jpg')]},
            )

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertEqual(payload['job']['status'], 'completed')
        self.assertEqual(payload['job']['result']['success_count'], 1)

        gallery = self.client.get('/photos/all', headers=headers)
        self.assertEqual(gallery.status_code, 200)
        photos = gallery.get_json()
        self.assertGreaterEqual(len(photos), 1)
        self.assertTrue(any(photo['scene'] == 'Temple' for photo in photos))
        self.assertTrue(any(photo['processing_status'] == 'ready' for photo in photos))

    def test_timeline_smoke(self):
        auth = self._register_user('smoke-timeline@example.com')
        headers = _auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        self._create_ready_photo(user_id, 'timeline-a.jpg', 'Beach', datetime(2026, 4, 20, 9, 0))
        self._create_ready_photo(user_id, 'timeline-b.jpg', 'Beach', datetime(2026, 4, 21, 9, 0))
        self._create_ready_photo(user_id, 'timeline-c.jpg', 'Temple', datetime(2025, 12, 31, 23, 30))

        year_response = self.client.get('/timeline?group=year', headers=headers)
        self.assertEqual(year_response.status_code, 200)
        year_payload = year_response.get_json()
        self.assertEqual(year_payload['group'], 'year')
        self.assertTrue(any(period['label'] == '2026' and period['count'] >= 2 for period in year_payload['periods']))

        month_response = self.client.get('/timeline?group=month', headers=headers)
        self.assertEqual(month_response.status_code, 200)
        month_payload = month_response.get_json()
        self.assertTrue(any(period['label'] == 'April 2026' and period['count'] >= 2 for period in month_payload['periods']))

        day_response = self.client.get('/timeline?group=day', headers=headers)
        self.assertEqual(day_response.status_code, 200)
        day_payload = day_response.get_json()
        self.assertTrue(any(period['count'] >= 1 for period in day_payload['periods']))

    def test_events_smoke(self):
        auth = self._register_user(f"smoke-events-{uuid.uuid4().hex[:8]}@example.com")
        headers = _auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        self._create_ready_photo(user_id, 'event-a.jpg', 'Beach', datetime(2026, 4, 20, 9, 0))
        self._create_ready_photo(user_id, 'event-b.jpg', 'Beach', datetime(2026, 4, 20, 10, 0))
        self._create_ready_photo(user_id, 'event-c.jpg', 'Temple', datetime(2026, 4, 20, 11, 0))

        organize = self.client.post('/events/organize', headers=headers)

        self.assertEqual(organize.status_code, 202)
        job = organize.get_json()['job']
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['result']['events_created'], 2)
        self.assertEqual(job['result']['matched_existing_count'], 1)

        events = self.client.get('/events/all', headers=headers)
        self.assertEqual(events.status_code, 200)
        event_list = events.get_json()
        self.assertTrue(any(event['label'] == 'Vacation & Outdoors' for event in event_list))
        self.assertTrue(any(event['label'] == 'Sacred & Heritage' for event in event_list))

        smoke_album = next(event for event in event_list if event['label'] == 'Vacation & Outdoors')
        event_photos = self.client.get(f"/events/{smoke_album['id']}/photos", headers=headers)
        self.assertEqual(event_photos.status_code, 200)
        photo_payloads = event_photos.get_json()
        filenames = {photo['original_filename'] for photo in photo_payloads}
        self.assertIn('event-a.jpg', filenames)
        self.assertIn('event-b.jpg', filenames)
        self.assertEqual(len(photo_payloads), 2)

    def test_event_organization_preserves_existing_events(self):
        auth = self._register_user(f"smoke-events-preserve-{uuid.uuid4().hex[:8]}@example.com")
        headers = _auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        existing_a = self._create_ready_photo(user_id, 'existing-a.jpg', 'Beach', datetime(2026, 4, 20, 9, 0))
        existing_b = self._create_ready_photo(user_id, 'existing-b.jpg', 'Beach', datetime(2026, 4, 20, 10, 0))
        new_a = self._create_ready_photo(user_id, 'new-a.jpg', 'Temple', datetime(2026, 4, 20, 11, 0))
        new_b = self._create_ready_photo(user_id, 'new-b.jpg', 'Temple', datetime(2026, 4, 20, 12, 0))
        new_c = self._create_ready_photo(user_id, 'new-c.jpg', 'Temple', datetime(2026, 4, 20, 13, 0))

        with db.session.begin():
            existing_event = Event(label='Original Album', dominant_scene='Beach', user_id=user_id)
            db.session.add(existing_event)
            db.session.flush()
            for photo_id in (existing_a.id, existing_b.id):
                photo = db.session.get(Photo, photo_id)
                photo.event_id = existing_event.id

        db.session.commit()
        original_event_id = existing_event.id

        organize = self.client.post('/events/organize', headers=headers)

        self.assertEqual(organize.status_code, 202)
        job = organize.get_json()['job']
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['result']['events_created'], 1)
        self.assertEqual(job['result']['matched_existing_count'], 2)

        events_response = self.client.get('/events/all', headers=headers)
        self.assertEqual(events_response.status_code, 200)
        events = events_response.get_json()
        self.assertTrue(any(event['label'] == 'Original Album' for event in events))
        self.assertTrue(any(event['label'] == 'Sacred & Heritage' for event in events))

        original_event_response = self.client.get(f'/events/{original_event_id}/photos', headers=headers)
        self.assertEqual(original_event_response.status_code, 200)
        original_files = {photo['original_filename'] for photo in original_event_response.get_json()}
        self.assertEqual(original_files, {'existing-a.jpg', 'existing-b.jpg'})

        new_event = next(event for event in events if event['label'] == 'Sacred & Heritage')
        new_event_response = self.client.get(f"/events/{new_event['id']}/photos", headers=headers)
        self.assertEqual(new_event_response.status_code, 200)
        new_files = {photo['original_filename'] for photo in new_event_response.get_json()}
        self.assertEqual(new_files, {'new-a.jpg', 'new-b.jpg', 'new-c.jpg'})

    def test_event_organization_matches_existing_album_by_scene_category(self):
        auth = self._register_user(f"smoke-events-match-{uuid.uuid4().hex[:8]}@example.com")
        headers = _auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        existing_photo = self._create_ready_photo(user_id, 'vacation-1.jpg', 'Beach', datetime(2026, 4, 20, 9, 0))
        new_photo = self._create_ready_photo(user_id, 'vacation-2.jpg', 'Beach', datetime(2026, 4, 20, 10, 0))

        vacation_event = Event(label='Vacation & Outdoors', dominant_scene='Beach', user_id=user_id)
        db.session.add(vacation_event)
        db.session.flush()
        existing_photo_db = db.session.get(Photo, existing_photo.id)
        existing_photo_db.event_id = vacation_event.id
        db.session.commit()
        vacation_event_id = vacation_event.id

        organize = self.client.post('/events/organize', headers=headers)
        self.assertEqual(organize.status_code, 202)
        job = organize.get_json()['job']
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['result']['events_created'], 0)
        self.assertEqual(job['result']['matched_existing_count'], 1)
        self.assertEqual(job['result']['merged_duplicate_albums'], 0)

        vacation_event_response = self.client.get(f'/events/{vacation_event_id}/photos', headers=headers)
        self.assertEqual(vacation_event_response.status_code, 200)
        vacation_files = {photo['original_filename'] for photo in vacation_event_response.get_json()}
        self.assertEqual(vacation_files, {'vacation-1.jpg', 'vacation-2.jpg'})

        refreshed_new_photo = db.session.get(Photo, new_photo.id)
        self.assertIsNotNone(refreshed_new_photo)
        self.assertEqual(refreshed_new_photo.event_id, vacation_event_id)

    def test_event_organization_merges_duplicate_existing_albums(self):
        auth = self._register_user(f"smoke-events-merge-{uuid.uuid4().hex[:8]}@example.com")
        headers = _auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        base_one = self._create_ready_photo(user_id, 'vacation-base-1.jpg', 'Beach', datetime(2026, 4, 20, 9, 0))
        base_two = self._create_ready_photo(user_id, 'vacation-base-2.jpg', 'Beach', datetime(2026, 4, 20, 10, 0))
        new_photo = self._create_ready_photo(user_id, 'vacation-new.jpg', 'Beach', datetime(2026, 4, 20, 11, 0))

        first_event = Event(label='Vacation & Outdoors', dominant_scene='Beach', user_id=user_id)
        second_event = Event(label='Vacation & Outdoors', dominant_scene='Beach', user_id=user_id)
        db.session.add_all([first_event, second_event])
        db.session.flush()
        db.session.get(Photo, base_one.id).event_id = first_event.id
        db.session.get(Photo, base_two.id).event_id = second_event.id
        db.session.commit()

        organize = self.client.post('/events/organize', headers=headers)
        self.assertEqual(organize.status_code, 202)
        job = organize.get_json()['job']
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['result']['events_created'], 0)
        self.assertEqual(job['result']['matched_existing_count'], 1)
        self.assertEqual(job['result']['merged_duplicate_albums'], 1)

        events_response = self.client.get('/events/all', headers=headers)
        self.assertEqual(events_response.status_code, 200)
        events = events_response.get_json()
        vacation_events = [event for event in events if event['label'] == 'Vacation & Outdoors']
        self.assertEqual(len(vacation_events), 1)

        vacation_event_id = vacation_events[0]['id']
        vacation_event_response = self.client.get(f'/events/{vacation_event_id}/photos', headers=headers)
        self.assertEqual(vacation_event_response.status_code, 200)
        vacation_files = {photo['original_filename'] for photo in vacation_event_response.get_json()}
        self.assertEqual(vacation_files, {'vacation-base-1.jpg', 'vacation-base-2.jpg', 'vacation-new.jpg'})

        refreshed_new_photo = db.session.get(Photo, new_photo.id)
        self.assertIsNotNone(refreshed_new_photo)
        self.assertEqual(refreshed_new_photo.event_id, vacation_event_id)

if __name__ == '__main__':
    unittest.main()
