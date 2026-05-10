from pathlib import Path

import numpy as np
from PIL import Image

import background_tasks
from models import db
from models.event import Event
from models.photo import Photo
from routes import search_routes


def _register_and_login(client):
    response = client.post(
        '/auth/register',
        json={
            'name': 'Search User',
            'email': 'search@example.com',
            'password': 'Strong123',
        },
    )
    return response.get_json()


def _create_ready_photo(app, upload_dir, user_id, filename, scene, vector):
    image_path = upload_dir / filename
    Image.new('RGB', (12, 12), color='green').save(image_path, format='JPEG')

    with app.app_context():
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
        return photo.id


def test_search_returns_matching_photo(client, app, upload_dir, monkeypatch):
    auth = _register_and_login(client)
    headers = {'Authorization': f"Bearer {auth['access_token']}"}
    user_id = auth['user']['id']

    _create_ready_photo(app, upload_dir, user_id, 'search.jpg', 'Beach', [1.0, 0.0, 0.0])

    monkeypatch.setattr(
        search_routes,
        'get_text_embedding_fn',
        lambda: (lambda text: np.array([1.0, 0.0, 0.0], dtype=np.float32)),
    )

    response = client.get('/search?q=beach', headers=headers)
    assert response.status_code == 200
    results = response.get_json()
    assert len(results) == 1
    assert results[0]['scene'] == 'Beach'


def test_event_organization_job_creates_events(client, app, upload_dir, monkeypatch):
    auth = _register_and_login(client)
    headers = {'Authorization': f"Bearer {auth['access_token']}"}
    user_id = auth['user']['id']

    _create_ready_photo(app, upload_dir, user_id, 'a.jpg', 'Beach', [1.0, 0.0, 0.0])
    _create_ready_photo(app, upload_dir, user_id, 'b.jpg', 'Beach', [0.9, 0.1, 0.0])
    _create_ready_photo(app, upload_dir, user_id, 'c.jpg', 'Beach', [0.95, 0.05, 0.0])

    response = client.post('/events/organize', headers=headers)
    assert response.status_code == 202
    job_data = response.get_json()['job']
    assert job_data['status'] == 'completed'
    assert job_data['result']['events_created'] == 1
    assert job_data['result']['matched_existing_count'] == 0

    events_response = client.get('/events/all', headers=headers)
    assert events_response.status_code == 200
    events = events_response.get_json()
    assert any(event['label'] == 'Vacation & Outdoors' for event in events)

    album = next(event for event in events if event['label'] == 'Vacation & Outdoors')
    photos_response = client.get(f"/events/{album['id']}/photos", headers=headers)
    assert photos_response.status_code == 200
    assert len(photos_response.get_json()) == 3


