Now I have all the context needed. Let me generate the section content for `section-04-otp-send`.

# Section 04: OTP Send

## Overview

This section implements the `POST /api/v1/auth/send-otp/` endpoint — the first step in the phone-based authentication flow. When a user submits their phone number, this endpoint validates the format, enforces rate limiting, generates a 6-digit OTP, stores an HMAC-SHA256 hash of it, and dispatches an async Celery task to deliver the OTP via SMS.

This section is the integration point between the user models (section-03), the SMS backend system (section-02), and the Celery infrastructure (section-07). All three must be complete before this section can be implemented.

---

## Dependencies

- **section-02-core-app**: Provides `apps.core.sms` (`get_sms_backend()`, `BaseSMSBackend`, `ConsoleSMSBackend`, `MSG91SMSBackend`) and the custom exception handler.
- **section-03-user-models**: Provides the `PhoneOTP` model (in `apps/users/models.py`).
- **section-07-celery-infrastructure**: Provides the Celery app, the `sms` queue, and task routing for `apps.users.tasks.*`.

---

## Files to Create or Modify

| File | Action |
|------|--------|
| `apps/users/views.py` | Add `SendOTPView` |
| `apps/users/serializers.py` | Add `SendOTPSerializer` |
| `apps/users/tasks.py` | Add `send_otp_sms` Celery task and `purge_expired_otps` task |
| `apps/users/urls.py` | Wire `send-otp/` URL |
| `config/urls.py` | Include `apps.users.urls` at `/api/v1/auth/` (may already exist from section-01) |
| `apps/users/tests/test_otp_send.py` | All tests for this section |
| `apps/users/tests/factories.py` | `PhoneOTPFactory` (may already have `UserFactory` from section-03) |

---

## Tests First

File: `apps/users/tests/test_otp_send.py`

Testing stack: `pytest-django`, `factory_boy`, `unittest.mock`. All DB-touching tests use `@pytest.mark.django_db`. Mock `send_otp_sms.delay` with `unittest.mock.patch` so tests do not require a live Celery worker.

### OTP Record Creation

```python
def test_send_otp_creates_phone_otp_record(client):
    """POST with valid phone creates exactly one PhoneOTP record."""

def test_send_otp_stores_hmac_hash_not_raw_otp(client):
    """The otp_hash field is a 64-character hex string (HMAC-SHA256), not a 6-digit OTP."""

def test_send_otp_returns_200_with_message(client):
    """Response is 200 with body {"message": "OTP sent"}."""

def test_send_otp_invalid_phone_no_prefix_returns_400(client):
    """Phone without +91 prefix (e.g. "9876543210") returns 400."""

def test_send_otp_invalid_phone_letters_returns_400(client):
    """Phone with non-digit characters after +91 returns 400."""

def test_send_otp_invalid_phone_too_short_returns_400(client):
    """Phone with fewer than 10 digits after +91 returns 400."""

def test_send_otp_invalid_phone_too_long_returns_400(client):
    """Phone with more than 10 digits after +91 returns 400."""
```

### Celery Task Dispatch

```python
def test_send_otp_dispatches_celery_task(client, mocker):
    """send_otp_sms.delay() is called once with the phone and the plaintext OTP."""

def test_send_otp_returns_200_before_sms_delivered(client, mocker):
    """Response is 200 even when the SMS backend raises an exception (async delivery)."""
```

### Rate Limiting

```python
def test_send_otp_rate_limit_blocks_4th_request(client):
    """4th POST with the same phone within 10 minutes returns 429."""

def test_send_otp_rate_limit_different_phones_independent(client):
    """Rate limit does not bleed across different phone numbers."""

def test_send_otp_rate_limit_resets_after_window(client, freezer):
    """A request after the 10-minute window succeeds even if 3 were sent before (use freezegun)."""
```

### HMAC Correctness

```python
def test_send_otp_hmac_is_keyed_with_secret(client, settings):
    """otp_hash cannot be reproduced without OTP_HMAC_SECRET — verify by recomputing."""
```

### `send_otp_sms` Celery Task

```python
def test_send_otp_sms_task_calls_backend_send(mocker):
    """send_otp_sms(phone, otp) calls get_sms_backend().send(phone, otp)."""

def test_send_otp_sms_task_retries_on_exception(mocker):
    """When backend.send raises, send_otp_sms retries (max_retries=3)."""

def test_send_otp_sms_task_is_registered():
    """send_otp_sms is registered in the Celery app task registry."""
```

