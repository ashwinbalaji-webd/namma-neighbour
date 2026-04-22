diff --git a/namma_neighbor/apps/vendors/services/razorpay.py b/namma_neighbor/apps/vendors/services/razorpay.py
index 2f2c3187..9aa12e0b 100644
--- a/namma_neighbor/apps/vendors/services/razorpay.py
+++ b/namma_neighbor/apps/vendors/services/razorpay.py
@@ -1 +1,108 @@
-# TODO: section-04
+import requests
+from django.conf import settings
+
+from apps.core.exceptions import RazorpayError, TransientAPIError
+from apps.vendors.models import Vendor
+
+
+class RazorpayClient:
+    """Wraps the Razorpay Route (Linked Accounts) API.
+
+    Uses HTTP Basic Auth with RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET.
+    All requests time out after 10 seconds.
+
+    Error translation:
+      HTTP 400, 409  -> RazorpayError (permanent, no retry)
+      HTTP 429, 5xx  -> TransientAPIError (retriable)
+      Timeout / ConnectionError -> TransientAPIError
+    """
+
+    BASE_URL = "https://api.razorpay.com"
+
+    def __init__(self):
+        self.key_id = settings.RAZORPAY_KEY_ID
+        self.key_secret = settings.RAZORPAY_KEY_SECRET
+
+    def _auth(self):
+        return (self.key_id, self.key_secret)
+
+    def _handle_response(self, response: requests.Response) -> dict:
+        if response.status_code in (400, 409):
+            raise RazorpayError()
+        if response.status_code == 429 or response.status_code >= 500:
+            raise TransientAPIError()
+        return response.json()
+
+    def create_linked_account(self, vendor: Vendor) -> str:
+        """POST /v2/accounts with type='route'.
+
+        Returns the Razorpay account ID string (e.g. 'acc_XXXXX').
+        Sets reference_id=str(vendor.pk) for Razorpay-side idempotency.
+
+        Raises RazorpayError on 400/409.
+        Raises TransientAPIError on 429/5xx/timeout.
+        """
+        url = f"{self.BASE_URL}/v2/accounts"
+        payload = {
+            "type": "route",
+            "reference_id": str(vendor.pk),
+            "email": f"vendor_{vendor.pk}@placeholder.namma",  # TODO(split-05): collect email during full KYB
+            "phone": vendor.user.phone,
+            "legal_business_name": vendor.display_name,
+            "business_type": "individual",  # TODO(split-05): add business_type field to Vendor
+            "contact_name": vendor.display_name,  # TODO(split-05): use actual contact_name from KYB
+            "profile": {
+                "category": "others",  # TODO(split-05): map from Vendor product category
+                "addresses": {
+                    "registered": {  # TODO(split-05): collect registered address during full KYB
+                        "street1": "NA",
+                        "city": "NA",
+                        "state": "NA",
+                        "postal_code": "000000",
+                        "country": "IN",
+                    }
+                },
+            },
+            "legal_info": {
+                "pan": "",  # TODO(split-05): collect PAN during full KYB
+            },
+        }
+        try:
+            response = requests.post(url, json=payload, auth=self._auth(), timeout=10)
+        except (requests.Timeout, requests.ConnectionError) as exc:
+            raise TransientAPIError(str(exc)) from exc
+        return self._handle_response(response)["id"]
+
+    def add_stakeholder(self, account_id: str, vendor: Vendor) -> str:
+        """POST /v2/accounts/{account_id}/stakeholders.
+
+        Returns the stakeholder_id string.
+        Raises RazorpayError on 400/409.
+        Raises TransientAPIError on 429/5xx/timeout.
+        """
+        url = f"{self.BASE_URL}/v2/accounts/{account_id}/stakeholders"
+        payload = {
+            "name": vendor.display_name,  # TODO(split-05): use actual contact_name from KYB
+            "phone": vendor.user.phone,
+        }
+        try:
+            response = requests.post(url, json=payload, auth=self._auth(), timeout=10)
+        except (requests.Timeout, requests.ConnectionError) as exc:
+            raise TransientAPIError(str(exc)) from exc
+        return self._handle_response(response)["id"]
+
+    def submit_for_review(self, account_id: str) -> None:
+        """PATCH /v2/accounts/{account_id} to trigger Razorpay compliance review.
+
+        Returns None on success (Razorpay responds asynchronously via webhook).
+        Raises RazorpayError on 400/409.
+        Raises TransientAPIError on 429/5xx/timeout.
+        """
+        url = f"{self.BASE_URL}/v2/accounts/{account_id}"
+        payload = {"profile": {"uses_razorpay": True}}
+        try:
+            response = requests.patch(url, json=payload, auth=self._auth(), timeout=10)
+        except (requests.Timeout, requests.ConnectionError) as exc:
+            raise TransientAPIError(str(exc)) from exc
+        self._handle_response(response)
+        return None
diff --git a/namma_neighbor/apps/vendors/tests/test_services.py b/namma_neighbor/apps/vendors/tests/test_services.py
index 27fe6e81..abc2f13d 100644
--- a/namma_neighbor/apps/vendors/tests/test_services.py
+++ b/namma_neighbor/apps/vendors/tests/test_services.py
@@ -1 +1,150 @@
-# TODO: sections 03, 04
+import pytest
+import requests
+from unittest.mock import patch, Mock
+
+from apps.vendors.services.razorpay import RazorpayClient
+from apps.core.exceptions import RazorpayError, TransientAPIError
+
+
+def make_response(status_code, json_data=None):
+    r = Mock()
+    r.status_code = status_code
+    r.json.return_value = json_data if json_data is not None else {}
+    return r
+
+
+@pytest.fixture
+def razorpay_client():
+    return RazorpayClient()
+
+
+# --- create_linked_account ---
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_create_linked_account_calls_correct_url(mock_post, vendor, razorpay_client):
+    mock_post.return_value = make_response(200, {"id": "acc_test123"})
+    razorpay_client.create_linked_account(vendor)
+    url = mock_post.call_args.args[0]
+    assert url.endswith("/v2/accounts")
+
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_create_linked_account_payload_type_route(mock_post, vendor, razorpay_client):
+    mock_post.return_value = make_response(200, {"id": "acc_test123"})
+    razorpay_client.create_linked_account(vendor)
+    payload = mock_post.call_args.kwargs["json"]
+    assert payload["type"] == "route"
+
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_create_linked_account_payload_reference_id(mock_post, vendor, razorpay_client):
+    mock_post.return_value = make_response(200, {"id": "acc_test123"})
+    razorpay_client.create_linked_account(vendor)
+    payload = mock_post.call_args.kwargs["json"]
+    assert payload["reference_id"] == str(vendor.pk)
+
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_create_linked_account_returns_account_id(mock_post, vendor, razorpay_client):
+    mock_post.return_value = make_response(200, {"id": "acc_test123"})
+    result = razorpay_client.create_linked_account(vendor)
+    assert result == "acc_test123"
+
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_create_linked_account_raises_razorpay_error_on_400(mock_post, vendor, razorpay_client):
+    mock_post.return_value = make_response(400)
+    with pytest.raises(RazorpayError):
+        razorpay_client.create_linked_account(vendor)
+
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_create_linked_account_raises_razorpay_error_on_409(mock_post, vendor, razorpay_client):
+    mock_post.return_value = make_response(409)
+    with pytest.raises(RazorpayError):
+        razorpay_client.create_linked_account(vendor)
+
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_create_linked_account_raises_transient_on_500(mock_post, vendor, razorpay_client):
+    mock_post.return_value = make_response(500)
+    with pytest.raises(TransientAPIError):
+        razorpay_client.create_linked_account(vendor)
+
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_create_linked_account_raises_transient_on_429(mock_post, vendor, razorpay_client):
+    mock_post.return_value = make_response(429)
+    with pytest.raises(TransientAPIError):
+        razorpay_client.create_linked_account(vendor)
+
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_create_linked_account_raises_transient_on_timeout(mock_post, vendor, razorpay_client):
+    mock_post.side_effect = requests.Timeout()
+    with pytest.raises(TransientAPIError):
+        razorpay_client.create_linked_account(vendor)
+
+
+# --- add_stakeholder ---
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_add_stakeholder_calls_correct_url(mock_post, vendor, razorpay_client):
+    account_id = "acc_test123"
+    mock_post.return_value = make_response(200, {"id": "sth_abc"})
+    razorpay_client.add_stakeholder(account_id, vendor)
+    url = mock_post.call_args.args[0]
+    assert f"/v2/accounts/{account_id}/stakeholders" in url
+
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_add_stakeholder_returns_stakeholder_id(mock_post, vendor, razorpay_client):
+    mock_post.return_value = make_response(200, {"id": "sth_abc"})
+    result = razorpay_client.add_stakeholder("acc_test123", vendor)
+    assert result == "sth_abc"
+
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_add_stakeholder_raises_razorpay_error_on_400(mock_post, vendor, razorpay_client):
+    mock_post.return_value = make_response(400)
+    with pytest.raises(RazorpayError):
+        razorpay_client.add_stakeholder("acc_test123", vendor)
+
+
+@patch("apps.vendors.services.razorpay.requests.post")
+def test_add_stakeholder_raises_transient_on_500(mock_post, vendor, razorpay_client):
+    mock_post.return_value = make_response(500)
+    with pytest.raises(TransientAPIError):
+        razorpay_client.add_stakeholder("acc_test123", vendor)
+
+
+# --- submit_for_review ---
+
+@patch("apps.vendors.services.razorpay.requests.patch")
+def test_submit_for_review_sends_patch_to_correct_url(mock_patch, razorpay_client):
+    account_id = "acc_test123"
+    mock_patch.return_value = make_response(200, {"id": account_id})
+    razorpay_client.submit_for_review(account_id)
+    url = mock_patch.call_args.args[0]
+    assert f"/v2/accounts/{account_id}" in url
+
+
+@patch("apps.vendors.services.razorpay.requests.patch")
+def test_submit_for_review_returns_none(mock_patch, razorpay_client):
+    mock_patch.return_value = make_response(200, {"id": "acc_test123"})
+    result = razorpay_client.submit_for_review("acc_test123")
+    assert result is None
+
+
+@patch("apps.vendors.services.razorpay.requests.patch")
+def test_submit_for_review_raises_razorpay_error_on_400(mock_patch, razorpay_client):
+    mock_patch.return_value = make_response(400)
+    with pytest.raises(RazorpayError):
+        razorpay_client.submit_for_review("acc_test123")
+
+
+@patch("apps.vendors.services.razorpay.requests.patch")
+def test_submit_for_review_raises_transient_on_500(mock_patch, razorpay_client):
+    mock_patch.return_value = make_response(500)
+    with pytest.raises(TransientAPIError):
+        razorpay_client.submit_for_review("acc_test123")
