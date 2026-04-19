Now I have everything needed to write the complete section. Here is the output:

# section-10-razorpay-webhook

## Overview

This section implements the `RazorpayWebhookView` — an unauthenticated HTTP endpoint that receives Razorpay account lifecycle events, verifies the request signature, and updates vendor records accordingly.

**This section is in the `03-seller-onboarding` split.**

**Dependencies (must be complete before starting this section):**

- `section-01-app-scaffold-models`: The `Vendor` model must exist with `razorpay_account_id`, `razorpay_account_status`, and `bank_account_verified` fields.
- `section-04-razorpay-service`: The Razorpay service layer and `RAZORPAY_WEBHOOK_SECRET` setting must be wired up (see `section-13-env-settings`).

**Blocks:** `section-12-url-configuration` (the webhook URL must be registered before URL configuration is complete).

**Parallelizable with:** `section-07-api-views-registration`, `section-08-api-views-admin-workflow`, `section-09-celery-tasks`, `section-11-django-admin`.

---

## Tests First

Test file: `apps/vendors/tests/test_webhooks.py` (or `apps/core/tests/test_webhooks.py` — place alongside the view file).

All tests use `pytest-django` and `APIClient`. No authentication is set up for the client — the endpoint is unauthenticated by design.

### Signature Verification Tests

```python
class TestRazorpayWebhookSignatureVerification:
    """POST /api/v1/webhooks/razorpay/"""

    def test_missing_signature_header_returns_400(self, client):
        """Request with no X-Razorpay-Signature header → HTTP 400."""

    def test_incorrect_signature_returns_400(self, client, vendor):
        """Request with a syntactically valid but wrong HMAC value → HTTP 400."""

    def test_valid_signature_returns_200(self, client, vendor):
        """Request with a correctly computed HMAC-SHA256 signature → HTTP 200."""

    def test_uses_hmac_compare_digest_not_equality(self, client):
        """
        Verify that the view imports and calls hmac.compare_digest rather than ==.
        Inspect the source or mock hmac.compare_digest and assert it was called.
        """
```

### Event Handling Tests

```python
class TestRazorpayWebhookAccountActivated:
    """account.activated event processing."""

    def test_account_activated_sets_razorpay_account_status_activated(self, client, vendor):
        """
        On valid account.activated webhook:
        vendor.razorpay_account_status == 'activated' after the request.
        """

    def test_account_activated_sets_bank_account_verified_true(self, client, vendor):
        """
        On valid account.activated webhook:
        vendor.bank_account_verified == True after the request.
        """

    def test_account_activated_for_unknown_account_id_returns_200(self, client):
        """
        payload.account.entity.id does not match any vendor.razorpay_account_id →
        returns 200 without raising an exception (defensive no-op).
        """

    def test_account_activated_is_idempotent(self, client, vendor):
        """
        Delivering the same account.activated webhook twice does not raise an error.
        Both deliveries return 200 and the vendor fields remain correct.
        """
```

### Helper for building a correctly signed payload

In `conftest.py` or as a test utility:

```python
import hashlib
import hmac
import json

def build_signed_webhook_request(payload_dict, secret):
    """
    Returns (body_bytes, headers_dict) for a valid Razorpay webhook request.
    Compute: hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    Set header X-Razorpay-Signature to that hex digest.
    """
```

---

## Implementation

### File to Create

`apps/core/views_webhooks.py`

The webhook view lives in `apps/core/` (not `apps/vendors/`) so the webhook URL namespace stays separate from vendor-specific routes. Future payment webhooks (split 05) will be added to the same file and namespace without touching the vendors app.

### Imports

```python
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.views import View
from django.http import JsonResponse

from apps.vendors.models import Vendor
```

Use the low-level Django `View` (not DRF `APIView`) because the endpoint must be exempt from DRF's `DEFAULT_AUTHENTICATION_CLASSES` and `DEFAULT_PERMISSION_CLASSES`. DRF authentication middleware must not touch this endpoint.

### View Skeleton

```python
class RazorpayWebhookView(View):
    """
    Unauthenticated webhook receiver for Razorpay account lifecycle events.

    Security: HMAC-SHA256 signature verification using RAZORPAY_WEBHOOK_SECRET.
    Replay protection: NOT implemented for MVP. The account.activated handler is
    idempotent (filter().update()), so replays are harmless for this event.
    TODO (split 05): Add timestamp + event-ID deduplication before handling
    non-idempotent payment events.
    """

    def post(self, request, *args, **kwargs):
        """Verify signature, dispatch to event handler, always return 200 on success."""

    def _verify_signature(self, raw_body: bytes, signature_header: str) -> bool:
        """
        Compute HMAC-SHA256(raw_body, RAZORPAY_WEBHOOK_SECRET).
        Compare with signature_header using hmac.compare_digest (constant-time).
        Returns True if valid, False otherwise.
        """

    def _handle_account_activated(self, payload: dict) -> None:
        """
        Extract account_id from payload['payload']['account']['entity']['id'].
        Atomically set razorpay_account_status='activated' and bank_account_verified=True
        on the matching Vendor record.
        Enqueue SMS notification to vendor.
        Unknown account_id: log a warning, do nothing (no exception raised).
        """
```

