Now I have all the context needed. Let me generate the section content.

# Section 01: Models

## Overview

This is the foundation section. All other sections depend on it. You will create the Django models for the `orders` and `payments` apps, including FSM-driven order lifecycle, financial invariants, Razorpay/delivery fields, and the idempotency log.

**Files to create or modify:**

- `apps/orders/__init__.py`
- `apps/orders/apps.py`
- `apps/orders/models.py`
- `apps/orders/tests/__init__.py`
- `apps/orders/tests/conftest.py`
- `apps/orders/tests/factories.py`
- `apps/orders/tests/test_models.py`
- `apps/payments/__init__.py`
- `apps/payments/apps.py`
- `apps/payments/models.py`
- `apps/payments/tests/__init__.py`
- `apps/payments/tests/conftest.py`
- `pyproject.toml` (add new dependencies)
- Django migrations for both apps

---

## Dependencies (Prior Splits — Do Not Reimplement)

These models already exist and must be referenced by FK:

- `apps.core.models.TimestampedModel` — base model with `created_at`, `updated_at`
- `apps.communities.models.Community` — has `commission_pct` (DecimalField, default 7.50)
- `apps.communities.models.ResidentProfile` — OneToOne to User, `related_name='resident_profile'`
- `apps.vendors.models.Vendor` — OneToOne to User, `related_name='vendor_profile'`; has `razorpay_account_id`, `completed_delivery_count`
- `apps.catalogue.models.Product` — has `delivery_days`, `available_from`, `available_to`, `max_daily_qty`, `flash_sale_qty_remaining`
- `apps.catalogue.models.DailyInventory` — has `qty_ordered`, unique on `(product, date)`

> Note: Verify whether the Vendor reverse accessor is `vendor_profile` or `vendor_profile_profile` in the split 03 Vendor model before using it. There is a known ambiguity here.

---

## New Package Dependencies

Add to `pyproject.toml`:

```
django-fsm-2       # maintained fork of django-fsm (original archived April 2024); API-compatible
razorpay           # official Razorpay Python SDK
```

---

## Tests First

### `apps/orders/tests/factories.py`

Write factories before writing model tests. All other test sections depend on these factories.

```python
# OrderFactory
#   - status = OrderStatus.PLACED
#   - buyer, vendor, community from prior split factories
#   - subtotal, platform_commission, vendor_payout set to consistent values satisfying the invariant
#   - delivery_window = today's date
#   - razorpay_idempotency_key auto-generated UUID

# OrderItemFactory
#   - linked to an Order via SubFactory
#   - product from catalogue factory
#   - quantity, unit_price, subtotal (subtotal = quantity * unit_price)

# DailyOrderSequenceFactory
#   - date = today
#   - last_sequence = 0
```

```python
# In apps/payments/tests/factories.py (or conftest):
# WebhookEventFactory
#   - event_id: unique string (Sequence)
#   - event_type = 'payment.captured'
#   - payload = {} (empty dict is fine as default)
```

### `apps/orders/tests/test_models.py`

```python
# --- Field invariant tests ---

def test_order_financial_invariant(order_factory):
    """order.subtotal == order.platform_commission + order.vendor_payout"""

def test_order_display_id_unique_constraint(db):
    """Creating two Orders with the same display_id raises IntegrityError at the DB level."""

def test_order_razorpay_idempotency_key_is_uuid_and_unique(db):
    """razorpay_idempotency_key is auto-generated as a UUID; two orders have distinct keys."""

def test_order_item_subtotal_equals_quantity_times_unit_price(order_item_factory):
    """OrderItem.subtotal == quantity * unit_price"""

def test_order_delivered_at_defaults_to_none(order_factory):
    """Fresh Order has delivered_at = None."""

def test_order_cancelled_at_defaults_to_none(order_factory):
    """Fresh Order has cancelled_at = None."""

def test_daily_order_sequence_date_unique_constraint(db):
    """Two DailyOrderSequence rows with the same date raise IntegrityError."""

# --- FSM transition tests ---

def test_placed_to_payment_pending(order):
    """PLACED → PAYMENT_PENDING via await_payment() succeeds."""

def test_placed_to_confirmed_directly_raises(order):
    """PLACED → CONFIRMED directly raises TransitionNotAllowed (FSM protected field)."""

def test_payment_pending_to_confirmed(order):
    """PAYMENT_PENDING → CONFIRMED via confirm_payment() succeeds."""

def test_confirmed_to_ready(order):
    """CONFIRMED → READY via mark_ready() succeeds."""

def test_ready_to_delivered(order):
    """READY → DELIVERED via mark_delivered() succeeds."""

def test_placed_to_cancelled(order):
    """PLACED → CANCELLED via cancel() succeeds; cancelled_at is set (not None)."""

def test_payment_pending_to_cancelled(order):
    """PAYMENT_PENDING → CANCELLED via cancel() succeeds."""

def test_confirmed_to_cancelled_directly_raises(order):
    """CONFIRMED → CANCELLED directly raises TransitionNotAllowed."""

def test_raise_dispute_within_24h(order, freezer):
    """DELIVERED → DISPUTED via raise_dispute() succeeds when within 24h of delivered_at."""

def test_raise_dispute_after_24h_raises(order, freezer):
    """raise_dispute() raises TransitionNotAllowed when delivered_at is >24h ago."""
    # Use freezegun to travel past the 24h window

def test_resolve_dispute(order):
    """DISPUTED → DELIVERED via resolve_dispute() succeeds."""

def test_process_refund(order):
    """DISPUTED → REFUNDED via process_refund() succeeds."""

def test_escalate_to_dispute_from_confirmed(order):
    """CONFIRMED → DISPUTED via escalate_to_dispute() succeeds (vendor cancel path)."""

def test_mark_delivered_without_transfer_id_does_not_raise(order):
    """mark_delivered() proceeds even when razorpay_transfer_id is blank; no exception is raised."""

def test_concurrent_confirm_payment_raises_retry_needed(db):
    """Two simultaneous confirm_payment() calls on the same order raise RetryNeeded on the second
    (ConcurrentTransitionMixin optimistic locking)."""
```

