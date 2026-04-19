# Research: 05-Ordering-Payments

## Part 1: Codebase Conventions (from Splits 01-04 Specs)

### 1.1 Base Model Pattern

All models inherit from `TimestampedModel` (defined in `apps/core/models.py`):
- Provides `created_at` (auto_now_add) and `updated_at` (auto_now)
- **Rule:** Never override `save()` for counter increments — use `F()` expressions with `.update()` directly

### 1.2 Vendor Model — Critical Details

**Related name:** `vendor_profile` (OneToOneField to User, `related_name='vendor_profile'`)
- Access: `request.user.vendor_profile`  
- **IMPORTANT:** The plan spec document says `vendor_profile_profile` in some places — the canonical reverse accessor is `vendor_profile` based on split 03 spec. Verify the actual Vendor model's `related_name` at implementation time.

**Status values:** `DRAFT`, `PENDING_REVIEW`, `APPROVED`, `SUSPENDED`, `DELISTED`

**Critical fields for split 05:**
- `razorpay_account_id` (CharField, max_length=100, blank=True)
- `razorpay_account_status` (pending/activated/suspended)
- `bank_account_verified` (BooleanField, default=False) — must be True before payout
- `completed_delivery_count` (PositiveIntegerField, default=0) — increment on delivery
- `missed_drop_window_count` (PositiveIntegerField, default=0) — increment on missed drops
- `average_rating` (DecimalField, max_digits=3, decimal_places=2)

### 1.3 Community Model

**Commission field:** `commission_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('7.50'))`

Commission formula:
```
rate = commission_pct / Decimal('100')
platform_commission = (subtotal * rate).quantize(Decimal('0.01'))
vendor_payout = subtotal - platform_commission
# INVARIANT: subtotal == platform_commission + vendor_payout (always)
```

### 1.4 DailyInventory Model (Split 04)

```python
class DailyInventory(TimestampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    date = models.DateField()
    qty_ordered = models.PositiveIntegerField(default=0)
    
    class Meta:
        unique_together = ('product', 'date')
```

**For split 05 stock decrement:**
- `get_or_create(product=product, date=order_date)` then update `qty_ordered`
- Guard: `qty_ordered + qty <= product.max_daily_qty` before decrementing
- Use F() optimistic update (see web research section)

### 1.5 Product Model Fields Needed by Split 05

- `delivery_days` (JSONField, list[int], 0=Monday–6=Sunday)
- `available_from` / `available_to` (TimeField, IST)
- `max_daily_qty` (PositiveIntegerField)
- `is_flash_sale` (BooleanField)
- `flash_sale_qty_remaining` (PositiveIntegerField, null=True)
- `flash_sale_ends_at` (DateTimeField, null=True)
- `vendor` FK → Vendor
- `community` FK → Community

### 1.6 JWT & Permission Classes

**JWT claims structure:**
```json
{
  "user_id": 42,
  "phone": "+919876543210",
  "roles": ["resident", "vendor", "community_admin"],
  "community_id": 7
}
```

**Existing permission classes** (from `apps/core/permissions.py`):
- `IsResidentOfCommunity` — checks `'resident'` in roles
- `IsVendorOfCommunity` — checks `'vendor'` in roles
- `IsCommunityAdmin` — checks `'community_admin'` in roles
- `IsPlatformAdmin` — checks `'platform_admin'` in roles

**New permissions needed for split 05:**
- `IsOrderBuyer` — `request.user == order.buyer.user`
- `IsOrderVendor` — `request.user == order.vendor.user`

### 1.7 Celery Configuration

- Broker & result backend: Redis (`REDIS_URL`)
- Timezone: `CELERY_TIMEZONE = 'Asia/Kolkata'`
- `CELERY_TASK_ALWAYS_EAGER = True` in test settings

**Payments queue already declared:**
```python
Queue('payments')
CELERY_TASK_ROUTES = {
    'apps.payments.tasks.*': {'queue': 'payments'},
}
```

