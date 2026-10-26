from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import create_app


def test_public_setup_route_is_registered_and_unavailable_without_backend_secret(monkeypatch):
    import app.api.v1.auth as auth_routes
    monkeypatch.setattr(auth_routes, 'get_settings', lambda: SimpleNamespace(super_admin_setup_secret=''))
    client = TestClient(create_app())
    response = client.post('/api/v1/auth/register/super-admin', json={
        'full_name': 'First Owner', 'email': 'first-owner@example.test',
        'phone_number': '+1 202 555 0142', 'password': 'Setup-Owner-Password-2026',
        'confirm_password': 'Setup-Owner-Password-2026', 'setup_secret': 'test-secret',
    })
    assert response.status_code == 503
    assert 'setup secret' not in response.text.lower()


def test_exception_stream_static_route_is_not_parsed_as_workflow_id():
    client = TestClient(create_app())
    response = client.get('/api/v1/workflows/exceptions/stream')
    # The route is found and auth is enforced; a dynamic int path must not return 422.
    assert response.status_code == 401