---

## Implementation: `apps/orders/models.py`

### `OrderStatus` (TextChoices)

Define an `OrderStatus` enum (or `TextChoices`) with these values:

`PLACED`, `PAYMENT_PENDING`, `CONFIRMED`, `READY`, `DELIVERED`, `CANCELLED`, `DISPUTED`, `REFUNDED`

`OUT_FOR_DELIVERY` is intentionally excluded from the MVP.

### `Order`

Inherit from both `ConcurrentTransitionMixin` and `TimestampedModel`. `ConcurrentTransitionMixin` must come first in the MRO (before the base model) to ensure the version field is added correctly.

```python
class Order(ConcurrentTransitionMixin, TimestampedModel):
    """Central order model with FSM lifecycle and Razorpay integration."""
    ...
```

**Fields (complete list):**

| Field | Type | Notes |
|---|---|---|
| `buyer` | FK → ResidentProfile | `on_delete=PROTECT`, `related_name='orders'` |
| `vendor` | FK → Vendor | `on_delete=PROTECT`, `related_name='received_orders'` |
| `community` | FK → Community | `on_delete=PROTECT` |
| `status` | FSMField | `default=OrderStatus.PLACED`, `protected=True` |
| `display_id` | CharField(50) | `unique=True` |
| `subtotal` | DecimalField(10, 2) | |
| `platform_commission` | DecimalField(10, 2) | |
| `vendor_payout` | DecimalField(10, 2) | |
| `delivery_window` | DateField | |
| `delivery_notes` | TextField | `blank=True` |
| `razorpay_payment_link_id` | CharField(255) | `blank=True` |
| `razorpay_payment_link_url` | URLField | `blank=True` |
| `razorpay_payment_id` | CharField(255) | `blank=True`, `db_index=True` |
| `razorpay_transfer_id` | CharField(255) | `blank=True` |
| `transfer_on_hold` | BooleanField | `default=True` |
| `razorpay_idempotency_key` | UUIDField | `default=uuid4`, `unique=True` |
| `hold_release_at` | DateTimeField | `null=True`, `blank=True` |
| `delivered_at` | DateTimeField | `null=True`, `blank=True` |
| `cancelled_at` | DateTimeField | `null=True`, `blank=True` |
| `dispute_reason` | TextField | `blank=True` |
| `dispute_raised_at` | DateTimeField | `null=True`, `blank=True` |

**DB indexes** (add via `Meta.indexes`):

- `(vendor, delivery_window, status)`
- `(buyer, status)`
- `(razorpay_payment_id)` — already handled via `db_index=True` above
- `(display_id)` — already handled via `unique=True` above

**FSM Transitions** — use `@transition(field=status, source=..., target=...)` decorator from `django_fsm`:

