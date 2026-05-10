import io
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from test_db_utils import TEST_DATABASE_URL, ensure_test_database, ensure_vector_extension
from app import create_app
from models import db
from models.event import Event
from models.photo import Photo
import routes.search_routes as search_routes


class MemoryLensAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_test_database(TEST_DATABASE_URL)
        ensure_vector_extension(TEST_DATABASE_URL)

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix='memorylens-tests-'))
        self.upload_dir = self.tmpdir / 'uploads'
        self.upload_dir.mkdir(parents=True, exist_ok=True)

        self.app = create_app(
            {
                'TESTING': True,
                'SECRET_KEY': 'test-secret-key-32-chars-minimum-okay!!',
                'JWT_SECRET_KEY': 'test-jwt-secret-key-32-chars-okay!!',
                'SQLALCHEMY_DATABASE_URI': TEST_DATABASE_URL,
                'UPLOAD_FOLDER': str(self.upload_dir),
                'TASKS_EAGER': True,
                'AUTH_RATE_LIMIT': '1000 per minute',
                'DISPLAY_TIMEZONE': 'Asia/Calcutta',
            }
        )
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def register_user(self, email='test@example.com', password='Strong123'):
        response = self.client.post(
            '/auth/register',
            json={
                'name': 'Test User',
                'email': email,
                'password': password,
            },
        )
        self.assertIn(response.status_code, {201, 409})
        if response.status_code == 409:
            login = self.client.post('/auth/login', json={'email': email, 'password': password})
            return login.get_json()
        return response.get_json()

    def auth_headers(self, token):
        return {'Authorization': f'Bearer {token}'}

    def make_image_file(self, color):
        buffer = io.BytesIO()
        Image.new('RGB', (16, 16), color=color).save(buffer, format='JPEG')
        buffer.seek(0)
        return buffer

    def create_ready_photo(self, user_id, filename, scene, vector):
        image_path = self.upload_dir / filename
        Image.new('RGB', (12, 12), color='green').save(image_path, format='JPEG')

        photo = Photo(
            filename=filename,
            original_filename=filename,
            scene=scene,
            processing_status='ready',
            user_id=user_id,
        )
        photo.set_clip_embedding(np.asarray(vector, dtype=np.float32))
        db.session.add(photo)
        db.session.commit()
        return photo

    def create_failed_photo(self, user_id, filename):
        image_path = self.upload_dir / filename
        Image.new('RGB', (12, 12), color='red').save(image_path, format='JPEG')

        photo = Photo(
            filename=filename,
            original_filename=filename,
            scene='Processing Failed',
            processing_status='failed',
            processing_error='Model crashed',
            user_id=user_id,
        )
        db.session.add(photo)
        db.session.commit()
        return photo

    def create_ready_photo_from_image(self, user_id, filename, scene, image, quality=92, exif=None):
        image_path = self.upload_dir / filename
        save_kwargs = {'format': 'JPEG', 'quality': quality}
        if exif is not None:
            save_kwargs['exif'] = exif
        image.save(image_path, **save_kwargs)

        photo = Photo(
            filename=filename,
            original_filename=filename,
            scene=scene,
            processing_status='ready',
            user_id=user_id,
        )
        db.session.add(photo)
        db.session.commit()
        return photo

    def make_patterned_image(self, variant='base'):
        image = Image.new('RGB', (96, 96), color=(242, 236, 224))
        draw = ImageDraw.Draw(image)

        if variant == 'other':
            draw.rectangle((10, 12, 84, 30), fill=(68, 114, 196))
            draw.ellipse((18, 38, 48, 68), fill=(220, 90, 70))
            draw.rectangle((56, 42, 86, 78), fill=(52, 168, 83))
            draw.line((12, 84, 86, 84), fill=(32, 32, 32), width=6)
            return image

        draw.rectangle((8, 10, 54, 70), fill=(63, 81, 181))
        draw.rectangle((60, 18, 88, 42), fill=(244, 81, 30))
        draw.ellipse((22, 22, 44, 44), fill=(255, 235, 59))
        draw.line((12, 82, 86, 78), fill=(40, 40, 40), width=5)
        draw.line((70, 6, 90, 30), fill=(0, 150, 136), width=6)
        return image

    def test_auth_register_login_refresh(self):
        register = self.register_user()
        self.assertIn('access_token', register)
        self.assertIn('refresh_token', register)

        refresh = self.client.post(
            '/auth/refresh',
            headers=self.auth_headers(register['refresh_token']),
        )
        self.assertEqual(refresh.status_code, 200)
        self.assertIn('access_token', refresh.get_json())

    def test_upload_job_and_private_photo_access(self):
        auth = self.register_user(email='photos@example.com')

        with patch('background_tasks.get_scene_classifier', return_value=lambda path: 'Beach'), patch(
            'background_tasks.get_clip_embedding_fn',
            return_value=lambda path: np.array([1.0, 0.0, 0.0], dtype=np.float32),
        ):
            response = self.client.post(
                '/photos/upload',
                headers=self.auth_headers(auth['access_token']),
                content_type='multipart/form-data',
                data={
                    'files': [
                        (self.make_image_file('red'), 'one.jpg'),
                        (self.make_image_file('blue'), 'two.jpg'),
                    ]
                },
            )

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertEqual(payload['job']['status'], 'completed')
        self.assertEqual(payload['job']['result']['success_count'], 2)

        photos = self.client.get('/photos/all', headers=self.auth_headers(auth['access_token'])).get_json()
        self.assertEqual(len(photos), 2)
        self.assertTrue(all(photo['processing_status'] == 'ready' for photo in photos))

        unauthorized = self.client.get(f"/photos/{photos[0]['id']}/file")
        self.assertEqual(unauthorized.status_code, 401)

        authorized = self.client.get(
            f"/photos/{photos[0]['id']}/file",
            headers=self.auth_headers(auth['access_token']),
        )
        self.assertEqual(authorized.status_code, 200)
        authorized.close()

    def test_search_returns_matching_ready_photo(self):
        auth = self.register_user(email='search@example.com')
        self.create_ready_photo(auth['user']['id'], 'search.jpg', 'Beach', [1.0, 0.0, 0.0])

        with patch.object(search_routes, 'get_text_embedding_fn', return_value=lambda text: np.array([1.0, 0.0, 0.0], dtype=np.float32)):
            response = self.client.get('/search?q=beach', headers=self.auth_headers(auth['access_token']))

        self.assertEqual(response.status_code, 200)
        results = response.get_json()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['scene'], 'Beach')

    def test_event_organization_job_creates_events(self):
        auth = self.register_user(email='events@example.com')
        user_id = auth['user']['id']

        self.create_ready_photo(user_id, 'a.jpg', 'Beach', [1.0, 0.0, 0.0])
        self.create_ready_photo(user_id, 'b.jpg', 'Beach', [0.95, 0.05, 0.0])
        self.create_ready_photo(user_id, 'c.jpg', 'Beach', [0.9, 0.1, 0.0])

        response = self.client.post('/events/organize', headers=self.auth_headers(auth['access_token']))
        self.assertEqual(response.status_code, 202)
        job = response.get_json()['job']
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['result']['events_created'], 1)
        self.assertEqual(job['result']['matched_existing_count'], 0)

        events_response = self.client.get('/events/all', headers=self.auth_headers(auth['access_token']))
        self.assertEqual(events_response.status_code, 200)
        events = events_response.get_json()
        self.assertTrue(any(event['label'] == 'Vacation & Outdoors' for event in events))

        album = next(event for event in events if event['label'] == 'Vacation & Outdoors')
        photos_response = self.client.get(
            f"/events/{album['id']}/photos",
            headers=self.auth_headers(auth['access_token']),
        )
        self.assertEqual(photos_response.status_code, 200)
        self.assertEqual(len(photos_response.get_json()), 3)

    def test_event_rename_merge_and_split(self):
        auth = self.register_user(email='events-flow@example.com')
        user_id = auth['user']['id']

        p1 = self.create_ready_photo(user_id, 'flow_a_1.jpg', 'Beach', [1.0, 0.0, 0.0])
        p2 = self.create_ready_photo(user_id, 'flow_a_2.jpg', 'Beach', [0.9, 0.1, 0.0])
        p3 = self.create_ready_photo(user_id, 'flow_b_1.jpg', 'City', [0.0, 1.0, 0.0])
        p4 = self.create_ready_photo(user_id, 'flow_b_2.jpg', 'City', [0.1, 0.9, 0.0])

        event_one = Event(label='Trip One', dominant_scene='Beach', user_id=user_id)
        event_two = Event(label='Trip Two', dominant_scene='City', user_id=user_id)
        db.session.add_all([event_one, event_two])
        db.session.flush()

        p1.event_id = event_one.id
        p2.event_id = event_one.id
        p3.event_id = event_two.id
        p4.event_id = event_two.id
        db.session.commit()

        rename_response = self.client.patch(
            f'/events/{event_one.id}',
            headers=self.auth_headers(auth['access_token']),
            json={'label': 'Trip One Renamed'},
        )
        self.assertEqual(rename_response.status_code, 200)
        self.assertEqual(rename_response.get_json()['label'], 'Trip One Renamed')

        merge_response = self.client.post(
            '/events/merge',
            headers=self.auth_headers(auth['access_token']),
            json={'event_ids': [event_one.id, event_two.id], 'label': 'Merged Trip'},
        )
        self.assertEqual(merge_response.status_code, 200)
        merged_event = merge_response.get_json()
        self.assertEqual(merged_event['photo_count'], 4)

        photos_response = self.client.get(
            f"/events/{merged_event['id']}/photos",
            headers=self.auth_headers(auth['access_token']),
        )
        self.assertEqual(photos_response.status_code, 200)
        merged_photos = photos_response.get_json()
        self.assertEqual(len(merged_photos), 4)

        split_response = self.client.post(
            f"/events/{merged_event['id']}/split",
            headers=self.auth_headers(auth['access_token']),
            json={'photo_ids': [merged_photos[0]['id'], merged_photos[1]['id']], 'new_label': 'Split Trip'},
        )
        self.assertEqual(split_response.status_code, 200)
        split_payload = split_response.get_json()
        self.assertEqual(split_payload['new_event']['photo_count'], 2)
        self.assertEqual(split_payload['source_event']['photo_count'], 2)

    def test_photo_bulk_retry_export_and_share(self):
        auth = self.register_user(email='bulk@example.com')
        user_id = auth['user']['id']
        headers = self.auth_headers(auth['access_token'])

        ready_photo = self.create_ready_photo(user_id, 'bulk-ready.jpg', 'Beach', [1.0, 0.0, 0.0])
        failed_photo = self.create_failed_photo(user_id, 'bulk-failed.jpg')

        event = Event(label='Bulk Album', dominant_scene='Beach', user_id=user_id)
        db.session.add(event)
        db.session.commit()

        favorite_response = self.client.post(
            '/photos/bulk',
            headers=headers,
            json={'action': 'favorite', 'photo_ids': [ready_photo.id]},
        )
        self.assertEqual(favorite_response.status_code, 200)

        favorites_response = self.client.get('/photos/all?collection=favorites', headers=headers)
        self.assertEqual([photo['id'] for photo in favorites_response.get_json()], [ready_photo.id])

        move_response = self.client.post(
            '/photos/bulk',
            headers=headers,
            json={'action': 'move_to_event', 'photo_ids': [ready_photo.id], 'event_id': event.id},
        )
        self.assertEqual(move_response.status_code, 200)

        trash_response = self.client.post(
            '/photos/bulk',
            headers=headers,
            json={'action': 'trash', 'photo_ids': [ready_photo.id]},
        )
        self.assertEqual(trash_response.status_code, 200)

        trash_listing = self.client.get('/photos/all?collection=trash', headers=headers)
        self.assertEqual([photo['id'] for photo in trash_listing.get_json()], [ready_photo.id])

        restore_response = self.client.post(
            '/photos/bulk',
            headers=headers,
            json={'action': 'restore', 'photo_ids': [ready_photo.id]},
        )
        self.assertEqual(restore_response.status_code, 200)

        with patch('background_tasks.get_scene_classifier', return_value=lambda path: 'Temple'), patch(
            'background_tasks.get_clip_embedding_fn',
            return_value=lambda path: np.array([0.4, 0.6, 0.0], dtype=np.float32),
        ):
            retry_response = self.client.post(
                '/photos/retry',
                headers=headers,
                json={'photo_ids': [failed_photo.id]},
            )
        self.assertEqual(retry_response.status_code, 202)

        all_photos_response = self.client.get('/photos/all?collection=all', headers=headers)
        all_photos = {photo['id']: photo for photo in all_photos_response.get_json()}
        self.assertEqual(all_photos[failed_photo.id]['processing_status'], 'ready')
        self.assertEqual(all_photos[ready_photo.id]['event_id'], event.id)

        export_response = self.client.post(
            '/photos/export',
            headers=headers,
            json={'photo_ids': [ready_photo.id, failed_photo.id], 'label': 'Bulk Export'},
        )
        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response.mimetype, 'application/zip')

        share_response = self.client.post(
            '/photos/share',
            headers=headers,
            json={'photo_ids': [ready_photo.id]},
        )
        self.assertEqual(share_response.status_code, 200)
        share_payload = share_response.get_json()
        shared_data = self.client.get(share_payload['api_path'])
        self.assertEqual(shared_data.status_code, 200)
        self.assertEqual(len(shared_data.get_json()['photos']), 1)

    def test_photo_rename(self):
        auth = self.register_user(email='rename@example.com')
        headers = self.auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        photo = self.create_ready_photo(user_id, 'abcdef1234567890abcdef1234567890.jpg', 'Beach', [1.0, 0.0, 0.0])
        rename_response = self.client.post(
            f'/photos/{photo.id}/rename',
            headers=headers,
            json={'name': 'Campus Concert'},
        )
        self.assertEqual(rename_response.status_code, 200)
        payload = rename_response.get_json()
        self.assertEqual(payload['display_name'], 'Campus Concert')
        self.assertEqual(payload['original_filename'], 'abcdef1234567890abcdef1234567890.jpg')

    def test_photo_custom_folder_updates_gallery_folders(self):
        auth = self.register_user(email='folders@example.com')
        headers = self.auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        photo = self.create_ready_photo(user_id, 'folder-test.jpg', 'Auditorium', [1.0, 0.0, 0.0])

        set_folder_response = self.client.post(
            '/photos/bulk',
            headers=headers,
            json={'action': 'set_folder', 'photo_ids': [photo.id], 'folder_name': 'College Fest 2026'},
        )
        self.assertEqual(set_folder_response.status_code, 200)

        all_photos_response = self.client.get('/photos/all', headers=headers)
        self.assertEqual(all_photos_response.status_code, 200)
        stored_photo = all_photos_response.get_json()[0]
        self.assertEqual(stored_photo['custom_folder'], 'College Fest 2026')
        self.assertEqual(stored_photo['folder_label'], 'College Fest 2026')

        filtered_response = self.client.get('/photos/all?scene=College%20Fest%202026', headers=headers)
        self.assertEqual(filtered_response.status_code, 200)
        self.assertEqual(len(filtered_response.get_json()), 1)

        folders_response = self.client.get('/photos/scenes', headers=headers)
        self.assertEqual(folders_response.status_code, 200)
        self.assertEqual(folders_response.get_json()[0]['scene'], 'College Fest 2026')

        clear_folder_response = self.client.post(
            '/photos/bulk',
            headers=headers,
            json={'action': 'set_folder', 'photo_ids': [photo.id], 'folder_name': ''},
        )
        self.assertEqual(clear_folder_response.status_code, 200)

        reset_photo = self.client.get('/photos/all', headers=headers).get_json()[0]
        self.assertIsNone(reset_photo['custom_folder'])
        self.assertEqual(reset_photo['folder_label'], 'Auditorium')

    def test_folder_management_endpoints(self):
        auth = self.register_user(email='folder-routes@example.com')
        headers = self.auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        p1 = self.create_ready_photo(user_id, 'folder-route-1.jpg', 'Auditorium', [1.0, 0.0, 0.0])
        p2 = self.create_ready_photo(user_id, 'folder-route-2.jpg', 'Auditorium', [0.9, 0.1, 0.0])
        p3 = self.create_ready_photo(user_id, 'folder-route-3.jpg', 'Kitchen', [0.0, 1.0, 0.0])
        p4 = self.create_ready_photo(user_id, 'folder-route-4.jpg', 'Stage Indoor', [0.2, 0.8, 0.0])

        folders_response = self.client.get('/folders/all', headers=headers)
        self.assertEqual(folders_response.status_code, 200)
        folder_names = {item['name'] for item in folders_response.get_json()}
        self.assertEqual(folder_names, {'Auditorium', 'Kitchen', 'Stage Indoor'})

        rename_response = self.client.post(
            '/folders/rename',
            headers=headers,
            json={'source_folder': 'Auditorium', 'target_folder': 'College Fest'},
        )
        self.assertEqual(rename_response.status_code, 200)
        self.assertEqual(rename_response.get_json()['renamed_count'], 2)

        move_response = self.client.post(
            '/folders/move-photos',
            headers=headers,
            json={'photo_ids': [p3.id], 'target_folder': 'College Fest'},
        )
        self.assertEqual(move_response.status_code, 200)
        self.assertEqual(move_response.get_json()['moved_count'], 1)

        merge_response = self.client.post(
            '/folders/merge',
            headers=headers,
            json={'source_folders': ['Stage Indoor'], 'target_folder': 'College Fest'},
        )
        self.assertEqual(merge_response.status_code, 200)
        self.assertEqual(merge_response.get_json()['merged_count'], 1)

        merged_folders = self.client.get('/folders/all', headers=headers).get_json()
        self.assertEqual(len(merged_folders), 1)
        self.assertEqual(merged_folders[0]['name'], 'College Fest')
        self.assertEqual(merged_folders[0]['count'], 4)
        self.assertEqual(merged_folders[0]['kind'], 'custom')

        delete_response = self.client.post(
            '/folders/delete',
            headers=headers,
            json={'folder_name': 'College Fest'},
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.get_json()['deleted_count'], 4)

        reset_folders = self.client.get('/folders/all', headers=headers).get_json()
        reset_names = {item['name'] for item in reset_folders}
        self.assertEqual(reset_names, {'Auditorium', 'Kitchen', 'Stage Indoor'})

    def test_active_library_folder_and_timeline_include_archived_photos(self):
        auth = self.register_user(email='archive-alignment@example.com')
        headers = self.auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        photo = self.create_ready_photo(user_id, 'archived-visible.jpg', 'Auditorium', [1.0, 0.0, 0.0])

        archive_response = self.client.post(
            '/photos/bulk',
            headers=headers,
            json={'action': 'archive', 'photo_ids': [photo.id]},
        )
        self.assertEqual(archive_response.status_code, 200)

        active_listing = self.client.get('/photos/all', headers=headers)
        self.assertEqual(active_listing.status_code, 200)
        self.assertEqual([item['id'] for item in active_listing.get_json()], [photo.id])

        folder_listing = self.client.get('/folders/all', headers=headers)
        self.assertEqual(folder_listing.status_code, 200)
        self.assertEqual(folder_listing.get_json()[0]['name'], 'Auditorium')
        self.assertEqual(folder_listing.get_json()[0]['count'], 1)

        timeline_listing = self.client.get('/timeline?group=day', headers=headers)
        self.assertEqual(timeline_listing.status_code, 200)
        self.assertEqual(timeline_listing.get_json()['periods'][0]['count'], 1)

    def test_timeline_groups_photos_by_period_and_fallback_date(self):
        auth = self.register_user(email='timeline@example.com')
        headers = self.auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        april_event = Event(label='April Highlights', dominant_scene='Beach', user_id=user_id)
        db.session.add(april_event)
        db.session.flush()

        photo_one = self.create_ready_photo(user_id, 'timeline-1.jpg', 'Beach', [1.0, 0.0, 0.0])
        photo_two = self.create_ready_photo(user_id, 'timeline-2.jpg', 'Beach', [0.9, 0.1, 0.0])
        photo_three = self.create_ready_photo(user_id, 'timeline-3.jpg', 'Temple', [0.0, 1.0, 0.0])

        photo_one.captured_at = datetime(2026, 4, 20, 21, 30)
        photo_one.uploaded_at = datetime(2026, 4, 20, 22, 0)
        photo_one.event_id = april_event.id

        photo_two.captured_at = None
        photo_two.uploaded_at = datetime(2026, 4, 20, 9, 15)

        photo_three.captured_at = datetime(2026, 3, 31, 18, 45)
        photo_three.uploaded_at = datetime(2026, 3, 31, 19, 0)
        db.session.commit()

        day_response = self.client.get('/timeline?group=day', headers=headers)
        self.assertEqual(day_response.status_code, 200)
        day_payload = day_response.get_json()
        self.assertEqual(day_payload['group'], 'day')
        self.assertEqual(day_payload['periods'][0]['label'], '20 Apr 2026')
        self.assertEqual(day_payload['periods'][0]['count'], 2)
        self.assertEqual(day_payload['periods'][0]['photos'][0]['event_label'], 'April Highlights')

        month_response = self.client.get('/timeline?group=month', headers=headers)
        self.assertEqual(month_response.status_code, 200)
        month_payload = month_response.get_json()
        self.assertEqual(month_payload['periods'][0]['label'], 'April 2026')
        self.assertEqual(month_payload['periods'][0]['count'], 2)
        self.assertEqual(month_payload['periods'][1]['label'], 'March 2026')
        self.assertEqual(month_payload['periods'][1]['count'], 1)

        year_response = self.client.get('/timeline?group=year', headers=headers)
        self.assertEqual(year_response.status_code, 200)
        year_payload = year_response.get_json()
        self.assertEqual(year_payload['group'], 'year')
        self.assertEqual(year_payload['periods'][0]['label'], '2026')
        self.assertEqual(year_payload['periods'][0]['count'], 3)

        filtered_month_response = self.client.get(
            f"/timeline?group=month&start={year_payload['periods'][0]['start']}&end={year_payload['periods'][0]['end']}",
            headers=headers,
        )
        self.assertEqual(filtered_month_response.status_code, 200)
        self.assertEqual(filtered_month_response.get_json()['periods'][0]['label'], 'April 2026')

        invalid_response = self.client.get('/timeline?group=week', headers=headers)
        self.assertEqual(invalid_response.status_code, 400)

    def test_timeline_uses_display_timezone_for_uploaded_at_fallback(self):
        auth = self.register_user(email='timeline-timezone@example.com')
        headers = self.auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        photo = self.create_ready_photo(user_id, 'timeline-tz.jpg', 'Office', [1.0, 0.0, 0.0])
        photo.captured_at = None
        photo.uploaded_at = datetime(2026, 4, 20, 18, 45)  # 21 Apr 2026 00:15 in Asia/Calcutta
        db.session.commit()

        timeline_response = self.client.get('/timeline?group=day', headers=headers)
        self.assertEqual(timeline_response.status_code, 200)
        self.assertEqual(timeline_response.get_json()['periods'][0]['label'], '21 Apr 2026')

        listing_response = self.client.get('/photos/all', headers=headers)
        self.assertEqual(listing_response.status_code, 200)
        self.assertTrue(listing_response.get_json()[0]['uploaded_at'].endswith('+00:00'))

    def test_settings_require_postgresql_database_url(self):
        import config.settings as settings_module

        def fake_getenv(name, default=None):
            if name == 'DATABASE_URL':
                return None
            return default

        with patch.object(settings_module.os, 'getenv', side_effect=fake_getenv):
            self.assertIsNone(settings_module._database_uri())

    def test_settings_use_postgresql_when_database_url_is_present(self):
        import config.settings as settings_module

        def fake_getenv(name, default=None):
            if name == 'DATABASE_URL':
                return 'postgres://memorylens:memorylens@127.0.0.1:5432/memorylens'
            return default

        with patch.object(settings_module.os, 'getenv', side_effect=fake_getenv):
            uri = settings_module._database_uri()
            self.assertEqual(uri, 'postgresql://memorylens:memorylens@127.0.0.1:5432/memorylens')
            self.assertEqual(settings_module.Config.DATABASE_LABEL, 'PostgreSQL')

    def test_vectors_status_reports_postgresql(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['vectors', 'status'])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('"database_dialect": "postgresql"', result.output)

    def test_duplicates_scan_trash_and_keep_flow(self):
        auth = self.register_user(email='duplicates@example.com')
        headers = self.auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        seed = self.create_ready_photo(user_id, 'dup-seed.jpg', 'Office', [1.0, 0.0, 0.0])
        seed_path = self.upload_dir / seed.filename

        copy_one_name = 'dup-copy-one.jpg'
        copy_two_name = 'dup-copy-two.jpg'
        shutil.copyfile(seed_path, self.upload_dir / copy_one_name)
        shutil.copyfile(seed_path, self.upload_dir / copy_two_name)

        copy_one = Photo(
            filename=copy_one_name,
            original_filename=copy_one_name,
            scene='Office',
            processing_status='ready',
            user_id=user_id,
        )
        copy_two = Photo(
            filename=copy_two_name,
            original_filename=copy_two_name,
            scene='Office',
            processing_status='ready',
            user_id=user_id,
        )
        db.session.add_all([copy_one, copy_two])
        db.session.commit()

        scan_response = self.client.post('/duplicates/scan', headers=headers, json={})
        self.assertEqual(scan_response.status_code, 200)
        scan_payload = scan_response.get_json()
        self.assertEqual(scan_payload['summary']['group_count'], 1)
        self.assertEqual(scan_payload['groups'][0]['count'], 3)
        self.assertEqual(scan_payload['groups'][0]['type'], 'exact')
        self.assertEqual(scan_payload['groups'][0]['confidence_score'], 100)

        trash_response = self.client.post(
            '/duplicates/trash',
            headers=headers,
            json={'photo_ids': [copy_one.id]},
        )
        self.assertEqual(trash_response.status_code, 200)
        self.assertEqual(trash_response.get_json()['summary']['group_count'], 1)
        self.assertEqual(trash_response.get_json()['groups'][0]['count'], 2)

        keep_response = self.client.post(
            '/duplicates/keep',
            headers=headers,
            json={'photo_id': seed.id},
        )
        self.assertEqual(keep_response.status_code, 200)
        self.assertEqual(keep_response.get_json()['kept_photo_id'], seed.id)
        self.assertEqual(keep_response.get_json()['summary']['group_count'], 0)

        active_photos = self.client.get('/photos/all', headers=headers).get_json()
        self.assertEqual(len(active_photos), 1)
        self.assertEqual(active_photos[0]['id'], seed.id)

        trashed_photos = self.client.get('/photos/all?collection=trash', headers=headers).get_json()
        self.assertEqual(len(trashed_photos), 2)

    def test_duplicates_detects_similar_photos_with_perceptual_hash(self):
        auth = self.register_user(email='duplicates-similar@example.com')
        headers = self.auth_headers(auth['access_token'])
        user_id = auth['user']['id']

        base_image = self.make_patterned_image('base')
        other_image = self.make_patterned_image('other')

        base_photo = self.create_ready_photo_from_image(user_id, 'similar-base.jpg', 'Office', base_image, quality=95)
        similar_photo = self.create_ready_photo_from_image(user_id, 'similar-copy.jpg', 'Office', base_image, quality=55)
        distinct_photo = self.create_ready_photo_from_image(user_id, 'similar-other.jpg', 'Office', other_image, quality=90)

        scan_response = self.client.post('/duplicates/scan', headers=headers, json={})
        self.assertEqual(scan_response.status_code, 200)
        payload = scan_response.get_json()

        similar_groups = [group for group in payload['groups'] if group['type'] == 'similar']
        self.assertEqual(len(similar_groups), 1)
        self.assertEqual(similar_groups[0]['count'], 2)
        self.assertGreaterEqual(similar_groups[0]['confidence_score'], 60)
        group_ids = {photo['id'] for photo in similar_groups[0]['photos']}
        self.assertEqual(group_ids, {base_photo.id, similar_photo.id})
        self.assertNotIn(distinct_photo.id, group_ids)

    def test_event_move_export_and_share(self):
        auth = self.register_user(email='event-move@example.com')
        user_id = auth['user']['id']
        headers = self.auth_headers(auth['access_token'])

        photo_one = self.create_ready_photo(user_id, 'move-1.jpg', 'Temple', [1.0, 0.0, 0.0])
        photo_two = self.create_ready_photo(user_id, 'move-2.jpg', 'Temple', [0.9, 0.1, 0.0])
        photo_three = self.create_ready_photo(user_id, 'move-3.jpg', 'Office', [0.0, 1.0, 0.0])

        source_event = Event(label='Temple Visit', dominant_scene='Temple', user_id=user_id)
        target_event = Event(label='Work Session', dominant_scene='Office', user_id=user_id)
        db.session.add_all([source_event, target_event])
        db.session.flush()

        photo_one.event_id = source_event.id
        photo_two.event_id = source_event.id
        photo_three.event_id = target_event.id
        db.session.commit()

        move_response = self.client.post(
            '/events/move-photos',
            headers=headers,
            json={'photo_ids': [photo_one.id], 'target_event_id': target_event.id},
        )
        self.assertEqual(move_response.status_code, 200)
        self.assertEqual(move_response.get_json()['target_event']['photo_count'], 2)

        source_photos_response = self.client.get(f'/events/{source_event.id}/photos', headers=headers)
        self.assertEqual(source_photos_response.status_code, 200)
        self.assertEqual(len(source_photos_response.get_json()), 1)

        export_response = self.client.get(f'/events/{target_event.id}/export', headers=headers)
        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response.mimetype, 'application/zip')

        share_response = self.client.post(f'/events/{target_event.id}/share', headers=headers, json={})
        self.assertEqual(share_response.status_code, 200)
        shared_album = self.client.get(share_response.get_json()['api_path'])
        self.assertEqual(shared_album.status_code, 200)
        self.assertEqual(shared_album.get_json()['event']['label'], 'Work Session')

    def test_remove_photo_from_event_keeps_photo_in_gallery(self):
        auth = self.register_user(email='event-remove@example.com')
        user_id = auth['user']['id']
        headers = self.auth_headers(auth['access_token'])

        photo = self.create_ready_photo(user_id, 'keep-in-gallery.jpg', 'Temple', [1.0, 0.0, 0.0])
        event = Event(label='Temple Visit', dominant_scene='Temple', user_id=user_id)
        db.session.add(event)
        db.session.flush()
        photo.event_id = event.id
        db.session.commit()

        remove_response = self.client.post(
            f'/events/{event.id}/remove-photos',
            headers=headers,
            json={'photo_ids': [photo.id]},
        )
        self.assertEqual(remove_response.status_code, 200)
        self.assertEqual(remove_response.get_json()['removed_count'], 1)
        self.assertIsNone(remove_response.get_json()['event'])

        gallery_response = self.client.get('/photos/all', headers=headers)
        self.assertEqual(gallery_response.status_code, 200)
        gallery_photos = gallery_response.get_json()
        self.assertEqual(len(gallery_photos), 1)
        self.assertIsNone(gallery_photos[0]['event_id'])


if __name__ == '__main__':
    unittest.main()
