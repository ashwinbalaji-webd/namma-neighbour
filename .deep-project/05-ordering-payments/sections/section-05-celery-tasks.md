Now I have all the context I need. Let me generate the section content.

# Section 05: Celery Tasks

## Overview

This section implements three Celery tasks in `apps/payments/tasks.py` that handle time-delayed payment lifecycle management and vendor accountability tracking. These tasks are scheduled by FSM transition side-effects (sections 01 and 04) and by Celery Beat.

**Dependencies:**
- Section 01 (Models): `Order`, `OrderStatus` FSM, `VendorCommunity` from prior splits
- Section 03 (Razorpay Services): `release_transfer_hold()` function

**Blocks:** Section 08 (vendor/admin endpoints reference task scheduling)

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `apps/payments/tasks.py` | Create — all three tasks |
| `apps/payments/tests/test_tasks.py` | Create — all task tests |
| `apps/payments/tests/conftest.py` | Create or extend — task-specific fixtures |
| `pyproject.toml` (or `settings/base.py`) | Modify — add Celery Beat schedule for `check_missed_drop_windows` |

---

## Tests First

File: `apps/payments/tests/test_tasks.py`

Test settings must have `CELERY_TASK_ALWAYS_EAGER = True` so tasks execute synchronously in the test process without a running broker.

### Fixtures needed

The conftest should provide:
- An `order_payment_pending` fixture: an `Order` in `PAYMENT_PENDING` status with no `razorpay_payment_id`
- An `order_confirmed` fixture: an `Order` in `CONFIRMED` status with `razorpay_payment_id` set and `transfer_on_hold=True`
- An `order_delivered` fixture: an `Order` in `DELIVERED` status with `transfer_on_hold=False`
- A `vendor_community` fixture for testing missed-window increments (pulled from the prior-split `VendorCommunity` model)

Use `freeze_time` from `freezegun` to control `date.today()` / `timezone.now()` in missed-window and timing tests.

### `cancel_unpaid_order` tests

```python
# Test: order in PAYMENT_PENDING with blank razorpay_payment_id → status becomes CANCELLED, inventory restored
# Test: order already CONFIRMED → task returns silently, status unchanged
# Test: order already CANCELLED → task returns silently, status unchanged
# Test: order in PAYMENT_PENDING but razorpay_payment_id is non-blank → task returns silently (race guard),
#       status stays PAYMENT_PENDING (webhook will complete the transition)
```

The inventory restoration assertion should verify `DailyInventory.qty_ordered` decremented back for each `OrderItem`. This tests that the `cancel()` FSM transition body runs correctly when invoked from the task.

### `release_payment_hold` tests

```python
# Test: order with transfer_on_hold=True and status != DISPUTED → release_transfer_hold() is called once
# Test: order with status=DISPUTED → task returns silently, release_transfer_hold() is NOT called
# Test: order with transfer_on_hold=False → task returns silently, release_transfer_hold() is NOT called
```

Mock `release_transfer_hold` via `unittest.mock.patch('apps.payments.tasks.release_transfer_hold')` — do not hit Razorpay in tests.

### `check_missed_drop_windows` tests

Use `freeze_time` to pin today's date so `yesterday = date.today() - timedelta(days=1)` resolves to a known value.

```python
# Test: order with delivery_window=yesterday AND status=CONFIRMED → VendorCommunity.missed_window_count incremented by 1
# Test: order with delivery_window=yesterday AND status=READY → VendorCommunity.missed_window_count incremented by 1
# Test: order with delivery_window=yesterday AND status=DELIVERED → NOT counted (count stays 0)
# Test: order with delivery_window=yesterday AND status=CANCELLED → NOT counted
# Test: two missed orders for same (vendor_id, community_id) pair → missed_window_count incremented by 1
#       (F() grouped update, one increment per pair not per order)
# Test: missed orders from two different (vendor, community) pairs → correct VendorCommunity row incremented
#       for each pair independently
```

For the "same pair, single increment" test: create two orders for the same vendor+community with `delivery_window=yesterday` and `status=CONFIRMED`. After task runs, assert `VendorCommunity.missed_window_count == 1` (not 2). The grouping by pair is the invariant, not the order count.

---

## Implementation

### `apps/payments/tasks.py`

```python
from celery import shared_task
# imports: Order, OrderStatus, VendorCommunity, release_transfer_hold, logging, timezone, timedelta, date, F
```

#### Task: `cancel_unpaid_order`

```python
@shared_task(queue='payments')
def cancel_unpaid_order(order_id):
    """
    Scheduled 30 minutes after await_payment() fires.
    Cancels the order if it is still PAYMENT_PENDING and no payment has been captured.
    
    Race guard: if razorpay_payment_id is non-blank, the webhook handler has already
    captured the payment even if the FSM transition to CONFIRMED has not yet completed.
    In that case, do NOT cancel — the webhook will complete the transition.
    """
```

Logic:
1. `order = Order.objects.get(pk=order_id)` — if not found, log and return.
2. If `order.status != OrderStatus.PAYMENT_PENDING`: return silently.
3. If `order.razorpay_payment_id` is non-blank (race guard): return silently.
4. Call `order.cancel()` and `order.save()`.