---

## Implementation Details

### `SendOTPSerializer` — `apps/users/serializers.py`

Validates the `phone` field:

- Required, string
- Must match `^\+91[6-9]\d{9}$` — the `+91` country code followed by an Indian mobile number (starting digit 6, 7, 8, or 9, then 9 more digits). This is the Indian mobile number format for MVP.
- Returns `ValidationError` on mismatch; the custom exception handler (section-02) will format it as `{"error": "validation_error", "detail": "..."}`.

Stub:

```python
class SendOTPSerializer(serializers.Serializer):
    """Validates an Indian mobile phone number in +91XXXXXXXXXX format."""
    phone = serializers.CharField(max_length=13)

    def validate_phone(self, value):
        """Raise ValidationError if value does not match ^\+91[6-9]\d{9}$."""
```

### `SendOTPView` — `apps/users/views.py`

A DRF `APIView` with `permission_classes = [AllowAny]` (overrides the global `IsAuthenticated` default).

Decorated with `@ratelimit(key='post:phone', rate='3/10m', method='POST', block=True)` from `django-ratelimit`. The `key='post:phone'` means the rate limit bucket is keyed on the `phone` field from the POST body — not the client IP. This is essential for India where carrier-grade NAT (CGNAT) is pervasive; IP-based rate limiting would bucket thousands of users together under the same exit IP.

When the rate limit is exceeded, `django-ratelimit` raises `django.core.exceptions.PermissionDenied` with a specific attribute. Override `handle_exception` or use `django-ratelimit`'s `was_limited` function to return a 429 response rather than a 403.

View logic, step by step:

1. Deserialize and validate with `SendOTPSerializer`. Return 400 on validation failure.
2. Extract `phone` from validated data.
3. Generate OTP: `otp = "%06d" % secrets.randbelow(1_000_000)`.
4. Compute hash: `hmac.new(key, msg, digestmod).hexdigest()` where key = `settings.OTP_HMAC_SECRET.encode()` and msg = `f"{phone}:{otp}".encode()`, digestmod = `hashlib.sha256`. Result is 64 hex characters.
5. Create `PhoneOTP(phone=phone, otp_hash=otp_hash)` and save.
6. Dispatch: `send_otp_sms.delay(phone, otp)`.
7. Return `Response({"message": "OTP sent"}, status=200)`.

Stub:

```python
class SendOTPView(APIView):
    """
    POST /api/v1/auth/send-otp/

    Accepts {"phone": "+91XXXXXXXXXX"}, generates a 6-digit OTP, stores its
    HMAC-SHA256 hash in PhoneOTP, and dispatches send_otp_sms to the sms queue.
    Returns {"message": "OTP sent"} immediately (delivery is async).

    Rate limited: 3 requests per phone per 10 minutes.
    """
    permission_classes = [AllowAny]

    @method_decorator(ratelimit(key='post:phone', rate='3/10m', method='POST', block=True))
    def post(self, request, *args, **kwargs):
        ...
```

### OTP HMAC Computation

The HMAC inputs and key come from settings. Add to `base.py`:

```python
OTP_HMAC_SECRET = env("OTP_HMAC_SECRET")  # arbitrary secret, min 32 chars recommended
```

Add to `.env.example`:

```
OTP_HMAC_SECRET=replace-with-a-random-32-plus-char-secret
```

Computation pattern (do not use `hashlib.sha256` alone — that is not HMAC):

```python
import hmac as hmac_module
import hashlib

digest = hmac_module.new(
    settings.OTP_HMAC_SECRET.encode(),
    f"{phone}:{otp}".encode(),
    hashlib.sha256
).hexdigest()
```

This produces a 64-character lowercase hex string. Store this in `PhoneOTP.otp_hash`.

### `send_otp_sms` Celery Task — `apps/users/tasks.py`

Defined with `@shared_task(bind=True, max_retries=3)`. Uses `self.retry(exc=exc, countdown=60 * 2**self.request.retries)` in the exception handler for exponential backoff: 60s on first retry, 120s on second, 240s on third. After all retries are exhausted, log at ERROR level.

The task calls `get_sms_backend().send(phone, otp)` — it does not import a backend directly. The `SMS_BACKEND` setting controls which backend runs without touching the task code.

Stub:

```python
@shared_task(bind=True, max_retries=3)
def send_otp_sms(self, phone: str, otp: str) -> None:
    """
    Deliver the OTP via the configured SMS backend.

    Retries up to 3 times with exponential backoff (60s, 120s, 240s).
    Routed to the 'sms' queue via CELERY_TASK_ROUTES.
    Plaintext OTP exists only in Redis (the broker) transiently.
    """
```

