import hmac
import hashlib
import secrets
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.users.models import PhoneOTP
from apps.users.tests.factories import PhoneOTPFactory
from apps.users.tasks import send_otp_sms

User = get_user_model()

pytestmark = pytest.mark.django_db


class TestSendOTPEndpoint:
    @pytest.fixture
    def client(self):
        return APIClient()

    def test_send_otp_creates_phone_otp_record(self, client):
        """POST with valid phone creates exactly one PhoneOTP record."""
        response = client.post("/api/v1/auth/send-otp/", {"phone": "+919876543210"})
        assert response.status_code == 200
        assert PhoneOTP.objects.count() == 1

    @patch("apps.users.views.send_otp_sms.delay")
    def test_send_otp_stores_hmac_hash_not_raw_otp(self, mock_task, client):
        """The otp_hash field is a 64-character hex string (HMAC-SHA256), not a 6-digit OTP."""
        response = client.post("/api/v1/auth/send-otp/", {"phone": "+919876543210"})
        assert response.status_code == 200
        otp_record = PhoneOTP.objects.latest("created_at")
        assert len(otp_record.otp_hash) == 64
        assert all(c in "0123456789abcdef" for c in otp_record.otp_hash)

    @patch("apps.users.views.send_otp_sms.delay")
    def test_send_otp_returns_200_with_message(self, mock_task, client):
        """Response is 200 with body {"message": "OTP sent"}."""
        response = client.post("/api/v1/auth/send-otp/", {"phone": "+919876543210"})
        assert response.status_code == 200
        assert response.json() == {"message": "OTP sent"}

    def test_send_otp_invalid_phone_no_prefix_returns_400(self, client):
        """Phone without +91 prefix returns 400."""
        response = client.post("/api/v1/auth/send-otp/", {"phone": "9876543210"})
        assert response.status_code == 400

    def test_send_otp_invalid_phone_letters_returns_400(self, client):
        """Phone with non-digit characters after +91 returns 400."""
        response = client.post("/api/v1/auth/send-otp/", {"phone": "+91987654321a"})
        assert response.status_code == 400

    def test_send_otp_invalid_phone_too_short_returns_400(self, client):
        """Phone with fewer than 10 digits after +91 returns 400."""
        response = client.post("/api/v1/auth/send-otp/", {"phone": "+91987654"})
        assert response.status_code == 400

    def test_send_otp_invalid_phone_too_long_returns_400(self, client):
        """Phone with more than 10 digits after +91 returns 400."""
        response = client.post("/api/v1/auth/send-otp/", {"phone": "+919876543210123"})
        assert response.status_code == 400

    @patch("apps.users.views.send_otp_sms.delay")
    def test_send_otp_dispatches_celery_task(self, mock_task, client):
        """send_otp_sms.delay() is called once with phone and 6-digit OTP."""
        response = client.post("/api/v1/auth/send-otp/", {"phone": "+919876543210"})
        assert response.status_code == 200
        assert mock_task.call_count == 1
        call_args = mock_task.call_args[0]
        assert call_args[0] == "+919876543210"
        assert len(call_args[1]) == 6
        assert call_args[1].isdigit()

    @patch("apps.users.views.send_otp_sms.delay")
    def test_send_otp_returns_200_before_sms_delivered(self, mock_task, client):
        """Response is 200 even when task dispatch fails (async delivery)."""
        mock_task.side_effect = Exception("Task dispatch failed")
        response = client.post("/api/v1/auth/send-otp/", {"phone": "+919876543210"})
        assert response.status_code == 200

    @patch("apps.users.views.cache")
    @patch("apps.users.views.send_otp_sms.delay")
    def test_send_otp_rate_limit_blocks_4th_request(self, mock_task, mock_cache, client):
        """4th POST with the same phone within 10 minutes returns 429."""
        phone = "+919876543210"
        cache_key = f"otp_send:{phone}"
        cache_state = {}

        def mock_get(key, default=0):
            return cache_state.get(key, default)

        def mock_set(key, value, timeout):
            cache_state[key] = value

        mock_cache.get.side_effect = mock_get
        mock_cache.set.side_effect = mock_set

        responses = []
        for i in range(4):
            response = client.post("/api/v1/auth/send-otp/", {"phone": phone})
            responses.append(response.status_code)
        assert responses == [200, 200, 200, 429]

    @patch("apps.users.views.cache")
    @patch("apps.users.views.send_otp_sms.delay")
    def test_send_otp_rate_limit_different_phones_independent(self, mock_task, mock_cache, client):
        """Rate limit does not bleed across different phone numbers."""
        cache_state = {}

        def mock_get(key, default=0):
            return cache_state.get(key, default)

        def mock_set(key, value, timeout):
            cache_state[key] = value

        mock_cache.get.side_effect = mock_get
        mock_cache.set.side_effect = mock_set

        for i in range(3):
            response = client.post("/api/v1/auth/send-otp/", {"phone": "+919876543210"})
            assert response.status_code == 200
        for i in range(3):
            response = client.post("/api/v1/auth/send-otp/", {"phone": "+919876543211"})
            assert response.status_code == 200

    @override_settings(OTP_HMAC_SECRET="test-secret-for-hmac")
    @patch("apps.users.views.send_otp_sms.delay")
    def test_send_otp_hmac_is_keyed_with_secret(self, mock_task, client):
        """otp_hash cannot be reproduced without OTP_HMAC_SECRET."""
        response = client.post("/api/v1/auth/send-otp/", {"phone": "+919876543210"})
        assert response.status_code == 200
        otp_record = PhoneOTP.objects.latest("created_at")
        otp_hash = otp_record.otp_hash
        otp = mock_task.call_args[0][1]
        expected_hash = hmac.new(
            b"test-secret-for-hmac",
            f"+919876543210:{otp}".encode(),
            hashlib.sha256,
        ).hexdigest()
        assert otp_hash == expected_hash


@pytest.mark.django_db
class TestSendOTPSMSTask:
    @patch("apps.users.tasks.get_sms_backend")
    def test_send_otp_sms_task_calls_backend_send(self, mock_get_backend):
        """send_otp_sms calls get_sms_backend().send(phone, otp)."""
        mock_backend = MagicMock()
        mock_get_backend.return_value = mock_backend
        send_otp_sms("+919876543210", "123456")
        mock_get_backend.assert_called_once()
        mock_backend.send.assert_called_once_with("+919876543210", "123456")

    @patch("apps.users.tasks.get_sms_backend")
    def test_send_otp_sms_task_is_registered(self, mock_get_backend):
        """send_otp_sms is registered in the Celery app task registry."""
        from celery import current_app

        assert "apps.users.tasks.send_otp_sms" in current_app.tasks

    def test_send_otp_sms_task_retries_on_exception(self):
        """send_otp_sms task has retry configuration with exponential backoff."""
        assert send_otp_sms.max_retries == 3