def test_event_rename_merge_and_split(client, app, upload_dir):
    auth = _register_and_login(client)
    headers = {'Authorization': f"Bearer {auth['access_token']}"}
    user_id = auth['user']['id']

    photo_ids = [
        _create_ready_photo(app, upload_dir, user_id, 'event_a_1.jpg', 'Beach', [1.0, 0.0, 0.0]),
        _create_ready_photo(app, upload_dir, user_id, 'event_a_2.jpg', 'Beach', [0.9, 0.1, 0.0]),
        _create_ready_photo(app, upload_dir, user_id, 'event_b_1.jpg', 'City', [0.0, 1.0, 0.0]),
        _create_ready_photo(app, upload_dir, user_id, 'event_b_2.jpg', 'City', [0.1, 0.9, 0.0]),
    ]

    with app.app_context():
        event_one = Event(label='Weekend One', dominant_scene='Beach', user_id=user_id)
        event_two = Event(label='Weekend Two', dominant_scene='City', user_id=user_id)
        db.session.add_all([event_one, event_two])
        db.session.flush()

        for photo_id in photo_ids[:2]:
            photo = db.session.get(Photo, photo_id)
            photo.event_id = event_one.id

        for photo_id in photo_ids[2:]:
            photo = db.session.get(Photo, photo_id)
            photo.event_id = event_two.id

        db.session.commit()
        event_one_id = event_one.id
        event_two_id = event_two.id

    rename_response = client.patch(
        f'/events/{event_one_id}',
        headers=headers,
        json={'label': 'Weekend One Renamed'},
    )
    assert rename_response.status_code == 200
    assert rename_response.get_json()['label'] == 'Weekend One Renamed'

    merge_response = client.post(
        '/events/merge',
        headers=headers,
        json={'event_ids': [event_one_id, event_two_id], 'label': 'Merged Weekend'},
    )
    assert merge_response.status_code == 200
    merged_event = merge_response.get_json()
    assert merged_event['label'] == 'Merged Weekend'
    assert merged_event['photo_count'] == 4

    merged_photos_response = client.get(f"/events/{merged_event['id']}/photos", headers=headers)
    assert merged_photos_response.status_code == 200
    merged_photos = merged_photos_response.get_json()
    assert len(merged_photos) == 4

    split_photo_ids = [merged_photos[0]['id'], merged_photos[1]['id']]
    split_response = client.post(
        f"/events/{merged_event['id']}/split",
        headers=headers,
        json={'photo_ids': split_photo_ids, 'new_label': 'Split Weekend'},
    )
    assert split_response.status_code == 200
    split_payload = split_response.get_json()
    assert split_payload['new_event']['label'] == 'Split Weekend'
    assert split_payload['new_event']['photo_count'] == 2
    assert split_payload['source_event']['photo_count'] == 2

    events_response = client.get('/events/all', headers=headers)
    assert events_response.status_code == 200
    events = events_response.get_json()
    assert len(events) == 2
    assert sorted(event['photo_count'] for event in events) == [2, 2]


def test_event_move_export_and_share(client, app, upload_dir):
    auth = _register_and_login(client)
    headers = {'Authorization': f"Bearer {auth['access_token']}"}
    user_id = auth['user']['id']

    photo_ids = [
        _create_ready_photo(app, upload_dir, user_id, 'move_a.jpg', 'Temple', [1.0, 0.0, 0.0]),
        _create_ready_photo(app, upload_dir, user_id, 'move_b.jpg', 'Temple', [0.9, 0.1, 0.0]),
        _create_ready_photo(app, upload_dir, user_id, 'move_c.jpg', 'Office', [0.0, 1.0, 0.0]),
    ]

    with app.app_context():
        source_event = Event(label='Temple Visit', dominant_scene='Temple', user_id=user_id)
        target_event = Event(label='Work Session', dominant_scene='Office', user_id=user_id)
        db.session.add_all([source_event, target_event])
        db.session.flush()

        db.session.get(Photo, photo_ids[0]).event_id = source_event.id
        db.session.get(Photo, photo_ids[1]).event_id = source_event.id
        db.session.get(Photo, photo_ids[2]).event_id = target_event.id
        db.session.commit()

        source_event_id = source_event.id
        target_event_id = target_event.id

    move_response = client.post(
        '/events/move-photos',
        headers=headers,
        json={'photo_ids': [photo_ids[0]], 'target_event_id': target_event_id},
    )
    assert move_response.status_code == 200
    move_payload = move_response.get_json()
    assert move_payload['moved_count'] == 1
    assert move_payload['target_event']['photo_count'] == 2

    source_photos_response = client.get(f'/events/{source_event_id}/photos', headers=headers)
    assert source_photos_response.status_code == 200
    assert len(source_photos_response.get_json()) == 1

    export_response = client.get(f'/events/{target_event_id}/export', headers=headers)
    assert export_response.status_code == 200
    assert export_response.mimetype == 'application/zip'

    share_response = client.post(f'/events/{target_event_id}/share', headers=headers, json={})
    assert share_response.status_code == 200
    share_payload = share_response.get_json()

    shared_album_response = client.get(share_payload['api_path'])
    assert shared_album_response.status_code == 200
    shared_album = shared_album_response.get_json()
    assert shared_album['event']['label'] == 'Work Session'
    assert len(shared_album['photos']) == 2