**Beat entries to add:**
```python
'expire-flash-sales': {'task': 'apps.catalogue.tasks.expire_flash_sales', 'schedule': 900.0},
'check-missed-drop-windows': {'task': 'apps.payments.tasks.check_missed_drop_windows', 'schedule': crontab(hour=1, minute=0)},
```

**Task pattern:**
```python
@shared_task(bind=True, queue='payments', max_retries=3)
def my_task(self, arg1):
    try:
        ...
    except Exception as exc:
        countdown = 60 * (2 ** self.request.retries)  # exponential backoff
        raise self.retry(exc=exc, countdown=countdown)
```

### 1.8 Testing Conventions

- Stack: `pytest` + `pytest-django` + `factory_boy` + `freezegun` + `moto[s3]`
- Test config: `DJANGO_SETTINGS_MODULE = "config.settings.test"`
- `CELERY_TASK_ALWAYS_EAGER = True` in test settings — tasks run synchronously
- Test layout: `apps/{app}/tests/conftest.py`, `factories.py`, `test_models.py`, `test_views.py`, etc.
- Use `TransactionTestCase` (NOT `TestCase`) for concurrency tests — `TestCase` wraps in a transaction that prevents lock testing

### 1.9 Missing Dependencies to Add

**Must add to `pyproject.toml`:**
- `django-fsm-2` (maintained fork of `django-fsm`, original archived April 2024)
- `razorpay` (official Razorpay Python SDK)

### 1.10 Related Names Summary

| Model | Field | Related Name | Access Pattern |
|-------|-------|--------------|----------------|
| Vendor | user (OneToOneField) | `vendor_profile` | `user.vendor_profile` |
| ResidentProfile | user (OneToOneField) | `resident_profile` | `user.resident_profile` |
| Product | vendor (FK) | `products` | `vendor.products.all()` |
| Order | buyer (FK to ResidentProfile) | `orders` | `resident_profile.orders.all()` |
| Order | vendor (FK) | `received_orders` | `vendor.received_orders.all()` |
| OrderItem | order (FK) | `items` | `order.items.all()` |

---

## Part 2: Web Research Findings

### 2.1 Razorpay Route API & on_hold Transfers

**Creating a transfer from a payment (post-capture):**
```python
transfer = client.payment.transfer(payment_id, {
    "transfers": [{
        "account": vendor.razorpay_account_id,
        "amount": int(order.vendor_payout * 100),  # paise
        "currency": "INR",
        "on_hold": True,
        "on_hold_until": int((timezone.now() + timedelta(days=1)).timestamp()),  # optional
    }]
})
razorpay_transfer_id = transfer['items'][0]['id']
```

**Releasing a hold (PATCH):**
```python
# No dedicated SDK method — use raw HTTP or requests
import requests
requests.patch(
    f"https://api.razorpay.com/v1/transfers/{transfer_id}",
    json={"on_hold": 0},
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
)
```

**Dispute/refund — reverse all transfers atomically:**
```python
client.payment.refund(payment_id, {
    "amount": int(order.subtotal * 100),
    "reverse_all": 1,  # claws back all linked transfers automatically
    "speed": "normal",
})
```

**Key notes:**
- If `on_hold_until` is omitted, hold is indefinite — must explicitly PATCH to release
- Cannot change `on_hold` after transfer has already settled to Linked Account
- Monitor `transfer.failed` webhook — retry on failure
- `reverse_all=1` is preferred over individual reversal API calls for simplicity

**Sources:** Razorpay Route API docs, razorpay-python SDK docs

### 2.2 django-fsm Patterns & Testing

**Library:** Use `django-fsm-2` (maintained fork). Original `viewflow/django-fsm` was archived April 2024.

