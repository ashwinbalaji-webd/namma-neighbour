# Interview Transcript — Section 02

## Item 1: error_map doesn't include custom exceptions (HIGH — AUTO-FIX)
**Applied:** Changed `error_map.get(type(exc), 'error')` to `error_map.get(type(exc), getattr(exc, 'default_code', 'error'))`.
Custom APIException subclasses now emit their `default_code` in the `error` field.

## Item 2: Integration test 403 deferred but not stubbed (HIGH — AUTO-FIX)
**Applied:** Added `@pytest.mark.skip(reason="Deferred: depends on section-07 document upload view")` placeholder test.
Will be fleshed out in section-07.

## Item 3: PermanentAPIError untested (MEDIUM — AUTO-FIX)
**Applied:** Added tests: `test_permanent_api_error_is_subclass_of_external`, `test_razorpay_error_is_subclass_of_permanent`, `test_fssai_error_is_subclass_of_permanent`.

## Item 4: Serialization test doesn't assert detail value (MEDIUM — AUTO-FIX)
**Applied:** Updated `test_external_api_error_serializes_via_custom_handler` to assert `response.data["error"] == "external_api_error"` and `response.data["detail"] == "upstream failure"`.

## Item 5: Mid-module APIException import with noqa (LOW — AUTO-FIX)
**Applied:** Moved `from rest_framework.exceptions import APIException` to the top-level import block.

## Item 6: No unauthenticated edge case for has_object_permission (LOW — KEPT AS-IS)
**Decision:** Docstring already explains that IsAuthenticated must guard the view, preventing unauthenticated requests from reaching object-level checks. Django's AnonymousUser.id is None, so the comparison fails safely.
