Now I have all the context needed. Let me generate the section content.

# Section 04: Razorpay Webhook Handler

## Overview

This section implements `RazorpayWebhookView` in `apps/payments/views.py` — the Django REST Framework view that receives all Razorpay webhook events, verifies their authenticity, and drives order FSM transitions for `payment.captured` and `payment.failed` events.

**Dependencies (must be completed before this section):**
- `section-01-models`: `Order`, `OrderItem`, `WebhookEvent`, `OrderStatus` FSM choices
- `section-03-razorpay-services`: `create_route_transfer()`, `release_transfer_hold()`, and the shared Razorpay client

**Blocks:**
- `section-08-vendor-admin-endpoints` (full order lifecycle tests reference webhook-set fields)

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `apps/payments/views.py` | Create — `RazorpayWebhookView` |
| `apps/payments/urls.py` | Create — URL route for the webhook endpoint |
| `apps/payments/tests/test_webhook.py` | Create — all webhook handler tests |
| `apps/payments/tests/conftest.py` | Create — webhook-specific fixtures |

---

## Tests First

File: `/var/www/html/MadGirlfriend/namma-neighbour/apps/payments/tests/test_webhook.py`

Tests use `pytest-django`, `factory_boy` factories from `section-01-models`, and `unittest.mock.patch`. Razorpay signature calls are mocked so no real HTTP calls occur. Celery tasks run synchronously via `CELERY_TASK_ALWAYS_EAGER = True` in test settings.

### Test stubs

```python
# apps/payments/tests/test_webhook.py

import json
import pytest
from unittest.mock import patch, MagicMock
from django.urls import reverse
from freezegun import freeze_time


WEBHOOK_URL = "/api/v1/payments/webhook/"


@pytest.fixture
def valid_payment_captured_payload(order_payment_pending):
    """Build a realistic payment.captured webhook body referencing the test order."""
    ...


@pytest.fixture
def webhook_headers_valid(valid_payment_captured_payload, settings):
    """Return headers dict with a mocked-valid X-Razorpay-Signature."""
    ...


def test_valid_signature_payment_captured_transitions_order_to_confirmed(
    client, order_payment_pending, valid_payment_captured_payload, webhook_headers_valid
):
    """Valid signature + payment.captured → order status becomes CONFIRMED."""
    ...


def test_invalid_signature_returns_400(client, valid_payment_captured_payload):
    """Tampered or missing correct signature → HTTP 400."""
    ...


def test_missing_signature_header_returns_400(client, valid_payment_captured_payload):
    """No X-Razorpay-Signature header → HTTP 400."""
    ...


def test_duplicate_event_id_returns_200_no_double_processing(
    client, order_payment_pending, valid_payment_captured_payload, webhook_headers_valid
):
    """Duplicate event_id (WebhookEvent already exists) → HTTP 200, order not re-processed."""
    ...


def test_unknown_reference_id_returns_200(client, webhook_headers_valid):
    """payment.captured with reference_id that matches no Order → logs, returns HTTP 200."""
    ...


def test_payment_captured_not_in_payment_pending_returns_200_no_state_change(
    client, order_confirmed, webhook_headers_valid
):
    """payment.captured for order already CONFIRMED → HTTP 200, status unchanged."""
    ...


def test_payment_captured_stores_payment_id_before_confirm(
    client, order_payment_pending, valid_payment_captured_payload, webhook_headers_valid
):
    """razorpay_payment_id is persisted on the order before confirm_payment() FSM transition."""
    ...


def test_payment_captured_calls_create_route_transfer(
    client, order_payment_pending, valid_payment_captured_payload, webhook_headers_valid
):
    """create_route_transfer() is called with the correct order after payment capture."""
    ...


@freeze_time("2026-04-02 10:00:00")
def test_payment_captured_sets_hold_release_at_24h_from_now(
    client, order_payment_pending, valid_payment_captured_payload, webhook_headers_valid
):
    """hold_release_at is set to now + 24h (UTC-aware) after payment.captured."""
    ...


def test_payment_captured_transfer_failure_order_still_confirmed(
    client, order_payment_pending, valid_payment_captured_payload, webhook_headers_valid
):
    """create_route_transfer returns None → order is still CONFIRMED, razorpay_transfer_id=None."""
    ...


def test_payment_failed_transitions_order_to_cancelled(
    client, order_payment_pending, webhook_headers_valid
):
    """payment.failed → order transitions to CANCELLED via cancel() FSM method."""
    ...


def test_payment_failed_restores_daily_inventory(
    client, order_payment_pending, webhook_headers_valid
):
    """cancel() called during payment.failed restores DailyInventory qty_ordered for each item."""
    ...


def test_unknown_event_type_returns_200(client, webhook_headers_valid):
    """Unrecognised event type → logged and returns HTTP 200, no exception."""
    ...


def test_reference_id_extracted_from_correct_path(
    client, order_payment_pending, webhook_headers_valid
):
    """reference_id read from payload['payload']['payment']['entity']['notes']['reference_id']."""
    ...


def test_handler_exception_caught_returns_200(
    client, order_payment_pending, valid_payment_captured_payload, webhook_headers_valid
):
    """If handler raises an exception internally, view still returns HTTP 200."""
    ...
```

