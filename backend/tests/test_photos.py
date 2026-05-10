import io

import numpy as np
from PIL import Image

import background_tasks
from models import db
from models.event import Event
from models.photo import Photo


def _make_image_file(color):
    buffer = io.BytesIO()
    image = Image.new('RGB', (16, 16), color=color)
    image.save(buffer, format='JPEG')
    buffer.seek(0)
    return buffer


def _register_and_login(client):
    response = client.post(
        '/auth/register',
        json={
            'name': 'Photo User',
            'email': 'photo@example.com',
            'password': 'Strong123',
        },
    )
    return response.get_json()


def _create_photo(app, upload_dir, user_id, filename, scene='Beach', status='ready'):
    image_path = upload_dir / filename
    Image.new('RGB', (14, 14), color='purple').save(image_path, format='JPEG')

    with app.app_context():
        photo = Photo(
            filename=filename,
            original_filename=filename,
            scene=scene,
            processing_status=status,
            user_id=user_id,
        )
        if status == 'ready':
            photo.set_clip_embedding(np.asarray([1.0, 0.0, 0.0], dtype=np.float32))
        if status == 'failed':
            photo.processing_error = 'Model crashed'
            photo.scene = 'Processing Failed'
        db.session.add(photo)
        db.session.commit()
        return photo.id


def test_upload_processes_photos_and_protects_files(client, monkeypatch):
    monkeypatch.setattr(background_tasks, 'get_scene_classifier', lambda: (lambda path: 'Beach'))
    monkeypatch.setattr(
        background_tasks,
        'get_clip_embedding_fn',
        lambda: (lambda path: np.array([1.0, 0.0, 0.0], dtype=np.float32)),
    )

    auth = _register_and_login(client)
    headers = {'Authorization': f"Bearer {auth['access_token']}"}

    upload_response = client.post(
        '/photos/upload',
        headers=headers,
        content_type='multipart/form-data',
        data={
            'files': [
                (_make_image_file('red'), 'one.jpg'),
                (_make_image_file('blue'), 'two.jpg'),
            ]
        },
    )

    assert upload_response.status_code == 202
    upload_data = upload_response.get_json()
    assert upload_data['job']['status'] in {'completed', 'completed_with_errors'}
    assert upload_data['job']['result']['success_count'] == 2

    photos_response = client.get('/photos/all', headers=headers)
    assert photos_response.status_code == 200
    photos = photos_response.get_json()
    assert len(photos) == 2
    assert all(photo['processing_status'] == 'ready' for photo in photos)

    unauthorized_file = client.get(f"/photos/{photos[0]['id']}/file")
    assert unauthorized_file.status_code == 401

    authorized_file = client.get(f"/photos/{photos[0]['id']}/file", headers=headers)
    assert authorized_file.status_code == 200
    assert authorized_file.mimetype.startswith('image/')


def test_photo_bulk_actions_retry_export_and_share(client, app, upload_dir, monkeypatch):
    auth = _register_and_login(client)
    headers = {'Authorization': f"Bearer {auth['access_token']}"}
    user_id = auth['user']['id']

    ready_photo_id = _create_photo(app, upload_dir, user_id, 'ready-photo.jpg')
    failed_photo_id = _create_photo(app, upload_dir, user_id, 'failed-photo.jpg', status='failed')

    with app.app_context():
        event = Event(label='Sprint Demo', dominant_scene='Beach', user_id=user_id)
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    favorite_response = client.post(
        '/photos/bulk',
        headers=headers,
        json={'action': 'favorite', 'photo_ids': [ready_photo_id]},
    )
    assert favorite_response.status_code == 200

    favorites_response = client.get('/photos/all?collection=favorites', headers=headers)
    assert favorites_response.status_code == 200
    assert [photo['id'] for photo in favorites_response.get_json()] == [ready_photo_id]

    archive_response = client.post(
        '/photos/bulk',
        headers=headers,
        json={'action': 'archive', 'photo_ids': [ready_photo_id]},
    )
    assert archive_response.status_code == 200

    archived_response = client.get('/photos/all?collection=archived', headers=headers)
    assert archived_response.status_code == 200
    assert [photo['id'] for photo in archived_response.get_json()] == [ready_photo_id]

    restore_library_response = client.post(
        '/photos/bulk',
        headers=headers,
        json={'action': 'unarchive', 'photo_ids': [ready_photo_id]},
    )
    assert restore_library_response.status_code == 200

    move_response = client.post(
        '/photos/bulk',
        headers=headers,
        json={'action': 'move_to_event', 'photo_ids': [ready_photo_id], 'event_id': event_id},
    )
    assert move_response.status_code == 200

    trash_response = client.post(
        '/photos/bulk',
        headers=headers,
        json={'action': 'trash', 'photo_ids': [ready_photo_id]},
    )
    assert trash_response.status_code == 200

    trash_listing = client.get('/photos/all?collection=trash', headers=headers)
    assert trash_listing.status_code == 200
    assert [photo['id'] for photo in trash_listing.get_json()] == [ready_photo_id]

    restore_response = client.post(
        '/photos/bulk',
        headers=headers,
        json={'action': 'restore', 'photo_ids': [ready_photo_id]},
    )
    assert restore_response.status_code == 200

    monkeypatch.setattr(background_tasks, 'get_scene_classifier', lambda: (lambda path: 'Temple'))
    monkeypatch.setattr(
        background_tasks,
        'get_clip_embedding_fn',
        lambda: (lambda path: np.array([0.5, 0.5, 0.0], dtype=np.float32)),
    )

    retry_response = client.post(
        '/photos/retry',
        headers=headers,
        json={'photo_ids': [failed_photo_id]},
    )
    assert retry_response.status_code == 202
    retry_payload = retry_response.get_json()
    assert retry_payload['job']['status'] in {'completed', 'completed_with_errors'}

    all_photos_response = client.get('/photos/all?collection=all', headers=headers)
    assert all_photos_response.status_code == 200
    all_photos = {photo['id']: photo for photo in all_photos_response.get_json()}
    assert all_photos[failed_photo_id]['processing_status'] == 'ready'
    assert all_photos[ready_photo_id]['event_id'] == event_id

    export_response = client.post(
        '/photos/export',
        headers=headers,
        json={'photo_ids': [ready_photo_id, failed_photo_id], 'label': 'Gallery Export'},
    )
    assert export_response.status_code == 200
    assert export_response.mimetype == 'application/zip'

    share_response = client.post(
        '/photos/share',
        headers=headers,
        json={'photo_ids': [ready_photo_id]},
    )
    assert share_response.status_code == 200
    share_payload = share_response.get_json()
    shared_api_response = client.get(share_payload['api_path'])
    assert shared_api_response.status_code == 200
    assert len(shared_api_response.get_json()['photos']) == 1


def test_photo_can_be_renamed(client, app, upload_dir):
    auth = _register_and_login(client)
    headers = {'Authorization': f"Bearer {auth['access_token']}"}
    user_id = auth['user']['id']

    photo_id = _create_photo(app, upload_dir, user_id, 'abcdef1234567890abcdef1234567890.jpg')
    rename_response = client.post(
        f'/photos/{photo_id}/rename',
        headers=headers,
        json={'name': 'Campus Concert'},
    )

    assert rename_response.status_code == 200
    payload = rename_response.get_json()
    assert payload['display_name'] == 'Campus Concert'
    assert payload['original_filename'] == 'abcdef1234567890abcdef1234567890.jpg'
