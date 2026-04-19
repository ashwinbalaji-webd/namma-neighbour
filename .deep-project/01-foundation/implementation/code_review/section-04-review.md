# Code Review: Section-04-otp-send

## Summary

Core functionality is correct and security aspects (HMAC, async delivery, rate limiting) work properly. However, there are specification compliance issues and code quality problems that need addressing before merge.

**Verdict: APPROVED WITH CHANGES**

---

## Critical Issues

### 1. Missing Celery Task Retry Test

The plan (line 102-103) specifies a test `test_send_otp_sms_task_retries_on_exception` to verify the task retries on exception with exponential backoff. This test is absent from `test_otp_send.py`.

**Current state**: Only 2 task tests exist (calls backend, is registered)
**Required**: Add retry logic verification

**Why it matters**: The retry mechanism with exponential backoff is a critical requirement for SMS delivery reliability. Lack of test coverage means we can't verify it works.

### 2. Dead Code in views.py

Unused imports and functions indicate incomplete refactoring:
- Line 6: `method_decorator` - imported but never used
- Line 8: `ratelimit` from django_ratelimit.decorators - imported but never used  
- Line 9: `viewsets` from rest_framework - imported but never used
- Line 14: `PermissionDenied` from rest_framework.exceptions - imported but never used
- Lines 21-26: `_get_rate_limit_key` function - defined but never used

**Root cause**: Plan specified `@method_decorator(ratelimit(...))` approach, but implementation switched to manual cache-based rate limiting without cleaning up the old imports.

### 3. Rate Limiting Implementation Deviates from Specification

**Plan specified**:
```python
@method_decorator(ratelimit(key='post:phone', rate='3/10m', method='POST', block=True))
def post(self, request, *args, **kwargs):
```

**Actually implemented** (lines 38-47 in views.py):
```python
attempts = cache.get(cache_key, 0)
if attempts >= 3:
    return Response(..., status=HTTP_429_TOO_MANY_REQUESTS)
cache.set(cache_key, attempts + 1, 600)
```

**Assessment**: The cache-based approach works correctly and produces identical behavior, but violates the specified architecture. The decorator pattern is cleaner and would integrate with the custom exception handler.

---

## Medium Severity Issues

### 1. Rate Limiting Test Fragility

**Line 109-117** (`test_send_otp_rate_limit_different_phones_independent`):
- Does not mock the cache object
- Will use real Redis (or fail if Redis unavailable)
- Test is environment-dependent and non-deterministic

**Line 88-107** (`test_send_otp_rate_limit_blocks_4th_request`):
- Properly mocks cache but only tests mocked behavior
- Doesn't verify real Redis behavior

### 2. Bare Exception Handling

**Line 59 in views.py**:
```python
try:
    send_otp_sms.delay(phone, otp)
except Exception:
    pass
```

Problem: All exceptions silently ignored with no logging. If task dispatch fails, we have no visibility.

**Should be**: Log the exception or catch specific exception types (e.g., `from celery.exceptions import CeleryError`)

---

## Minor Issues

### Test Comment Incomplete

**Line 69-70** in test_otp_send.py:
```python
def test_send_otp_dispatches_celery_task(self, mock_task, client):
    """send_otp_sms.delay() is called once with the phone."""
```

Comment says "called once with the phone" but the test correctly verifies both phone and 6-digit OTP are passed (lines 75-77). Comment should be updated to match actual behavior.

---

## Strengths

1. **HMAC implementation is correct**: Uses constant-time comparison (hmac module), keyed with OTP_HMAC_SECRET
2. **Celery task structure is sound**: Uses shared_task decorator, proper retry logic with exponential backoff
3. **Test coverage is comprehensive**: 7 endpoint tests + 2 task tests, good edge case coverage
4. **Phone validation is strict**: Regex correctly enforces +91 prefix and 10-digit format (6-9 start)
5. **Serializer design is clean**: Validation in `validate_phone`, follows DRF patterns

---

## Required Actions

Before merge:

1. **Add missing Celery task retry test**
   - Test name: `test_send_otp_sms_task_retries_on_exception`
   - Verify task retries with `@patch('apps.users.tasks.send_otp_sms.retry')`
   - Verify exponential backoff calculation

2. **Remove dead code from views.py**
   - Delete unused imports: `method_decorator`, `ratelimit`, `viewsets`, `PermissionDenied`
   - Delete unused function: `_get_rate_limit_key`

3. **Fix rate limiting test**
   - Mock cache in `test_send_otp_rate_limit_different_phones_independent`
   - Or document that test requires Redis available

4. **Add logging to exception handler** (line 59)
   - Import logging
   - Log exceptions when Celery task dispatch fails

5. **Update test comment** (line 70)
   - Change from "called once with the phone" to "called once with phone and OTP"

---

## Specification Compliance

| Requirement | Status | Notes |
|---|---|---|
| SendOTP creates PhoneOTP record | ✓ | Passing test |
| Stores HMAC hash, not raw OTP | ✓ | Passing test |
| Returns 200 with {"message": "OTP sent"} | ✓ | Passing test |
| Phone validation (Indian format) | ✓ | Passing tests (5 phone variants) |
| Rate limiting 3 per 10 minutes | ✓ | Working but using cache instead of decorator |
| Celery async dispatch | ✓ | Task dispatched correctly |
| Task retries with exponential backoff | ⚠ | Code exists but not tested |
| Celery task is registered | ✓ | Passing test |