### Signature Verification Logic

The raw request body must be used for HMAC computation — not re-serialized JSON, not `request.data`. Access it via `request.body` (Django's raw bytes attribute).

```python
# Pseudocode — do not copy literally; write your own clean implementation
expected = hmac.new(
    settings.RAZORPAY_WEBHOOK_SECRET.encode('utf-8'),
    raw_body,
    hashlib.sha256
).hexdigest()

is_valid = hmac.compare_digest(expected, received_signature)
```

If `X-Razorpay-Signature` header is absent or the digest does not match, return `JsonResponse({'error': 'invalid signature'}, status=400)` immediately without processing the body.

### Event Dispatch

After signature verification, parse the body as JSON and read the `event` field:

```python
event = payload.get('event', '')
if event == 'account.activated':
    self._handle_account_activated(payload)
# Other events: silently ignore and return 200
```

Always return `JsonResponse({'status': 'ok'}, status=200)` for any verified request, regardless of whether the event was recognised.

### account.activated Handler

The nested payload path Razorpay uses is `payload.account.entity.id`. Extract it with safe dictionary traversal:

```python
account_id = payload.get('payload', {}).get('account', {}).get('entity', {}).get('id')
```

Update atomically:

```python
Vendor.objects.filter(razorpay_account_id=account_id).update(
    razorpay_account_status='activated',
    bank_account_verified=True,
)
```

Using `filter().update()` makes the operation idempotent — if the vendor is already activated, the update is a no-op and returns a count of 0 or 1 rows; no exception is raised either way. If `account_id` is `None` or does not match any vendor, the queryset is empty and nothing happens — log a warning but do not raise.

After the update, enqueue an SMS notification to the vendor. The SMS task is defined in the notifications/SMS infrastructure (split 01 foundation). Mock `.delay()` in tests.

### CSRF Exemption

Razorpay cannot send a CSRF token. The view must be exempt from Django's CSRF middleware. Apply `@method_decorator(csrf_exempt, name='dispatch')` on the class, or register the URL with `csrf_exempt()` wrapping at URL configuration time (see `section-12-url-configuration`).

```python
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

@method_decorator(csrf_exempt, name='dispatch')
class RazorpayWebhookView(View):
    ...
```

---

## URL Registration

This section only creates the view file. URL wiring is handled in `section-12-url-configuration`, but the expected shape is documented here for reference:

File to create: `apps/core/urls_webhooks.py`

```python
# apps/core/urls_webhooks.py
from django.urls import path
from apps.core.views_webhooks import RazorpayWebhookView

urlpatterns = [
    path('webhooks/razorpay/', RazorpayWebhookView.as_view(), name='razorpay-webhook'),
]
```

Include in `config/urls.py` at `api/v1/`:

```python
path('api/v1/', include('apps.core.urls_webhooks')),
```

Note: this include has no namespace (unlike the vendors app). Future payment webhook handlers in split 05 will be added to `apps/core/urls_webhooks.py` directly.

---

## Settings Dependency

`settings.RAZORPAY_WEBHOOK_SECRET` must be set. This is configured in `section-13-env-settings`:

```python
# config/settings/base.py
RAZORPAY_WEBHOOK_SECRET = env('RAZORPAY_WEBHOOK_SECRET')
```

The test fixtures should set `settings.RAZORPAY_WEBHOOK_SECRET = 'test-secret'` using `pytest`'s `settings` fixture or `@override_settings`.

---

## Key Design Constraints

| Constraint | Detail |
|------------|--------|
| Unauthenticated endpoint | No `IsAuthenticated` or JWT verification — Razorpay cannot send tokens |
| Constant-time comparison | Always use `hmac.compare_digest`, never `==`, to prevent timing attacks |
| Raw body for HMAC | Use `request.body` (bytes), not re-serialized JSON |
| CSRF exempt | Django's CSRF middleware would reject Razorpay requests — must be exempt |
| filter().update() for idempotency | `account.activated` may be re-delivered; the update must be a no-op on repeat |
| Unknown account_id is silent | If no vendor matches, log a warning and return 200 — do not error |
| No replay protection for MVP | Acceptable because `account.activated` is idempotent; add in split 05 |
| 200 for all valid verified events | Even unrecognised events → 200; Razorpay retries on non-2xx responses |
| Low-level Django View | Not DRF APIView — avoids DRF auth/permission middleware interference |

---

## Relevant Model Fields (from section-01)

The `Vendor` model fields used in this section:

| Field | Type | Notes |
|-------|------|-------|
| `razorpay_account_id` | `CharField(max_length=100, blank=True)` | Set by `create_razorpay_linked_account` task |
| `razorpay_account_status` | `CharField(max_length=20, blank=True)` | Values: `pending`, `under_review`, `activated`, `rejected` |
| `bank_account_verified` | `BooleanField(default=False)` | Set `True` by this webhook handler |