---

## Implementation

### Background

Razorpay cannot authenticate itself via tokens; it authenticates via an HMAC-SHA256 signature over the raw request body. Because of this:

- The view must set `authentication_classes = []` and `permission_classes = [AllowAny]`. This prevents DRF's `SessionAuthentication` from enforcing CSRF (which would reject Razorpay's POST), and is the correct pattern for externally-called webhook endpoints.
- The raw `request.body` (bytes) must be read **before** any JSON parsing. Once you call `request.data` in DRF, the body stream may be consumed — always use `request.body` in this view.

### Idempotency design

The `WebhookEvent.event_id` unique constraint (populated from the `X-Razorpay-Event-ID` header) is the primary guard against duplicate deliveries. The secondary guard is the `order.status != PAYMENT_PENDING` check inside each handler, which protects against edge cases where the unique constraint could be bypassed (e.g., a missing event ID header). Both layers are required per the plan's belt-and-suspenders requirement.

### View: `RazorpayWebhookView`

File: `apps/payments/views.py`

```python
# apps/payments/views.py

import json
import logging
from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
import razorpay

from apps.orders.models import Order, OrderStatus
from apps.payments.models import WebhookEvent
from apps.payments.services.razorpay import create_route_transfer

logger = logging.getLogger(__name__)


class RazorpayWebhookView(APIView):
    """
    Receives Razorpay webhook events.

    No authentication — Razorpay cannot provide tokens. Verified by HMAC signature.
    authentication_classes and permission_classes are explicitly set to bypass DRF
    session auth (which enforces CSRF) and allow unauthenticated POST requests.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        """
        Main entry point. Steps:
        1. Read raw body + signature header before any JSON parsing.
        2. Verify HMAC signature; return 400 on failure.
        3. Parse JSON.
        4. Extract event_id from X-Razorpay-Event-ID header.
        5. Try to insert WebhookEvent; on IntegrityError (duplicate), return 200 early.
        6. Route to _handle_payment_captured or _handle_payment_failed; log others.
        7. Wrap handler in try/except; always return 200.
        """
        ...

    def _verify_signature(self, raw_body: bytes, signature: str) -> bool:
        """
        Call client.utility.verify_webhook_signature(body_str, signature, secret).
        Return False on SignatureVerificationError.
        """
        ...

    def _handle_payment_captured(self, payload: dict) -> None:
        """
        Steps:
        1. Extract reference_id from payload['payload']['payment']['entity']['notes']['reference_id'].
        2. Find Order by razorpay_idempotency_key = UUID(reference_id); log + return if not found.
        3. Idempotency check: if order.status != PAYMENT_PENDING, return (already handled).
        4. Set order.razorpay_payment_id and save immediately (race guard before FSM transition).
        5. Call order.confirm_payment() then order.save() (transitions to CONFIRMED).
           The confirm_payment() transition body schedules release_payment_hold task at now+24h.
        6. Set order.hold_release_at = timezone.now() + timedelta(hours=24), save.
        7. Call create_route_transfer(order); store result in order.razorpay_transfer_id.
           If result is None, log "TRANSFER_CREATION_FAILED" alert but continue.
        8. Call notification stubs.
        """
        ...

    def _handle_payment_failed(self, payload: dict) -> None:
        """
        Steps:
        1. Extract reference_id; find order.
        2. If order.status == PAYMENT_PENDING: call order.cancel(), save.
           The cancel() transition body restores DailyInventory via F() per item.
        3. Call notification stub (notify_buyer_order_cancelled).
        """
        ...
```

### URL configuration

File: `apps/payments/urls.py`

```python
# apps/payments/urls.py

from django.urls import path
from apps.payments.views import RazorpayWebhookView

urlpatterns = [
    path("webhook/", RazorpayWebhookView.as_view(), name="razorpay-webhook"),
]
```

Wire this into the project-level `urls.py` at `api/v1/payments/`.

### Settings required

The following settings must be present (typically sourced from environment variables):

- `RAZORPAY_KEY_ID` — used by the shared Razorpay client in `section-03-razorpay-services`
- `RAZORPAY_KEY_SECRET` — used by the shared client
- `RAZORPAY_WEBHOOK_SECRET` — used **only** in `RazorpayWebhookView._verify_signature()`; this is a separate secret configured in the Razorpay dashboard for the webhook endpoint, distinct from the API key secret