```python
@transition(field=status, source=OrderStatus.PLACED, target=OrderStatus.PAYMENT_PENDING)
def await_payment(self):
    """Schedule cancel_unpaid_order task with 30-minute countdown."""
    # import and call: cancel_unpaid_order.apply_async(args=[self.pk], countdown=1800)

@transition(field=status, source=OrderStatus.PAYMENT_PENDING, target=OrderStatus.CONFIRMED)
def confirm_payment(self):
    """Create Route transfer, schedule release_payment_hold in 24h, call notification stubs."""
    # from apps.payments.tasks import release_payment_hold
    # release_payment_hold.apply_async(args=[self.pk], eta=timezone.now() + timedelta(hours=24))
    # from apps.notifications.tasks import notify_vendor_order_received, notify_buyer_payment_confirmed
    # (call stubs)

@transition(field=status, source=OrderStatus.CONFIRMED, target=OrderStatus.READY)
def mark_ready(self):
    """Call buyer notification stub."""

@transition(field=status, source=OrderStatus.READY, target=OrderStatus.DELIVERED)
def mark_delivered(self):
    """Set delivered_at. Release transfer hold if transfer_id exists, else log alert.
    Increment vendor.completed_delivery_count. Call notification stub."""

@transition(
    field=status,
    source=[OrderStatus.PLACED, OrderStatus.PAYMENT_PENDING],
    target=OrderStatus.CANCELLED
)
def cancel(self):
    """Set cancelled_at. Restore DailyInventory for each item via F() decrement.
    If razorpay_payment_id is set, trigger Razorpay refund."""

@transition(
    field=status,
    source=[OrderStatus.CONFIRMED, OrderStatus.READY],
    target=OrderStatus.DISPUTED
)
def escalate_to_dispute(self):
    """Vendor cancel path. Sets dispute_raised_at."""

@transition(field=status, source=OrderStatus.DELIVERED, target=OrderStatus.DISPUTED,
            conditions=[_within_dispute_window])
def raise_dispute(self):
    """Buyer dispute. Sets dispute_reason, dispute_raised_at."""

@transition(field=status, source=OrderStatus.DISPUTED, target=OrderStatus.DELIVERED)
def resolve_dispute(self):
    """Community admin resolves in vendor's favor."""

@transition(field=status, source=OrderStatus.DISPUTED, target=OrderStatus.REFUNDED)
def process_refund(self):
    """Community admin resolves in buyer's favor. Triggers Razorpay refund."""
```

The `raise_dispute()` guard condition (`_within_dispute_window`) should be a standalone function (not a method) that accepts `self` and returns `True` when `timezone.now() - self.delivered_at <= timedelta(hours=24)`. Note it uses `delivered_at`, not `updated_at`.

**Transition body notes:**

- `cancel()` iterates `self.items.all()` and performs a `DailyInventory.objects.filter(...).update(qty_ordered=F('qty_ordered') - item.quantity)` for each item. This runs inside a `transaction.atomic()` wrapping the save call.
- `mark_delivered()` checks `bool(self.razorpay_transfer_id)` before calling `release_transfer_hold`. If blank, use `logger.error("MANUAL_PAYOUT_REQUIRED order_id=%s", self.pk)`.
- `confirm_payment()` imports Celery tasks inside the method body to avoid circular imports.

**`__str__`:** Return `f"Order {self.display_id} ({self.status})"`.

### `OrderItem`

```python
class OrderItem(TimestampedModel):
    """Snapshot of a product at order time. Price fields never change after creation."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('catalogue.Product', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
```

`__str__`: Return `f"{self.quantity}x {self.product_id} @ {self.unit_price}"`.

### `DailyOrderSequence`

```python
class DailyOrderSequence(models.Model):
    """Per-date counter for generating human-readable display_ids. Not a TimestampedModel."""
    date = models.DateField(unique=True)
    last_sequence = models.PositiveIntegerField(default=0)
```

`__str__`: Return `f"Sequence {self.date}: {self.last_sequence}"`.

---

## Implementation: `apps/payments/models.py`

### `WebhookEvent`

```python
class WebhookEvent(models.Model):
    """Idempotency log for Razorpay webhook deliveries. One row per unique event delivery."""
    event_id = models.CharField(max_length=255, unique=True, db_index=True)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
```

`__str__`: Return `f"WebhookEvent {self.event_type} ({self.event_id})"`.

---

## App Registration

### `apps/orders/apps.py`

```python
class OrdersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.orders'
```

### `apps/payments/apps.py`

```python
class PaymentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.payments'
```

Add both to `INSTALLED_APPS` in Django settings.

---

## Migrations

After writing the models, generate migrations:

```
uv run python manage.py makemigrations orders
uv run python manage.py makemigrations payments
```

The `ConcurrentTransitionMixin` from `django-fsm-2` adds an integer `state_version` field to the `Order` model. This will appear in the generated migration automatically — do not add it manually.

---

## Key Invariants to Enforce

- `subtotal == platform_commission + vendor_payout` — enforced by `OrderPlacementService` at creation; never recomputed. Not enforced by a DB constraint, but tested at the model level.
- `OrderItem.subtotal == quantity * unit_price` — set at creation time by the service, tested at the model level.
- `display_id` unique constraint — enforced by DB (`unique=True`) and tested with an `IntegrityError` assertion.
- `razorpay_idempotency_key` unique constraint — enforced by DB (`unique=True`).
- `raise_dispute()` guard uses `delivered_at`, not `updated_at`, so that any subsequent `save()` call on the order does not extend the 24-hour window.
- `protected=True` on `FSMField` prevents any direct status assignment outside of `@transition`-decorated methods.

---

## Import Notes

The transition methods in `Order` must use lazy/inline imports for Celery tasks to avoid circular import issues:

```python
# Inside confirm_payment():
from apps.payments.tasks import release_payment_hold  # local import
```

The `_within_dispute_window` guard function must be defined at module level (not as a method) before the `Order` class body, or as a free function imported at the top of the file:

```python
def _within_dispute_window(instance):
    if not instance.delivered_at:
        return False
    return timezone.now() - instance.delivered_at <= timedelta(hours=24)
```