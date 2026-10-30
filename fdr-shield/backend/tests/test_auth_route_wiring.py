from types import SimpleNamespace

from fastapi.testclient import TestClient
from starlette.routing import Match

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
    app = create_app()
    scope = {
        'type': 'http',
        'path': '/api/v1/workflows/exceptions/stream',
        'method': 'GET',
        'root_path': '',
        'headers': [],
    }
    matches = [
        route.name
        for route in app.routes
        if route.matches(scope)[0] is Match.FULL
    ]
    assert matches[0] == 'stream_exceptions'

    client = TestClient(app)
    response = client.get('/api/v1/workflows/exceptions/stream')
    assert response.status_code == 401
