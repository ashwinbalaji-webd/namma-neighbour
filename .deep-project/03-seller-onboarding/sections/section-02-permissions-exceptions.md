I now have all the context needed to write the section. Let me produce the complete, self-contained section content.

# Section 02: Permissions and Custom Exceptions

## Overview

This section adds two new building blocks to `apps/core/` that every other section in split 03 depends on:

1. `IsVendorOwner` — an object-level DRF permission that ensures the authenticated user owns the `Vendor` they are operating on.
2. A custom exception hierarchy for third-party API failures: `ExternalAPIError → TransientAPIError / PermanentAPIError → RazorpayError / FSSAIVerificationError`.

**Depends on:** `section-01-app-scaffold-models` (the `Vendor` model must exist; `apps/core/` must be set up from split 01 foundation).

**Blocks:** `section-03-fssai-service`, `section-04-razorpay-service`, `section-06-serializers`, `section-07-api-views-registration`, `section-08-api-views-admin-workflow`.

**Parallelizable with:** `section-05-s3-document-upload`, `section-11-django-admin`, `section-13-env-settings`.

---

## Background

`apps/core/` was created in split 01 (`section-02-core-app`). It already contains:
- `apps/core/permissions.py` — four JWT-role-based permission classes (`IsResidentOfCommunity`, `IsVendorOfCommunity`, `IsCommunityAdmin`, `IsPlatformAdmin`).
- `apps/core/exceptions.py` — `custom_exception_handler` that normalizes DRF errors to `{"error": ..., "detail": ...}`.

This section **extends** both files. It does not rewrite them. The existing `custom_exception_handler` already handles DRF's built-in exceptions; the new exception classes are DRF `APIException` subclasses that will automatically be serialized correctly by it.

---

## Files to Create or Modify

```
apps/core/
├── permissions.py      # ADD IsVendorOwner class (append to existing file)
└── exceptions.py       # ADD ExternalAPIError hierarchy (append to existing file)

apps/core/tests/
├── test_permissions.py # ADD IsVendorOwner tests (append to existing file)
└── test_exceptions.py  # ADD ExternalAPIError hierarchy tests (append to existing file)
```

---

## Tests First

All tests use `pytest-django`. DB tests are decorated with `@pytest.mark.django_db`. Use `APIClient.force_authenticate(user=user)` for auth. Use the `VendorFactory` from `apps/vendors/tests/factories.py` (created in section 01).

### Append to `apps/core/tests/test_permissions.py`

**IsVendorOwner — unit tests (no DB needed):**

```python
# Test: IsVendorOwner.has_object_permission returns True when request.user == vendor.user
# Test: IsVendorOwner.has_object_permission returns False when request.user != vendor.user
```

For both tests, construct a mock `request` object with `request.user` set. Pass a `Vendor` instance (can be a plain mock with `user` attribute set) as the `obj` argument. No database access is required.

**IsVendorOwner — integration test (DB required):**

```python
# Test: Document upload endpoint returns 403 when authenticated user does not own the vendor
```

Use `APIClient`, create two users (owner and other), create a `Vendor` for owner. Authenticate as `other` and POST to `/api/v1/vendors/{vendor_id}/documents/`. Assert HTTP 403.

Note: this integration test depends on section 07 (the document upload view) being implemented. If running section 02 in isolation, you can defer this third test or stub the view at a minimum route. Mark it with `@pytest.mark.integration` if you need to skip it during isolated section development.

### Append to `apps/core/tests/test_exceptions.py`

**ExternalAPIError hierarchy — no DB needed:**

```python
# Test: ExternalAPIError serializes to {"error": ..., "detail": ...} via custom_exception_handler
# Test: TransientAPIError is a subclass of ExternalAPIError
# Test: FSSAIVerificationError returns HTTP 400
# Test: RazorpayError returns HTTP 402
```

For the serialization test: instantiate `ExternalAPIError("upstream failure")`, pass it directly to `custom_exception_handler(exc, context={})`, and assert the response JSON matches `{"error": ..., "detail": ...}` with status 503.

For the subclass test: use `assert issubclass(TransientAPIError, ExternalAPIError)`.

For the HTTP status tests: instantiate each exception class and assert `.status_code` equals the expected value (400 for `FSSAIVerificationError`, 402 for `RazorpayError`).

---

## Implementation

### 2.1 `IsVendorOwner` — append to `apps/core/permissions.py`

```python
class IsVendorOwner(BasePermission):
    """Object-level permission: request.user must be the Vendor's owning user.

    Views must call self.check_object_permissions(request, vendor) explicitly
    after fetching the Vendor by vendor_id. To avoid accidentally omitting
    this call, prefer the get_vendor_or_404() helper defined in
    apps/vendors/views.py (section 07).
    """

    def has_object_permission(self, request, view, obj) -> bool:
        """Return True if obj.user_id matches request.user.id."""
```

`obj` will always be a `Vendor` instance. Compare `obj.user_id` to `request.user.id` (integer comparison via `_id` suffix avoids an extra DB query vs. `obj.user == request.user`).

This permission is **object-level only** — it does not override `has_permission`. Views using it should still require `IsAuthenticated` at the `permission_classes` level so that unauthenticated requests are rejected before object-level checks run.