**Model definition:**
```python
from django_fsm import FSMField, transition, can_proceed, TransitionNotAllowed

status = FSMField(
    default=OrderStatus.PLACED,
    choices=OrderStatus.choices,
    protected=True,   # prevents direct assignment, forces use of transition methods
)

def payment_received(instance):
    """Guard: pure function, returns bool."""
    return bool(instance.razorpay_payment_id)

@transition(
    field=status,
    source=OrderStatus.PAYMENT_PENDING,
    target=OrderStatus.CONFIRMED,
    conditions=[payment_received],  # all must return True
    on_error=OrderStatus.CANCELLED,  # if transition body raises, go here
)
def confirm_payment(self):
    """Side effects go in the transition body, not in guards."""
    self.confirmed_at = timezone.now()
```

**Concurrency safety:**
```python
from django_fsm import ConcurrentTransitionMixin

class Order(ConcurrentTransitionMixin, models.Model):
    ...
```
Note: `ConcurrentTransitionMixin` uses optimistic locking for FSM transitions but does NOT protect stock decrements — still need `select_for_update` or F() updates for inventory.

**Testing helpers:**
```python
from django_fsm import can_proceed, TransitionNotAllowed, has_transition_perm

# Check if transition is valid (state + conditions)
can_proceed(order.confirm_payment)  # True/False

# Check state only (ignore conditions)
can_proceed(order.confirm_payment, check_conditions=False)

# Check permission
has_transition_perm(order.cancel, user)

# Test invalid transition
with pytest.raises(TransitionNotAllowed):
    order.ship()  # wrong source state
```

**Best practices:**
- Guards are pure functions — no side effects
- Side effects go in transition body
- Always wrap transitions in `transaction.atomic()`
- Use `protected=True` on `FSMField` in production

### 2.3 Razorpay Webhook Verification in Django

**Critical rule: always use raw body for signature verification:**
```python
raw_body = request.body           # bytes — do NOT parse first
signature = request.META.get("HTTP_X_RAZORPAY_SIGNATURE", "")

client.utility.verify_webhook_signature(
    raw_body.decode("utf-8"),     # must be string, not bytes
    signature,
    settings.RAZORPAY_WEBHOOK_SECRET,
)
```

**Idempotency via `X-Razorpay-Event-ID` header:**
```python
event_id = request.META.get("HTTP_X_RAZORPAY_EVENT_ID", "")
# Store in WebhookEvent model with unique constraint on event_id
# On IntegrityError: duplicate delivery — return 200 immediately
```

**WebhookEvent model:**
```python
class WebhookEvent(TimestampedModel):
    event_id = models.CharField(max_length=255, unique=True, db_index=True)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
```

