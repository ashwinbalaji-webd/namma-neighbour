Now I have all the context needed. Let me generate the section content for `section-03-razorpay-services`.

# Section 03: Razorpay Services

## Overview

This section implements `apps/payments/services/razorpay.py` — the payment gateway integration layer. It provides three functions that wrap the Razorpay Python SDK and handle all direct API communication with Razorpay. This module is consumed by `OrderPlacementService` (section 02), the webhook handler (section 04), FSM transition methods on `Order` (section 01), and the Celery tasks (section 05).

**Depends on:** section-01-models (for `Order` model fields accessed by these functions)

**Blocks:** section-02-order-placement-service, section-04-webhook-handler, section-05-celery-tasks

---

## Background and Context

NammaNeighbor uses Razorpay for three distinct payment operations:

1. **Payment Links** — buyer-facing: create a hosted payment page and send the URL to the buyer
2. **Route Transfers** — vendor payout: after payment capture, transfer `vendor_payout` amount to the vendor's linked Razorpay account, held until delivery is confirmed
3. **Transfer Hold Release** — release the `on_hold` flag on a Route transfer once delivery is confirmed (either manually by vendor or via the 24h Celery task)

The Razorpay Python SDK (`razorpay` package) must be added to `pyproject.toml`. The SDK is initialized once at module level as a cached client — this avoids repeated instantiation on each request.

### Required Settings

The following must be present in the Django settings (and available as environment variables):

- `RAZORPAY_KEY_ID` — Razorpay API key ID
- `RAZORPAY_KEY_SECRET` — Razorpay API key secret
- `RAZORPAY_WEBHOOK_SECRET` — webhook signature verification secret (used in section 04, but defined in settings alongside the other Razorpay keys)
- `APP_BASE_URL` — e.g., `https://api.nammaNeighbor.in` — used to construct the callback URL

### Razorpay Route

Route is Razorpay's marketplace/split payment feature. A vendor must have a linked account (`order.vendor.razorpay_account_id`) before transfers can be made. The transfer is created with `on_hold=True`, which freezes the funds until the platform explicitly releases them by setting `on_hold=0`.

---

## File to Create

**`apps/payments/services/razorpay.py`**

This file does not exist yet. Also create:
- `apps/payments/services/__init__.py` (empty)
- `apps/payments/services/` directory

---

## Tests First

**File:** `apps/payments/tests/test_services.py`

All Razorpay API calls must be mocked via `unittest.mock.patch('apps.payments.services.razorpay.client')`. Never hit the real Razorpay API in tests.

Write tests as stubs/outlines in this order:

```python
# Test: create_payment_link builds payload with correct amount in paise
#   - order.subtotal = Decimal('500.00') → amount field in payload = 50000
#   - currency = 'INR'

# Test: create_payment_link uses str(order.razorpay_idempotency_key) as reference_id
#   - verify payload['reference_id'] == str(order.razorpay_idempotency_key)

# Test: create_payment_link callback_url contains APP_BASE_URL + '/api/v1/payments/callback/'

# Test: create_payment_link notify field has sms=True

# Test: create_payment_link description includes vendor name

# Test: create_route_transfer sends correct vendor account
#   - verify transfers[0]['account'] == order.vendor.razorpay_account_id

# Test: create_route_transfer sends amount in paise
#   - order.vendor_payout = Decimal('465.00') → amount = 46500

# Test: create_route_transfer sends on_hold=True in transfer payload

# Test: create_route_transfer returns transfer_id string on success

# Test: create_route_transfer returns None when Razorpay raises an exception
#   - mock client.payment.transfer to raise razorpay.errors.BadRequestError
#   - assert return value is None (no re-raise)

# Test: release_transfer_hold sends PATCH request to correct URL
#   - URL pattern: https://api.razorpay.com/v1/transfers/{order.razorpay_transfer_id}
#   - request body contains {'on_hold': 0}

# Test: release_transfer_hold returns True on HTTP 200 response

# Test: release_transfer_hold returns False on 4xx response (already settled)
#   - mock the requests.patch call to return a 422 or 400 status
#   - assert return value is False (no exception raised)
```

Also create `apps/payments/tests/__init__.py` and `apps/payments/tests/conftest.py`.

The `conftest.py` should import factories from `apps/orders/tests/factories.py` (defined in section 01) and provide any payment-specific fixtures.

---

## Implementation Details

### Module-level Client

Initialize the Razorpay client once at module import time:

```python
import razorpay
from django.conf import settings

client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)
```

This `client` is what tests mock via `patch('apps.payments.services.razorpay.client')`.

---

### `create_payment_link(order) -> dict`

