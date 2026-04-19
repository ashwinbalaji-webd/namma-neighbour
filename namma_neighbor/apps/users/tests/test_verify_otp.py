"""
Tests for POST /api/v1/auth/verify-otp/

Covers:
- Correct OTP returns tokens and marks is_used=True
- Response includes user_id
- Incorrect OTP returns 400
- Already-used OTP returns 400
- Expired OTP (>10 min) returns 400
- No active OTP for phone returns 400
- After 5 failed attempts, returns 400 "Too many attempts"
- Concurrent verification: only one of two simultaneous requests succeeds
- First-time user is created on success
- Existing user is fetched (not duplicated) on second verification
- HMAC constant-time comparison is used (mock hmac.compare_digest)
"""
import hmac
import hashlib
import threading
import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from unittest.mock import patch
from datetime import timedelta

from apps.users.models import PhoneOTP, User
from apps.users.tests.factories import UserFactory

VERIFY_URL = reverse("users:verify-otp")


def make_valid_otp_record(phone, otp, used=False, attempt_count=0):
    """Helper: create a PhoneOTP with valid HMAC hash for the given phone+otp."""
    from django.conf import settings
    otp_hash = hmac.new(
        settings.OTP_HMAC_SECRET.encode(),
        f"{phone}:{otp}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return PhoneOTP.objects.create(
        phone=phone,
        otp_hash=otp_hash,
        is_used=used,
        attempt_count=attempt_count,
    )


class TestVerifyOTPSuccess:
    @pytest.mark.django_db
    def test_correct_otp_returns_access_and_refresh_tokens(self, client):
        phone = "+919876543210"
        otp = "123456"
        make_valid_otp_record(phone, otp)

        response = client.post(VERIFY_URL, {"phone": phone, "otp": otp})
        assert response.status_code == 200
        assert "access" in response.json()
        assert "refresh" in response.json()

    @pytest.mark.django_db
    def test_correct_otp_response_includes_user_id(self, client):
        phone = "+919876543210"
        otp = "123456"
        make_valid_otp_record(phone, otp)

        response = client.post(VERIFY_URL, {"phone": phone, "otp": otp})
        assert response.status_code == 200
        data = response.json()
        assert "user_id" in data
        assert isinstance(data["user_id"], int)

    @pytest.mark.django_db
    def test_correct_otp_marks_is_used_true(self, client):
        phone = "+919876543210"
        otp = "123456"
        otp_record = make_valid_otp_record(phone, otp)

        client.post(VERIFY_URL, {"phone": phone, "otp": otp})
        otp_record.refresh_from_db()
        assert otp_record.is_used is True

    @pytest.mark.django_db
    def test_first_verification_creates_new_user(self, client):
        phone = "+919876543210"
        otp = "123456"
        make_valid_otp_record(phone, otp)
        assert User.objects.filter(phone=phone).count() == 0

        client.post(VERIFY_URL, {"phone": phone, "otp": otp})
        assert User.objects.filter(phone=phone).count() == 1

    @pytest.mark.django_db
    def test_second_verification_does_not_duplicate_user(self, client):
        """Send OTP twice for the same phone; verify both succeed; user count stays 1."""
        phone = "+919876543210"
        otp1 = "111111"
        otp2 = "222222"

        make_valid_otp_record(phone, otp1)
        response1 = client.post(VERIFY_URL, {"phone": phone, "otp": otp1})
        assert response1.status_code == 200
        assert User.objects.filter(phone=phone).count() == 1

        make_valid_otp_record(phone, otp2)
        response2 = client.post(VERIFY_URL, {"phone": phone, "otp": otp2})
        assert response2.status_code == 200
        assert User.objects.filter(phone=phone).count() == 1