**Response rules:**
- Return `400` only for signature verification failure
- Return `200` for everything else — including handler errors (log to alerting, don't cause Razorpay retries)
- Razorpay retries with exponential backoff over 24h window on non-2xx responses
- `X-Razorpay-Event-ID` is consistent across retries of the same event

**View skeleton:**
```python
@csrf_exempt
@require_POST
def razorpay_webhook(request):
    raw_body = request.body
    signature = request.META.get("HTTP_X_RAZORPAY_SIGNATURE", "")
    event_id = request.META.get("HTTP_X_RAZORPAY_EVENT_ID", "")
    
    # 1. Verify signature BEFORE parsing
    try:
        client.utility.verify_webhook_signature(raw_body.decode("utf-8"), signature, secret)
    except razorpay.errors.SignatureVerificationError:
        return HttpResponseBadRequest("Invalid signature")
    
    # 2. Parse after verification
    payload = json.loads(raw_body)
    
    # 3. Idempotency check
    try:
        with transaction.atomic():
            WebhookEvent.objects.create(event_id=event_id, ...)
    except IntegrityError:
        return HttpResponse("Already processed", status=200)
    
    # 4. Route to handler (return 200 even on handler errors)
    try:
        _handle_event(payload["event"], payload)
    except Exception:
        logger.exception("Webhook handler failed")
    
    return HttpResponse("OK", status=200)
```

### 2.4 Django Atomic Order Placement with select_for_update

**Pattern choice:**
- Use **F() optimistic update** for stock decrement — single atomic SQL statement, no blocking
- Use **select_for_update** only when complex Python-level logic requires reading full row state

**F() optimistic pattern for DailyInventory:**
```python
@transaction.atomic
def decrement_inventory(product_id, date, qty):
    # Ensure row exists
    DailyInventory.objects.get_or_create(product_id=product_id, date=date)
    
    # Atomic check + decrement in single SQL UPDATE
    updated = DailyInventory.objects.filter(
        product_id=product_id,
        date=date,
        qty_ordered__lte=F('max_daily_qty') - qty,  # guard: won't overshoot max
    ).update(
        qty_ordered=F('qty_ordered') + qty
    )
    
    if updated == 0:
        raise InsufficientStockError(f"Product {product_id} at daily quota")
```

**Simpler approach given DailyInventory structure** (since we track `qty_ordered` not `qty_available`):
```python
# Get product's max_daily_qty
product = Product.objects.get(pk=product_id)

updated = DailyInventory.objects.filter(
    product_id=product_id,
    date=date,
    qty_ordered__lte=product.max_daily_qty - qty,  # remaining capacity >= qty
).update(qty_ordered=F('qty_ordered') + qty)

if updated == 0:
    raise InsufficientStockError(...)
```

**Flash sale decrement (from split 04 spec):**
```python
# Separate atomic update for flash sale qty
Product.objects.filter(
    pk=product_id,
    flash_sale_qty_remaining__gte=qty,
).update(flash_sale_qty_remaining=F('flash_sale_qty_remaining') - qty)
```

**Full order placement transaction scope:**
```python
@transaction.atomic
def place_order(user, items, delivery_window, delivery_notes):
    # 1. Validate all products
    # 2. Validate delivery_window + available_from/to
    # 3. Decrement DailyInventory for each item (F() optimistic)
    # 4. Decrement flash_sale_qty_remaining if applicable (F() optimistic)
    # 5. Calculate financials
    # 6. Create Order + OrderItems
    # 7. Generate Razorpay payment link
    # 8. Transition order to PAYMENT_PENDING
    # All inside single atomic block — any failure rolls back everything
```

**DB safety net:**
```python
class DailyInventory(TimestampedModel):
    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(qty_ordered__gte=0),
                name="daily_inventory_no_negative_qty"
            )
        ]
```

**Concurrency testing — use TransactionTestCase:**
```python
from django.test import TransactionTestCase
import threading

class OrderConcurrencyTest(TransactionTestCase):
    def test_only_one_order_succeeds_for_last_unit(self):
        # Use threading.Barrier to synchronize threads
        ...
```

---

## Part 3: Summary of Key Decisions for Implementation

| Concern | Decision |
|---------|----------|
| FSM library | `django-fsm-2` (add to deps) |
| Razorpay SDK | `razorpay` (add to deps) |
| FSM field | `protected=True`, `ConcurrentTransitionMixin` |
| Transfer timing | Create with `on_hold=True` from captured payment |
| Transfer release | PATCH `on_hold=0` after delivery confirmation |
| Refund/dispute | `reverse_all=1` on payment refund |
| Webhook signature | `request.body.decode()` — never parsed body |
| Webhook idempotency | `X-Razorpay-Event-ID` with unique DB constraint |
| Stock decrement | F() optimistic update with capacity guard in WHERE |
| Transaction scope | Single `transaction.atomic()` wraps entire order placement |
| Vendor accessor | `request.user.vendor_profile` (verify actual related_name) |
| Test for concurrency | `TransactionTestCase` not `TestCase` |
| Celery test mode | `CELERY_TASK_ALWAYS_EAGER = True` in test settings |