### 2.2 Exception Hierarchy — append to `apps/core/exceptions.py`

The full hierarchy to implement:

```
ExternalAPIError(APIException)      HTTP 503  — base for all third-party API failures
├── TransientAPIError               HTTP 503  — retriable: 5xx, timeout, connection error
└── PermanentAPIError               HTTP 503  — non-retriable: 400/404 from third-party

RazorpayError(PermanentAPIError)    HTTP 402  — Razorpay business logic error
FSSAIVerificationError(PermanentAPIError)  HTTP 400  — FSSAI permanent failure
```

Stubs with docstrings:

```python
from rest_framework.exceptions import APIException


class ExternalAPIError(APIException):
    """Base exception for all third-party API failures.

    HTTP 503. Signals that an upstream service call failed. Subclass this
    rather than raising it directly — use TransientAPIError or PermanentAPIError.
    """
    status_code = 503
    default_detail = "An upstream service call failed."
    default_code = "external_api_error"


class TransientAPIError(ExternalAPIError):
    """Raised when a third-party API failure is temporary and retrying may succeed.

    Examples: HTTP 5xx responses, requests.Timeout, requests.ConnectionError,
    HTTP 429 rate-limit. Used in Celery autoretry_for tuples.
    """
    default_code = "transient_api_error"


class PermanentAPIError(ExternalAPIError):
    """Raised when a third-party API failure is definitively non-retriable.

    Examples: HTTP 400 (invalid input to external API), HTTP 404 (resource
    not found at external API). Celery tasks should catch this and NOT re-raise
    it to prevent retry loops.
    """
    default_code = "permanent_api_error"


class RazorpayError(PermanentAPIError):
    """Razorpay-specific business logic error.

    Examples: duplicate reference_id, invalid bank account details.
    HTTP 402 Payment Required — signals a payment processing issue.
    """
    status_code = 402
    default_detail = "A Razorpay API error occurred."
    default_code = "razorpay_error"


class FSSAIVerificationError(PermanentAPIError):
    """FSSAI license verification permanent failure.

    Examples: invalid license format (HTTP 400 from Surepass),
    license not found (HTTP 404 from Surepass).
    HTTP 400 — the vendor's submitted data is invalid.
    """
    status_code = 400
    default_detail = "FSSAI license verification failed."
    default_code = "fssai_verification_error"
```

**Important design notes:**

- All five classes extend DRF's `APIException`. This means the existing `custom_exception_handler` in `apps/core/exceptions.py` (from split 01) will automatically render them as `{"error": ..., "detail": ...}` JSON responses — no additional handler changes needed.
- `TransientAPIError` and `PermanentAPIError` do not override `status_code` — they inherit 503 from `ExternalAPIError`. Only `RazorpayError` (402) and `FSSAIVerificationError` (400) change the status code because they represent errors that mean something specific to the API caller.
- `TransientAPIError` is listed in `autoretry_for` tuples in Celery tasks (sections 09). Services (`fssai.py`, `razorpay.py`) raise it for 5xx/timeout/429; Celery retries automatically.
- `PermanentAPIError` (and its subclasses) are caught in Celery tasks and **not** re-raised, preventing infinite retry loops.
- Celery `autoretry_for` should include both `TransientAPIError` and `requests.Timeout` / `requests.ConnectionError` directly, since `requests` exceptions are not DRF exceptions and won't be caught by DRF's handler.

---

## Settings

No settings changes are needed for this section. The `custom_exception_handler` is already registered in `REST_FRAMEWORK['EXCEPTION_HANDLER']` in `config/settings/base.py` from split 01.

---

## Checklist

- [x] `apps/core/permissions.py`: append `IsVendorOwner` with `has_object_permission` comparing `obj.user_id` to `request.user.id`
- [x] `apps/core/exceptions.py`: append `ExternalAPIError`, `TransientAPIError`, `PermanentAPIError`, `RazorpayError`, `FSSAIVerificationError`
- [x] `apps/core/tests/test_permissions.py`: unit tests for `has_object_permission` True/False; integration test `test_document_upload_returns_403_for_non_owner` added as `@pytest.mark.skip` (deferred to section-07)
- [x] `apps/core/tests/test_exceptions.py`: serialization test with explicit `error`/`detail` value assertions; subclass tests for all hierarchy levels; HTTP status code assertions for `FSSAIVerificationError` and `RazorpayError`
- [x] Verify `uv run pytest apps/core/tests/test_permissions.py apps/core/tests/test_exceptions.py` passes (26 passed, 1 skipped)

## Actual Implementation Notes

**Deviations from plan:**
- `APIException` import was already present at the top of `exceptions.py` (from split 01); no duplicate import needed.
- `custom_exception_handler` fallback changed from `'error'` to `getattr(exc, 'default_code', 'error')` so that custom APIException subclasses emit their `default_code` in the `error` field.
- Integration test for 403 on document upload deferred with `@pytest.mark.skip(reason="Deferred: depends on section-07 document upload view")`.

**Extra tests added (not in original plan):**
- `test_permanent_api_error_is_subclass_of_external`
- `test_razorpay_error_is_subclass_of_permanent`
- `test_fssai_error_is_subclass_of_permanent`

**Final test count:** 26 passed, 1 skipped (test_document_upload_returns_403_for_non_owner)