Note: the plaintext OTP travels through Redis as a Celery task argument. `CELERY_TASK_IGNORE_RESULT = True` (set in section-07) prevents result storage, limiting exposure. In production, the Redis broker should use ACLs and TLS.

### `purge_expired_otps` Celery Task — `apps/users/tasks.py`

A simple periodic task (Beat schedule defined in section-07):

```python
@shared_task
def purge_expired_otps() -> None:
    """
    Delete PhoneOTP records older than 7 days.
    Scheduled daily at 02:00 IST via Celery Beat.
    """
```

Implementation deletes `PhoneOTP.objects.filter(created_at__lt=now() - timedelta(days=7))`.

### URL Wiring — `apps/users/urls.py`

```python
from django.urls import path
from .views import SendOTPView

urlpatterns = [
    path("send-otp/", SendOTPView.as_view(), name="send-otp"),
    # verify-otp/ added in section-05
    # logout/ added in section-05
    # switch-community/ added in section-06
]
```

The root `config/urls.py` includes this at `api/v1/auth/`:

```python
path("api/v1/auth/", include("apps.users.urls")),
```

This is expected to already exist from section-01. Verify it is present; add it if the section-01 implementer did not include it.

### Rate Limit 429 Response

`django-ratelimit` with `block=True` raises `Ratelimited` (a subclass of `PermissionDenied`) when the limit is exceeded. The default DRF exception handler converts `PermissionDenied` to 403. Override this in `SendOTPView` to return 429 instead, or configure the custom exception handler (section-02) to handle the `Ratelimited` exception type specifically and return 429. The preferred approach is to handle it in the exception handler so all rate-limited views behave consistently:

```python
# In apps/core/exceptions.py, inside custom_exception_handler:
from django_ratelimit.exceptions import Ratelimited

if isinstance(exc, Ratelimited):
    return Response(
        {"error": "rate_limited", "detail": "Too many requests. Please try again later."},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
```

If the custom exception handler was already implemented in section-02 without this case, add the `Ratelimited` handling now.

---

## Required Settings

Ensure `base.py` has the following (section-01 should have established the base; add any missing items):

```python
OTP_HMAC_SECRET = env("OTP_HMAC_SECRET")
```

Ensure `test.py` (or `base.py` via `env.str(..., default=...)`) provides a value for `OTP_HMAC_SECRET` so tests do not fail on missing env var.

The `CACHES` setting must use Redis (established in section-01/02) so that `django-ratelimit` shares state across processes. `LocMemCache` will make rate limiting non-functional under multiple gunicorn workers.

---

## Security Notes

- **Rate limit key = phone, not IP**: CGNAT means many Indian users share a single public IP. IP-based rate limiting would block unrelated users. Always key on the phone number from the POST body.
- **HMAC over plain hash**: With only 1,000,000 possible OTPs, a plain SHA-256 of the OTP is brute-forceable offline if the database is leaked. HMAC-SHA256 with a server-side secret (`OTP_HMAC_SECRET`) prevents this — an attacker with the `phone_otp` table but not the secret cannot crack the OTPs offline.
- **Async delivery, synchronous response**: The view returns 200 before the SMS is delivered. The OTP is valid for 10 minutes, giving Celery time to retry. Users can re-request if delivery fails.
- **Plaintext OTP in Redis**: The OTP briefly exists in Redis as a Celery task argument. `CELERY_TASK_IGNORE_RESULT = True` prevents it from being stored as a task result. Use Redis ACLs and TLS in production.

---

## Acceptance Criteria

An implementation of this section is complete when:

1. `POST /api/v1/auth/send-otp/` with `{"phone": "+919876543210"}` creates one `PhoneOTP` row with a 64-char `otp_hash` and returns `{"message": "OTP sent"}` with HTTP 200.
2. The `otp_hash` in the database is an HMAC-SHA256 digest, not the raw OTP digits.
3. `send_otp_sms.delay(phone, otp)` is called exactly once per successful request.
4. Sending the same phone number 4 times within 10 minutes returns 429 on the 4th request.
5. Two different phone numbers have independent rate limit counters.
6. Invalid phone formats return 400 with the standard `{"error": "validation_error", "detail": "..."}` shape.
7. All tests in `apps/users/tests/test_otp_send.py` pass under `uv run pytest`.