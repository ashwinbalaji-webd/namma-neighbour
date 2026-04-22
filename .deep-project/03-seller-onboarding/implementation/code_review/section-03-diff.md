diff --git a/namma_neighbor/apps/vendors/services/fssai.py b/namma_neighbor/apps/vendors/services/fssai.py
index d0167e0a..ddd853ca 100644
--- a/namma_neighbor/apps/vendors/services/fssai.py
+++ b/namma_neighbor/apps/vendors/services/fssai.py
@@ -1 +1,57 @@
-# TODO: section-03
+import datetime
+import requests
+from django.conf import settings
+from apps.core.exceptions import FSSAIVerificationError, TransientAPIError
+
+
+class SurepassFSSAIClient:
+    BASE_URL = "https://kyc-api.surepass.io/api/v1"
+
+    def _headers(self):
+        return {
+            "Authorization": f"Bearer {settings.SUREPASS_TOKEN}",
+            "Content-Type": "application/json",
+        }
+
+    def _raise_for_status(self, response):
+        status = response.status_code
+        if status in (400, 404):
+            raise FSSAIVerificationError()
+        if status == 429 or status >= 500:
+            raise TransientAPIError()
+
+    def verify_fssai(self, license_number: str) -> dict:
+        try:
+            response = requests.post(
+                f"{self.BASE_URL}/fssai/fssai-full-details",
+                json={"id": license_number},
+                headers=self._headers(),
+                timeout=10,
+            )
+        except (requests.Timeout, requests.ConnectionError):
+            raise TransientAPIError()
+        self._raise_for_status(response)
+        data = response.json()["data"]
+        return {
+            "status": data["license_status"],
+            "business_name": data["business_name"],
+            "expiry_date": datetime.date.fromisoformat(data["expiry_date"]),
+            "authorized_categories": data.get("authorized_categories") or [],
+        }
+
+    def check_expiry(self, license_number: str) -> dict:
+        try:
+            response = requests.post(
+                f"{self.BASE_URL}/fssai/fssai-expiry-check",
+                json={"id": license_number},
+                headers=self._headers(),
+                timeout=10,
+            )
+        except (requests.Timeout, requests.ConnectionError):
+            raise TransientAPIError()
+        self._raise_for_status(response)
+        data = response.json()["data"]
+        return {
+            "status": data["license_status"],
+            "expiry_date": datetime.date.fromisoformat(data["expiry_date"]),
+        }
diff --git a/namma_neighbor/apps/vendors/tests/test_fssai_service.py b/namma_neighbor/apps/vendors/tests/test_fssai_service.py
new file mode 100644
index 00000000..6bdfaf73
--- /dev/null
+++ b/namma_neighbor/apps/vendors/tests/test_fssai_service.py
@@ -0,0 +1,102 @@
+import datetime
+import pytest
+import requests
+from unittest.mock import patch, Mock
+from apps.vendors.services.fssai import SurepassFSSAIClient
+from apps.core.exceptions import FSSAIVerificationError, TransientAPIError
+
+
+def make_mock_response(status_code, json_data):
+    response = Mock()
+    response.status_code = status_code
+    response.json.return_value = json_data
+    return response
+
+
+VALID_RESPONSE = {
+    "success": True,
+    "data": {
+        "license_status": "active",
+        "business_name": "Ravi's Kitchen",
+        "expiry_date": "2026-03-31",
+        "authorized_categories": ["dairy", "bakery"],
+    },
+}
+
+EXPIRY_RESPONSE = {
+    "success": True,
+    "data": {
+        "license_status": "active",
+        "expiry_date": "2026-03-31",
+    },
+}
+
+
+@patch("apps.vendors.services.fssai.requests.post")
+def test_verify_fssai_returns_normalized_dict(mock_post):
+    mock_post.return_value = make_mock_response(200, VALID_RESPONSE)
+    client = SurepassFSSAIClient()
+    result = client.verify_fssai("12345678901234")
+    assert result["status"] == "active"
+    assert result["business_name"] == "Ravi's Kitchen"
+    assert result["expiry_date"] == datetime.date(2026, 3, 31)
+    assert result["authorized_categories"] == ["dairy", "bakery"]
+
+
+@patch("apps.vendors.services.fssai.requests.post")
+def test_verify_fssai_raises_on_http_400(mock_post):
+    mock_post.return_value = make_mock_response(400, {"success": False})
+    client = SurepassFSSAIClient()
+    with pytest.raises(FSSAIVerificationError):
+        client.verify_fssai("invalid")
+
+
+@patch("apps.vendors.services.fssai.requests.post")
+def test_verify_fssai_raises_on_http_404(mock_post):
+    mock_post.return_value = make_mock_response(404, {"success": False})
+    client = SurepassFSSAIClient()
+    with pytest.raises(FSSAIVerificationError):
+        client.verify_fssai("notfound")
+
+
+@patch("apps.vendors.services.fssai.requests.post")
+def test_verify_fssai_raises_transient_on_http_500(mock_post):
+    mock_post.return_value = make_mock_response(500, {})
+    client = SurepassFSSAIClient()
+    with pytest.raises(TransientAPIError):
+        client.verify_fssai("12345678901234")
+
+
+@patch("apps.vendors.services.fssai.requests.post")
+def test_verify_fssai_raises_transient_on_http_429(mock_post):
+    mock_post.return_value = make_mock_response(429, {})
+    client = SurepassFSSAIClient()
+    with pytest.raises(TransientAPIError):
+        client.verify_fssai("12345678901234")
+
+
+@patch("apps.vendors.services.fssai.requests.post")
+def test_verify_fssai_raises_transient_on_timeout(mock_post):
+    mock_post.side_effect = requests.Timeout()
+    client = SurepassFSSAIClient()
+    with pytest.raises(TransientAPIError):
+        client.verify_fssai("12345678901234")
+
+
+@patch("apps.vendors.services.fssai.requests.post")
+def test_check_expiry_calls_expiry_endpoint(mock_post):
+    mock_post.return_value = make_mock_response(200, EXPIRY_RESPONSE)
+    client = SurepassFSSAIClient()
+    client.check_expiry("12345678901234")
+    called_url = mock_post.call_args[0][0]
+    assert "fssai-expiry-check" in called_url
+    assert "fssai-full-details" not in called_url
+
+
+@patch("apps.vendors.services.fssai.requests.post")
+def test_check_expiry_returns_normalized_dict(mock_post):
+    mock_post.return_value = make_mock_response(200, EXPIRY_RESPONSE)
+    client = SurepassFSSAIClient()
+    result = client.check_expiry("12345678901234")
+    assert result["status"] == "active"
+    assert result["expiry_date"] == datetime.date(2026, 3, 31)
diff --git a/namma_neighbor/config/settings/test.py b/namma_neighbor/config/settings/test.py
index e2f3264b..da7f2a79 100644
--- a/namma_neighbor/config/settings/test.py
+++ b/namma_neighbor/config/settings/test.py
@@ -19,3 +19,10 @@ CACHES = {
         'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
     }
 }
+
+SUREPASS_TOKEN = 'test-surepass-token'
+RAZORPAY_KEY_ID = 'test-key-id'
+RAZORPAY_KEY_SECRET = 'test-key-secret'
+RAZORPAY_WEBHOOK_SECRET = 'test-webhook-secret'
+AWS_ACCESS_KEY_ID = 'test-access-key'
+AWS_SECRET_ACCESS_KEY = 'test-secret-key'
