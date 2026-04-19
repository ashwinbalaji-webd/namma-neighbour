"""
Tests for POST /api/v1/auth/logout/

Covers:
- Valid refresh token returns 200
- Blacklisted token cannot be used for /auth/refresh/ (returns 401)
- Invalid or malformed token returns 400
- Missing token body returns 400
"""
import pytest
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.tests.factories import UserFactory

LOGOUT_URL = reverse("users:logout")
REFRESH_URL = reverse("users:token-refresh")


class TestLogout:
    @pytest.mark.django_db
    def test_logout_with_valid_refresh_token_returns_200(self, client):
        user = UserFactory()
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        response = client.post(
            LOGOUT_URL,
            {"refresh": str(refresh)},
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_blacklisted_refresh_token_cannot_refresh(self, client):
        """After logout, POST to /refresh/ with the same token returns 401."""
        user = UserFactory()
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        refresh_str = str(refresh)

        # Logout
        client.post(
            LOGOUT_URL,
            {"refresh": refresh_str},
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )

        # Try to refresh
        response = client.post(REFRESH_URL, {"refresh": refresh_str})
        assert response.status_code == 401

    @pytest.mark.django_db
    def test_logout_with_invalid_token_returns_400(self, client):
        user = UserFactory()
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        response = client.post(
            LOGOUT_URL,
            {"refresh": "invalid.token.string"},
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == 400

    @pytest.mark.django_db
    def test_logout_with_missing_token_returns_400(self, client):
        user = UserFactory()
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        response = client.post(
            LOGOUT_URL,
            {},
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == 400
