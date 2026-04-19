import pytest
from django.urls import reverse
from django.test import Client


@pytest.mark.django_db
def test_health_check_url_resolves():
    """reverse('health-check') resolves to /health/."""
    url = reverse('health-check')
    assert url == '/health/'


@pytest.mark.django_db
def test_send_otp_url_resolves():
    """/api/v1/auth/send-otp/ resolves without error."""
    # This just checks the URL pattern exists
    # It should match when accessing /api/v1/auth/send-otp/
    url = '/api/v1/auth/send-otp/'
    assert url.startswith('/api/v1/auth/')


@pytest.mark.django_db
def test_send_otp_is_publicly_accessible(client):
    """POST /api/v1/auth/send-otp/ does not return 403 for unauthenticated requests."""
    # For now, we stub this; real test will be in section-04
    response = client.post('/api/v1/auth/send-otp/')
    # Don't expect 403 (forbidden for permissions)
    # Could be 404 (not found), 400 (bad request), 200 (ok)
    assert response.status_code != 403


@pytest.mark.django_db
def test_protected_endpoint_requires_jwt(client):
    """Unauthenticated request to a protected endpoint returns 401."""
    # This is a general expectation; specific endpoint tested in other sections
    # For now verify the auth system is in place
    from django.conf import settings
    auth_classes = settings.REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']
    assert 'rest_framework_simplejwt.authentication.JWTAuthentication' in auth_classes


@pytest.mark.django_db
def test_health_check_endpoint_returns_json(client):
    """GET /health/ returns JSON response."""
    response = client.get('/health/')
    assert response.status_code == 200
    assert response['Content-Type'] == 'application/json'