---

## Processing Logic in Detail

### Signature verification

Before any JSON parsing or DB writes, verify:

```
client.utility.verify_webhook_signature(
    raw_body.decode("utf-8"),
    signature,
    settings.RAZORPAY_WEBHOOK_SECRET
)
```

The Razorpay SDK raises `razorpay.errors.SignatureVerificationError` on mismatch. Catch this and return HTTP 400. Also return 400 if the `X-Razorpay-Signature` header is absent entirely (the header is accessed as `request.META.get("HTTP_X_RAZORPAY_SIGNATURE", "")`).

### Idempotency check sequence

```
event_id = request.META.get("HTTP_X_RAZORPAY_EVENT_ID", "")

with transaction.atomic():
    try:
        WebhookEvent.objects.create(
            event_id=event_id,
            event_type=event["event"],
            payload=payload,
        )
    except IntegrityError:
        return Response(status=200)  # already processed
```

The `WebhookEvent.event_id` field has `unique=True`. On a duplicate delivery, the `IntegrityError` is caught and the view returns 200 immediately, preventing any re-processing.

### Extracting `reference_id` from `payment.captured`

When a Payment Link is created with `reference_id` set (as done by `create_payment_link()` in section 03), Razorpay includes that value under:

```
payload["payload"]["payment"]["entity"]["notes"]["reference_id"]
```

This value is `str(order.razorpay_idempotency_key)` — a UUID string. Look up the order via:

```python
Order.objects.get(razorpay_idempotency_key=UUID(reference_id))
```

### Race condition: webhook vs. `cancel_unpaid_order` task

The 30-minute auto-cancel Celery task (`cancel_unpaid_order`, section 05) checks `order.razorpay_payment_id`. The correct sequence in `_handle_payment_captured` is:

1. Store `razorpay_payment_id` and save immediately.
2. Then call `order.confirm_payment()`.

This ordering ensures that if the Celery task fires in the narrow window between Razorpay sending the webhook and the webhook handler completing the FSM transition, the task will see a non-blank `razorpay_payment_id` and abort silently, rather than cancelling a paid order.

### Transfer failure handling

`create_route_transfer()` returns `None` on failure (it does not re-raise). After calling it:

```python
transfer_id = create_route_transfer(order)
order.razorpay_transfer_id = transfer_id or ""
order.save(update_fields=["razorpay_transfer_id"])
if not transfer_id:
    logger.error("TRANSFER_CREATION_FAILED order_id=%s", order.pk)
```

The order remains CONFIRMED. Operations staff must handle the manual payout (they are alerted via the log entry and any log aggregation tooling). Do not cancel the order — payment was already captured.

### Always return HTTP 200

Wrap the handler dispatch in a broad try/except:

```python
try:
    if event_type == "payment.captured":
        self._handle_payment_captured(payload)
    elif event_type == "payment.failed":
        self._handle_payment_failed(payload)
    else:
        logger.info("Unhandled Razorpay event type: %s", event_type)
except Exception:
    logger.exception("Webhook handler raised for event_id=%s", event_id)

return Response(status=200)
```

Returning 200 on handler exceptions prevents Razorpay from retrying the event and creating duplicate processing attempts. Transient failures (e.g., DB timeout) should be handled by making the handler idempotent rather than relying on Razorpay retries.

---

## Notification Stubs Called

The following notification stub tasks (defined in `section-09-admin-notifications`) must be called from this handler:

- After `confirm_payment()`: `notify_buyer_payment_confirmed.delay(order.pk)` and `notify_vendor_order_received.delay(order.pk)`
- After `cancel()` in `_handle_payment_failed`: `notify_buyer_order_cancelled.delay(order.pk)`

These tasks are no-ops at this stage. Import them from `apps.notifications.tasks`.

---

## Key Invariants for This Section

- The view must never return 4xx/5xx for anything other than a failed signature verification. Razorpay treats 4xx/5xx as failed delivery and retries — all errors after successful signature verification must return 200.
- `request.body` must be read before `request.data` or any DRF parsing. Assign to a local variable immediately: `raw_body = request.body`.
- The `authentication_classes = []` + `permission_classes = [AllowAny]` combination is explicitly required to prevent CSRF enforcement and token validation on this public endpoint.
- `order.razorpay_payment_id` must be saved to the DB before calling `order.confirm_payment()`. This is the race guard that prevents `cancel_unpaid_order` from cancelling a paid order.
- `hold_release_at` is set explicitly in the view after `confirm_payment()`, in addition to the Celery task ETA set inside the transition body. Both record the same point in time; `hold_release_at` is the human-readable audit field on the Order record.