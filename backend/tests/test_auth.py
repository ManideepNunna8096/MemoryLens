def test_register_login_and_refresh(client):
    register_response = client.post(
        '/auth/register',
        json={
            'name': 'Test User',
            'email': 'test@example.com',
            'password': 'Strong123',
        },
    )
    assert register_response.status_code == 201
    register_data = register_response.get_json()
    assert register_data['access_token']
    assert register_data['refresh_token']

    login_response = client.post(
        '/auth/login',
        json={
            'email': 'test@example.com',
            'password': 'Strong123',
        },
    )
    assert login_response.status_code == 200
    login_data = login_response.get_json()
    assert login_data['access_token']
    assert login_data['refresh_token']

    refresh_response = client.post(
        '/auth/refresh',
        headers={'Authorization': f"Bearer {login_data['refresh_token']}"},
    )
    assert refresh_response.status_code == 200
    refresh_data = refresh_response.get_json()
    assert refresh_data['access_token']


def test_register_rejects_weak_password(client):
    response = client.post(
        '/auth/register',
        json={
            'name': 'Weak User',
            'email': 'weak@example.com',
            'password': 'weak',
        },
    )
    assert response.status_code == 400
    assert 'Password' in response.get_json()['error']
