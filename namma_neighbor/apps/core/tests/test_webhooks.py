import hashlib
import hmac
import json
from unittest.mock import patch

import pytest

from apps.vendors.tests.factories import VendorFactory

WEBHOOK_URL = "/api/v1/webhooks/razorpay/"
TEST_SECRET = "test-webhook-secret"
TEST_ACCOUNT_ID = "acc_test123"


def _signed_request(payload_dict: dict, secret: str = TEST_SECRET) -> tuple[bytes, dict]:
    """Return (body_bytes, headers) for a correctly signed Razorpay webhook."""
    body = json.dumps(payload_dict).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, {"HTTP_X_RAZORPAY_SIGNATURE": digest, "content_type": "application/json"}


def _account_activated_payload(account_id: str = TEST_ACCOUNT_ID) -> dict:
    return {
        "event": "account.activated",
        "payload": {
            "account": {
                "entity": {"id": account_id}
            }
        },
    }


# ─── Signature Verification ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestRazorpayWebhookSignatureVerification:
    def test_missing_signature_header_returns_400(self, client, settings):
        settings.RAZORPAY_WEBHOOK_SECRET = TEST_SECRET
        response = client.post(
            WEBHOOK_URL,
            data=json.dumps({"event": "account.activated"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_incorrect_signature_returns_400(self, client, settings):
        settings.RAZORPAY_WEBHOOK_SECRET = TEST_SECRET
        body, headers = _signed_request({"event": "account.activated"})
        headers["HTTP_X_RAZORPAY_SIGNATURE"] = "badhex" + "0" * 60
        response = client.post(WEBHOOK_URL, data=body, **headers)
        assert response.status_code == 400

    def test_valid_signature_returns_200(self, client, settings):
        settings.RAZORPAY_WEBHOOK_SECRET = TEST_SECRET
        body, headers = _signed_request({"event": "unknown.event"})
        response = client.post(WEBHOOK_URL, data=body, **headers)
        assert response.status_code == 200

    def test_uses_hmac_compare_digest(self, client, settings):
        settings.RAZORPAY_WEBHOOK_SECRET = TEST_SECRET
        body, headers = _signed_request({"event": "account.activated"})
        with patch("apps.core.views_webhooks.hmac.compare_digest", return_value=True) as mock_cd:
            client.post(WEBHOOK_URL, data=body, **headers)
        mock_cd.assert_called_once()


# ─── account.activated event ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestRazorpayWebhookAccountActivated:
    @pytest.fixture(autouse=True)
    def _mock_sms(self):
        with patch("apps.core.views_webhooks.notify_vendor_account_activated"):
            yield

    def _post(self, client, settings, account_id=TEST_ACCOUNT_ID):
        settings.RAZORPAY_WEBHOOK_SECRET = TEST_SECRET
        body, headers = _signed_request(_account_activated_payload(account_id))
        return client.post(WEBHOOK_URL, data=body, **headers)

    def test_account_activated_sets_status_activated(self, client, settings):
        vendor = VendorFactory(razorpay_account_id=TEST_ACCOUNT_ID)
        self._post(client, settings)
        vendor.refresh_from_db()
        assert vendor.razorpay_account_status == "activated"

    def test_account_activated_sets_bank_account_verified_true(self, client, settings):
        vendor = VendorFactory(razorpay_account_id=TEST_ACCOUNT_ID, bank_account_verified=False)
        self._post(client, settings)
        vendor.refresh_from_db()
        assert vendor.bank_account_verified is True

    def test_account_activated_unknown_id_returns_200(self, client, settings):
        response = self._post(client, settings, account_id="acc_unknown_xyz")
        assert response.status_code == 200

    def test_account_activated_is_idempotent(self, client, settings):
        vendor = VendorFactory(razorpay_account_id=TEST_ACCOUNT_ID)
        self._post(client, settings)
        response = self._post(client, settings)
        assert response.status_code == 200
        vendor.refresh_from_db()
        assert vendor.razorpay_account_status == "activated"
        assert vendor.bank_account_verified is True

    def test_account_activated_enqueues_sms_notification(self, client, settings):
        vendor = VendorFactory(razorpay_account_id=TEST_ACCOUNT_ID)
        with patch("apps.core.views_webhooks.notify_vendor_account_activated") as mock_task:
            self._post(client, settings)
        mock_task.delay.assert_called_once_with(vendor.id)