**Purpose:** Creates a Razorpay Payment Link for the buyer to complete payment.

**SDK method:** `client.payment_link.create(payload)`

**Returns:** The raw dict response from the Razorpay API (caller extracts `id` and `short_url`).

**Payload fields to build:**

| Field | Value |
|-------|-------|
| `amount` | `int(order.subtotal * 100)` — convert rupees to paise |
| `currency` | `"INR"` |
| `description` | Human-readable string including vendor display name (e.g., `"Order from {vendor name}"`) |
| `customer` | Dict with `name` and `contact` from the buyer's profile |
| `notify` | `{"sms": True}` |
| `callback_url` | `f"{settings.APP_BASE_URL}/api/v1/payments/callback/"` |
| `reference_id` | `str(order.razorpay_idempotency_key)` — this is the key that ties the webhook back to the order |

The `reference_id` is critical: when Razorpay sends the `payment.captured` webhook, this value appears in `payload["payload"]["payment"]["entity"]["notes"]["reference_id"]`, allowing the webhook handler to look up the order via `Order.objects.get(razorpay_idempotency_key=UUID(reference_id))`.

**Error handling:** Let exceptions propagate to the caller (`OrderPlacementService`) which handles them in Phase 2.

---

### `create_route_transfer(order) -> str | None`

**Purpose:** After a payment is captured, move `vendor_payout` to the vendor's linked Razorpay account, held until delivery is confirmed.

**SDK method:** `client.payment.transfer(payment_id, payload)` where `payment_id = order.razorpay_payment_id`

**Payload structure:**

```python
{
    "transfers": [
        {
            "account": order.vendor.razorpay_account_id,
            "amount": int(order.vendor_payout * 100),  # paise
            "currency": "INR",
            "on_hold": True,
        }
    ]
}
```

**Returns:** The `transfer_id` string from the first item in the response's `items` list on success. Returns `None` on any exception — do not re-raise.

**Error handling:** Wrap in `try/except Exception`. On failure: log the error with the order ID at `ERROR` level (format: `"TRANSFER_CREATION_FAILED order_id={order.id} error={e}"`), return `None`. The caller (webhook handler in section 04) checks for `None` and logs `"TRANSFER_CREATION_FAILED"` with order ID as an alert for ops but does not cancel the order.

---

### `release_transfer_hold(order) -> bool`

**Purpose:** Release the `on_hold` flag on a completed Route transfer so funds become available to the vendor.

**Why raw HTTP:** The Razorpay Python SDK does not have a dedicated method to patch a transfer's hold status. Use `requests.patch()` directly with HTTP Basic Auth.

**Request:**
- `PATCH https://api.razorpay.com/v1/transfers/{order.razorpay_transfer_id}`
- Auth: HTTP Basic `(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)`
- Body: `{"on_hold": 0}`
- Headers: `{"Content-Type": "application/json"}`

**Returns:**
- `True` on HTTP 2xx
- `False` on HTTP 4xx (the transfer is already settled — this is expected when the 24h Celery task fires after a vendor has already manually triggered delivery confirmation). Log the response body at `WARNING` level before returning `False`.

**Error handling:** Let network exceptions (`requests.exceptions.RequestException`) propagate — the Celery task in section 05 will log them and the task will retry via Celery's retry mechanism if configured, or they will be captured in monitoring.

---

## Structural Notes

- All three functions are module-level (not methods of a class)
- Keep all imports at the top of the file: `import razorpay`, `import requests`, `from django.conf import settings`, `import logging`
- Use `logger = logging.getLogger(__name__)` for all logging
- Do not import Django models in this file — receive the `order` object as a parameter and access only its attributes
- The `apps/payments/services/` package must have `__init__.py` to be importable

---

## Dependency Notes (Do Not Duplicate)

- **`Order` model fields used here** (defined in section 01): `subtotal`, `vendor_payout`, `razorpay_idempotency_key`, `razorpay_payment_id`, `razorpay_transfer_id`, `vendor.razorpay_account_id`, `vendor` (FK), `buyer` (FK with profile for name/contact)
- **Called by `OrderPlacementService`** (section 02): `create_payment_link(order)` is called in Phase 2 outside `transaction.atomic()`
- **Called by webhook handler** (section 04): `create_route_transfer(order)` is called inside `_handle_payment_captured`; `release_transfer_hold(order)` may also be called if hold needs releasing
- **Called by Celery tasks** (section 05): `release_transfer_hold(order)` is called in `release_payment_hold` task
- **Called by FSM transition body** (section 01): `mark_delivered()` transition calls `release_transfer_hold(order)` directly when vendor confirms delivery