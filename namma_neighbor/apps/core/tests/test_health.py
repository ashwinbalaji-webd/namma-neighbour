import pytest
import redis.exceptions
from unittest.mock import patch
from django.db import OperationalError


@pytest.mark.django_db
def test_health_check_returns_200_when_healthy(client):
    """GET /health/ returns 200 with all-ok JSON when db and redis are up."""
    with patch("apps.core.views.connection") as mock_conn, \
         patch("apps.core.views.redis.Redis.from_url") as mock_redis:
        mock_redis.return_value.ping.return_value = True
        response = client.get("/health/")
    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "ok", "db": "ok", "redis": "ok"}


@pytest.mark.django_db
def test_health_check_requires_no_auth(client):
    """GET /health/ is accessible without any JWT or session token."""
    with patch("apps.core.views.connection") as mock_conn, \
         patch("apps.core.views.redis.Redis.from_url") as mock_redis:
        mock_redis.return_value.ping.return_value = True
        response = client.get("/health/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_health_check_returns_error_when_db_unreachable(client):
    """When connection.ensure_connection() raises, /health/ reflects the failure."""
    with patch("apps.core.views.connection") as mock_conn, \
         patch("apps.core.views.redis.Redis.from_url") as mock_redis:
        mock_conn.ensure_connection.side_effect = OperationalError("db down")
        mock_redis.return_value.ping.return_value = True
        response = client.get("/health/")
    assert response.status_code != 200
    data = response.json()
    assert data["status"] != "ok"
    assert data["db"] == "error"


@pytest.mark.django_db
def test_health_check_returns_error_when_redis_unreachable(client):
    """When redis.ping() raises, /health/ reflects the failure."""
    with patch("apps.core.views.connection") as mock_conn, \
         patch("apps.core.views.redis.Redis.from_url") as mock_redis:
        mock_redis.return_value.ping.side_effect = ConnectionError("redis down")
        response = client.get("/health/")
    assert response.status_code != 200
    data = response.json()
    assert data["status"] != "ok"
    assert data["redis"] == "error"
