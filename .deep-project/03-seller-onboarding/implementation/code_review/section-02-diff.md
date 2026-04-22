diff --git a/namma_neighbor/apps/core/exceptions.py b/namma_neighbor/apps/core/exceptions.py
index feb948ef..14686193 100644
--- a/namma_neighbor/apps/core/exceptions.py
+++ b/namma_neighbor/apps/core/exceptions.py
@@ -34,3 +34,55 @@ def custom_exception_handler(exc, context):
         'detail': response.data.get('detail') or str(response.data),
     }
     return response
+
+
+from rest_framework.exceptions import APIException  # noqa: E402
+
+
+class ExternalAPIError(APIException):
+    """Base exception for all third-party API failures.
+
+    HTTP 503. Subclass rather than raising directly — use TransientAPIError
+    or PermanentAPIError depending on whether the failure is retriable.
+    """
+    status_code = 503
+    default_detail = "An upstream service call failed."
+    default_code = "external_api_error"
+
+
+class TransientAPIError(ExternalAPIError):
+    """Third-party failure is temporary; retrying may succeed.
+
+    Examples: HTTP 5xx, requests.Timeout, requests.ConnectionError, HTTP 429.
+    Listed in Celery autoretry_for tuples.
+    """
+    default_code = "transient_api_error"
+
+
+class PermanentAPIError(ExternalAPIError):
+    """Third-party failure is definitively non-retriable.
+
+    Examples: HTTP 400/404 from external API. Celery tasks catch this and do
+    not re-raise to prevent retry loops.
+    """
+    default_code = "permanent_api_error"
+
+
+class RazorpayError(PermanentAPIError):
+    """Razorpay-specific business logic error (duplicate ref, invalid bank account).
+
+    HTTP 402 — signals a payment processing issue to the API caller.
+    """
+    status_code = 402
+    default_detail = "A Razorpay API error occurred."
+    default_code = "razorpay_error"
+
+
+class FSSAIVerificationError(PermanentAPIError):
+    """FSSAI license verification permanent failure (invalid format, not found).
+
+    HTTP 400 — the vendor's submitted license data is invalid.
+    """
+    status_code = 400
+    default_detail = "FSSAI license verification failed."
+    default_code = "fssai_verification_error"
diff --git a/namma_neighbor/apps/core/permissions.py b/namma_neighbor/apps/core/permissions.py
index f6da00d1..a2f72e51 100644
--- a/namma_neighbor/apps/core/permissions.py
+++ b/namma_neighbor/apps/core/permissions.py
@@ -31,3 +31,15 @@ class IsPlatformAdmin(BasePermission):
             return False
         roles = request.auth.payload.get('roles', [])
         return 'platform_admin' in roles
+
+
+class IsVendorOwner(BasePermission):
+    """Object-level permission: request.user must be the Vendor's owning user.
+
+    Views must call self.check_object_permissions(request, vendor) explicitly
+    after fetching the Vendor by vendor_id. Still requires IsAuthenticated at
+    the view level so unauthenticated requests are rejected before this runs.
+    """
+
+    def has_object_permission(self, request, view, obj) -> bool:
+        return obj.user_id == request.user.id
diff --git a/namma_neighbor/apps/core/tests/test_exceptions.py b/namma_neighbor/apps/core/tests/test_exceptions.py
index 07c79503..ef0a23d8 100644
--- a/namma_neighbor/apps/core/tests/test_exceptions.py
+++ b/namma_neighbor/apps/core/tests/test_exceptions.py
@@ -3,7 +3,11 @@ from rest_framework.exceptions import (
     ValidationError, PermissionDenied, NotAuthenticated,
     AuthenticationFailed, NotFound, MethodNotAllowed
 )
-from apps.core.exceptions import custom_exception_handler
+from apps.core.exceptions import (
+    custom_exception_handler,
+    ExternalAPIError, TransientAPIError, PermanentAPIError,
+    RazorpayError, FSSAIVerificationError,
+)
 
 
 def test_validation_error_format():
@@ -80,3 +84,28 @@ def test_non_drf_exception_returns_none():
     exc = Exception("Generic error")
     response = custom_exception_handler(exc, {})
     assert response is None
+
+
+# --- ExternalAPIError hierarchy ---
+
+def test_external_api_error_serializes_via_custom_handler():
+    exc = ExternalAPIError("upstream failure")
+    response = custom_exception_handler(exc, {})
+    assert response is not None
+    assert response.status_code == 503
+    assert "error" in response.data
+    assert "detail" in response.data
+
+
+def test_transient_api_error_is_subclass_of_external():
+    assert issubclass(TransientAPIError, ExternalAPIError)
+
+
+def test_fssai_verification_error_returns_400():
+    exc = FSSAIVerificationError()
+    assert exc.status_code == 400
+
+
+def test_razorpay_error_returns_402():
+    exc = RazorpayError()
+    assert exc.status_code == 402
diff --git a/namma_neighbor/apps/core/tests/test_permissions.py b/namma_neighbor/apps/core/tests/test_permissions.py
index 82f0adac..5f899ca0 100644
--- a/namma_neighbor/apps/core/tests/test_permissions.py
+++ b/namma_neighbor/apps/core/tests/test_permissions.py
@@ -2,7 +2,7 @@ import pytest
 from unittest.mock import Mock
 from apps.core.permissions import (
     IsResidentOfCommunity, IsVendorOfCommunity,
-    IsCommunityAdmin, IsPlatformAdmin
+    IsCommunityAdmin, IsPlatformAdmin, IsVendorOwner
 )
 
 
@@ -88,3 +88,25 @@ def test_all_permissions_false_for_unauthenticated():
     ]
     for perm in perms:
         assert perm.has_permission(request, None) is False
+
+
+# --- IsVendorOwner ---
+
+def test_is_vendor_owner_true_when_user_matches():
+    request = Mock()
+    request.user = Mock()
+    request.user.id = 1
+    vendor = Mock()
+    vendor.user_id = 1
+    perm = IsVendorOwner()
+    assert perm.has_object_permission(request, None, vendor) is True
+
+
+def test_is_vendor_owner_false_when_user_does_not_match():
+    request = Mock()
+    request.user = Mock()
+    request.user.id = 1
+    vendor = Mock()
+    vendor.user_id = 2
+    perm = IsVendorOwner()
+    assert perm.has_object_permission(request, None, vendor) is False