The `cancel()` FSM transition body (defined in section 01) handles DailyInventory restoration via `F()` updates on each item — this task does not need to replicate that logic.

#### Task: `release_payment_hold`

```python
@shared_task(queue='payments')
def release_payment_hold(order_id):
    """
    Scheduled 24 hours after payment.captured webhook processes successfully.
    Releases the Razorpay Route transfer hold for the vendor payout.
    
    Returns silently if the order is disputed (hold must be preserved for admin review)
    or if the hold has already been released (e.g., by manual vendor delivery confirmation).
    """
```

Logic:
1. `order = Order.objects.get(pk=order_id)` — if not found, log and return.
2. If `order.status == OrderStatus.DISPUTED`: return silently (hold is intentionally preserved).
3. If `order.transfer_on_hold == False`: return silently (already released, log for observability).
4. Call `release_transfer_hold(order)` from `apps.payments.services.razorpay`. Log the result (True/False) at INFO level regardless of success — this aids ops investigation.

Note: `release_transfer_hold()` already catches Razorpay 4xx (transfer already settled) and returns `False` without raising. This task does not need an additional try/except around that call beyond basic task-level error handling.

#### Task: `check_missed_drop_windows`

```python
@shared_task(queue='payments')
def check_missed_drop_windows():
    """
    Daily cron task scheduled at 01:00 IST via Celery Beat.
    Finds all orders whose delivery_window was yesterday and are still in CONFIRMED or READY
    status (i.e., vendor did not mark them delivered). Increments VendorCommunity.missed_window_count
    for each affected (vendor_id, community_id) pair.
    
    Uses F() updates to avoid race conditions. Groups by pair to count one missed window
    per vendor-community relationship per day, regardless of how many orders were missed.
    """
```

Logic:
1. `yesterday = date.today() - timedelta(days=1)`
2. Query `Order.objects.filter(delivery_window=yesterday, status__in=[OrderStatus.CONFIRMED, OrderStatus.READY])` — select `vendor_id` and `community_id` fields only (use `.values('vendor_id', 'community_id').distinct()` to get unique pairs).
3. For each distinct `(vendor_id, community_id)` pair: `VendorCommunity.objects.filter(vendor_id=vendor_id, community_id=community_id).update(missed_window_count=F('missed_window_count') + 1)`
4. Log count of affected pairs at INFO level.

**Why `.distinct()` on the pairs:** A vendor may have 10 missed orders for the same community on the same day. The `missed_window_count` is a per-day missed drop window counter, not a per-order counter. One increment per `(vendor, community)` per day is the correct semantics.

---

## Celery Beat Configuration

Add to Django settings (e.g., `settings/base.py`):

```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'check-missed-drop-windows-daily': {
        'task': 'apps.payments.tasks.check_missed_drop_windows',
        'schedule': crontab(hour=19, minute=30),  # 01:00 IST = 19:30 UTC
    },
}
```

IST is UTC+5:30, so 01:00 IST = 19:30 UTC the previous calendar day. Document this offset conversion in a comment in the settings file.

---

## Queue Configuration

All three tasks use `queue='payments'`. Ensure the `payments` queue is declared in the Celery worker configuration. A minimal worker start command for this queue:

```
celery -A config.celery worker -Q payments --concurrency=2
```

If using a single-worker setup in development, add `payments` to the default queues list.

---

## Key Invariants and Edge Cases

**`cancel_unpaid_order` race window:** The task fires 30 minutes after order creation. Between the task firing and executing, the Razorpay webhook may have set `razorpay_payment_id` but not yet called `confirm_payment()`. The `razorpay_payment_id` non-blank check is the guard. The task must check this field AFTER the status check to avoid a TOCTOU issue — fetch the order fresh from the DB at task execution time (not from a cached reference).

**`release_payment_hold` idempotency:** Both the vendor's manual `mark_delivered()` call and this 24h task call `release_transfer_hold()`. The function returns `False` (not raises) when Razorpay responds 4xx because the transfer is already settled. This makes the task naturally idempotent — running it twice is harmless.

**`check_missed_drop_windows` timing:** The task runs at 01:00 IST, after midnight. `yesterday = date.today() - timedelta(days=1)` uses the server's local date. If the server runs in UTC, `date.today()` at 01:00 IST (19:30 UTC previous day) would return the wrong date. Use `timezone.localdate()` (Django's IST-aware equivalent) or configure `TIME_ZONE = 'Asia/Kolkata'` in Django settings and verify `USE_TZ = True`. Document this assumption explicitly.

**`VendorCommunity` import path:** `VendorCommunity` lives in `apps/vendors/models.py` from prior splits. Import as `from apps.vendors.models import VendorCommunity`. Verify the exact model name and the field name (`missed_window_count`) against the split 03 implementation before running tests.

**Order not found:** All tasks should handle `Order.DoesNotExist` gracefully — log at WARNING level and return. Do not let the task raise an unhandled exception, which would cause Celery to retry and potentially spam logs.