class TestVerifyOTPFailure:
    @pytest.mark.django_db
    def test_wrong_otp_returns_400(self, client):
        phone = "+919876543210"
        otp = "123456"
        make_valid_otp_record(phone, otp)

        response = client.post(VERIFY_URL, {"phone": phone, "otp": "999999"})
        assert response.status_code == 400
        assert "error" in response.json()

    @pytest.mark.django_db
    def test_used_otp_returns_400(self, client):
        phone = "+919876543210"
        otp = "123456"
        make_valid_otp_record(phone, otp, used=True)

        response = client.post(VERIFY_URL, {"phone": phone, "otp": otp})
        assert response.status_code == 400

    @pytest.mark.django_db
    def test_no_active_otp_returns_400(self, client):
        phone = "+919876543210"
        response = client.post(VERIFY_URL, {"phone": phone, "otp": "123456"})
        assert response.status_code == 400
        assert response.json()["error"] == "otp_not_found"

    @pytest.mark.django_db
    def test_expired_otp_returns_400(self, client):
        """Use freezegun to advance time past 10 minutes."""
        phone = "+919876543210"
        otp = "123456"

        with freeze_time("2026-04-19 10:00:00"):
            make_valid_otp_record(phone, otp)

        with freeze_time("2026-04-19 10:11:00"):
            response = client.post(VERIFY_URL, {"phone": phone, "otp": otp})
            assert response.status_code == 400
            assert response.json()["error"] == "otp_not_found"

    @pytest.mark.django_db
    def test_too_many_attempts_returns_400(self, client):
        """Create a PhoneOTP with attempt_count=5; verify with wrong OTP."""
        phone = "+919876543210"
        otp = "123456"
        make_valid_otp_record(phone, otp, attempt_count=5)

        response = client.post(VERIFY_URL, {"phone": phone, "otp": "999999"})
        assert response.status_code == 400
        assert response.json()["error"] == "too_many_attempts"

    @pytest.mark.django_db
    def test_hmac_uses_constant_time_comparison(self, client):
        """Patch hmac.compare_digest and assert it is called during verification."""
        phone = "+919876543210"
        otp = "123456"
        make_valid_otp_record(phone, otp)

        with patch("hmac.compare_digest", wraps=hmac.compare_digest) as mock_cd:
            client.post(VERIFY_URL, {"phone": phone, "otp": "999999"})
            mock_cd.assert_called()

    @pytest.mark.django_db
    def test_missing_phone_returns_400(self, client):
        response = client.post(VERIFY_URL, {"otp": "123456"})
        assert response.status_code == 400

    @pytest.mark.django_db
    def test_missing_otp_returns_400(self, client):
        response = client.post(VERIFY_URL, {"phone": "+919876543210"})
        assert response.status_code == 400

    @pytest.mark.django_db
    def test_invalid_phone_format_returns_400(self, client):
        response = client.post(VERIFY_URL, {"phone": "1234567890", "otp": "123456"})
        assert response.status_code == 400


class TestVerifyOTPConcurrent:
    @pytest.mark.django_db(transaction=True)
    def test_concurrent_requests_only_one_succeeds(self):
        """
        Two threads both POST verify-otp with the same correct OTP simultaneously.
        Only one should receive tokens; the other should receive a 400 (OTP already used
        or no active OTP found). Uses threading, not async. Requires transaction=True to
        allow each thread to see committed data.

        Note: SQLite has limitations with concurrent transactions, so this test may fail
        on SQLite. It works fine on PostgreSQL and other production databases.
        """
        from django.db import connection
        if connection.vendor == 'sqlite':
            pytest.skip("SQLite does not handle concurrent transactions well")

        phone = "+919876543210"
        otp = "123456"
        make_valid_otp_record(phone, otp)

        results = {}

        def make_request(thread_id):
            from django.test import Client
            client = Client()
            response = client.post(VERIFY_URL, {"phone": phone, "otp": otp})
            results[thread_id] = response.status_code

        thread1 = threading.Thread(target=make_request, args=(1,))
        thread2 = threading.Thread(target=make_request, args=(2,))

        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        status_codes = [results[1], results[2]]
        assert 200 in status_codes
        assert 400 in status_codes
