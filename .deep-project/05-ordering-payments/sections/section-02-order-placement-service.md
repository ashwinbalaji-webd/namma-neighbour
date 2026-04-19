Now I have all the context I need. I'll generate the section content for `section-02-order-placement-service`.

# Section 02: OrderPlacementService

## Overview

This section implements `apps/orders/services.py` — the `OrderPlacementService.place_order()` static method and the custom `InsufficientStockError` exception. All order placement business logic lives here; the view layer calls this method and stays thin.

**Dependencies:**
- **Section 01** (models): `Order`, `OrderItem`, `DailyOrderSequence`, `OrderStatus` FSM field and transitions must exist before this section can be implemented.
- **Section 03** (Razorpay services): `create_payment_link()` from `apps/payments/services/razorpay.py` is called in Phase 2. If section 03 is not yet merged, stub it as `def create_payment_link(order): raise NotImplementedError`.

This section is blocked by sections 01 and 03, and it blocks sections 07 and 08.

---

## Files to Create or Modify

- **Create:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/orders/services.py`
- **Create:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/orders/tests/test_services.py`
- **Create:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/orders/tests/test_concurrency.py`
- **Modify (if not already present):** `/var/www/html/MadGirlfriend/namma-neighbour/apps/orders/tests/conftest.py` — shared fixtures
- **Modify (if not already present):** `/var/www/html/MadGirlfriend/namma-neighbour/apps/orders/tests/factories.py` — section 01 establishes factories; confirm they exist before writing tests

---

## Background and Context

NammaNeighbor residents pre-order products from approved vendors during daily delivery windows. Order placement must be atomic: if any product runs out of stock mid-placement, all earlier stock decrements in the same order are automatically rolled back. A Razorpay Payment Link is created after the DB transaction commits to avoid holding locks during an external HTTP call.

**Key models used (from Section 01):**
- `Order` — `status` is a `FSMField(protected=True)`. Transitions: `await_payment()` moves from `PLACED` to `PAYMENT_PENDING`.
- `OrderItem` — stores unit price snapshot.
- `DailyOrderSequence` — per-date counter for human-readable display IDs; accessed with `select_for_update`.

**Key models from prior splits:**
- `VendorCommunity` (in `apps/vendors/`) — join table with `status` field that must be `'approved'` and `missed_window_count` counter.
- `DailyInventory` (in `apps/catalogue/`) — has `qty_ordered` field; also `Product` has `max_daily_qty`, `delivery_days`, `available_from`, `available_to`, `flash_sale_qty_remaining`.
- `Community` (in `apps/communities/`) — has `commission_pct` as `DecimalField`.
- `ResidentProfile` (in `apps/communities/`) — `OneToOne` to `User` with `related_name='resident_profile'`.

**New dependency to add to `pyproject.toml`:** No new packages are introduced in this section specifically, but `django-fsm-2` and `razorpay` (from section 01 and 03) must be present.

---

## Custom Exception

Define in `apps/orders/services.py`:

```python
class InsufficientStockError(Exception):
    """Raised inside transaction.atomic() when a stock decrement update affects 0 rows.
    Causes the entire atomic block to roll back, restoring all prior decrements."""
    pass
```

HTTP layer in section 07 must catch this and return HTTP 409.

---

## OrderPlacementService Implementation

`OrderPlacementService` is a class with a single `@staticmethod`. The two-phase design is the most important architectural decision here.

### File: `apps/orders/services.py`

```python
from decimal import Decimal, ROUND_HALF_UP
import logging
from django.db import transaction
from django.utils import timezone
# ... other imports

logger = logging.getLogger(__name__)


class InsufficientStockError(Exception):
    """Raised when stock decrement finds 0 eligible rows; triggers atomic rollback."""
    pass


class OrderPlacementService:

    @staticmethod
    def place_order(user, payload) -> 'Order':
        """Place an order for a resident.

        Two-phase design:
          Phase 1: transaction.atomic() — all DB writes
          Phase 2: Razorpay API call outside transaction

        Args:
            user: the authenticated Django User (must have resident_profile)
            payload: validated data from PlaceOrderSerializer — contains
                     vendor_id, delivery_window (date), items (list of
                     {product_id, quantity}), delivery_notes

        Returns:
            Saved Order instance with status=PAYMENT_PENDING and
            razorpay_payment_link_url set.

        Raises:
            ValidationError (400): invalid vendor/community, delivery window,
                                   or flash sale stock.
            InsufficientStockError (409): a product hit max_daily_qty.
            ServiceUnavailable (503): Razorpay call failed.
        """
        ...
```

### Phase 1 — `transaction.atomic()` (DB operations only)

All steps inside a single `with transaction.atomic():` block. Raising any exception inside the block causes a full rollback, including all stock decrements done earlier in the loop.

**Step 1 — Validate vendor and community**

- Resolve `buyer = user.resident_profile` (raises `ObjectDoesNotExist` if missing — treat as 400).
- All items must belong to the same single vendor. Fetch `Product` objects for all `product_id` values in `payload['items']`. Assert they all share the same `vendor_id`.
- The `community` for the order is the buyer's JWT `community_id`. Confirm all products belong to that community.
- Fetch the `VendorCommunity` row for `(vendor, community)`. Its `status` must be `'approved'`. Raise `ValidationError` (400) if absent or not approved.

**Step 2 — Validate delivery window**

- `delivery_window = payload['delivery_window']` must be a date that is today or in the future. Raise `ValidationError` (400) for past dates.
- Every product has a `delivery_days` field (bitmask, list, or CharField — check the actual split 01 model; use the same representation). The weekday of `delivery_window` must be present for every product in the order.
- Check that the current time in IST (`timezone.localtime(timezone.now()).time()`) is within `product.available_from` and `product.available_to` for every product. Raise `ValidationError` (400) if outside window.

**Step 3 — Validate flash sale stock**

For any product where `flash_sale_qty_remaining` is not null/zero (i.e., it is a flash sale product), check `flash_sale_qty_remaining >= requested_qty`. Raise `ValidationError` (400) — not a 409 — because this is a business rule violation detected before attempting the atomic decrement.

**Step 4 — Atomic stock decrement per item**

For each item in `payload['items']`:

1. Call `DailyInventory.objects.get_or_create(product=product, date=delivery_window)` to ensure the row exists.

2. Perform an optimistic update that only succeeds if there is capacity:
   ```python
   updated = DailyInventory.objects.filter(
       product=product,
       date=delivery_window,
       qty_ordered__lte=product.max_daily_qty - qty
   ).update(qty_ordered=F('qty_ordered') + qty)
   ```
   If `updated == 0`, raise `InsufficientStockError(f"Product {product.id} is sold out for {delivery_window}")`. Because this is inside `transaction.atomic()`, all earlier F() updates are rolled back automatically.

3. For flash sale products, perform a second atomic decrement on the product itself:
   ```python
   updated = Product.objects.filter(
       pk=product.pk,
       flash_sale_qty_remaining__gte=qty
   ).update(flash_sale_qty_remaining=F('flash_sale_qty_remaining') - qty)
   ```
   If `updated == 0`, raise `InsufficientStockError` (race condition; flash stock just sold out).

**Step 5 — Generate display_id**

```python
seq_row, _ = DailyOrderSequence.objects.select_for_update().get_or_create(
    date=delivery_window
)
seq_row.last_sequence += 1
seq_row.save()
display_id = f"NN-{delivery_window.strftime('%Y%m%d')}-{seq_row.last_sequence:04d}"
```

The `select_for_update()` ensures that concurrent orders for the same date get strictly increasing sequence numbers with no gaps or duplicates.

**Step 6 — Calculate financials**

```python
subtotal = sum(
    Decimal(str(item['quantity'])) * product.price
    for item, product in zip(payload['items'], products)
)
commission_rate = community.commission_pct / Decimal('100')
platform_commission = (subtotal * commission_rate).quantize(
    Decimal('0.01'), rounding=ROUND_HALF_UP
)
vendor_payout = subtotal - platform_commission
```

The invariant `subtotal == platform_commission + vendor_payout` holds by construction. Financial fields are never recalculated after creation.

**Step 7 — Create Order and OrderItems, commit**

Create the `Order` instance with `status=PLACED` (the FSM default). Create one `OrderItem` per item with the `unit_price` snapshot. Both `Order.save()` and all `OrderItem` bulk-creates happen within the atomic block so a failure at this step rolls back all stock decrements.

### Phase 2 — Outside `transaction.atomic()` (Razorpay call)

After the `with` block exits (transaction committed), proceed to Phase 2.

**Step 8 — Create Razorpay Payment Link**

```python
from apps.payments.services.razorpay import create_payment_link

try:
    link_data = create_payment_link(order)
    order.razorpay_payment_link_id = link_data['id']
    order.razorpay_payment_link_url = link_data['short_url']
    order.await_payment()  # FSM: PLACED → PAYMENT_PENDING
    # await_payment() body schedules cancel_unpaid_order.apply_async(countdown=1800)
    order.save()
except Exception as razorpay_exc:
    logger.error("Razorpay payment link creation failed for order %s: %s", order.pk, razorpay_exc)
    order.cancel()   # restores DailyInventory via F() per item
    order.save()
    raise ServiceUnavailable("Payment service unavailable. Please retry.") from razorpay_exc
```

The `cancel()` transition body (implemented in section 01) handles inventory restoration — no manual cleanup needed here.

**Step 9 — Return**

Return the saved `Order` instance. The view serializes it and returns HTTP 201 with `{order_id, display_id, status, payment_link_url}`.

---

## Tests

### `apps/orders/tests/test_services.py`

Uses `pytest-django`, `factory_boy` factories from section 01, and `freezegun` for time-dependent tests. Razorpay is mocked at the service function level using `unittest.mock.patch('apps.payments.services.razorpay.create_payment_link')`.

```python
# conftest / setup:
# - Use factories from apps/orders/tests/factories.py (OrderFactory, etc.)
# - Mock create_payment_link to return {'id': 'pl_test', 'short_url': 'https://rzp.io/test'}

class TestOrderPlacementServiceFinancials:
    """Verify commission calculations and financial invariants."""

    def test_valid_order_creates_order_and_items(self, ...):
        """Placing a valid order creates one Order and N OrderItems."""

    def test_subtotal_equals_commission_plus_payout(self, ...):
        """platform_commission + vendor_payout == subtotal for community commission_pct=7.50."""

    def test_rounding_half_up_various_commission_rates(self, ...):
        """Test exact paise values for commission_pct in [7, 10, 12.5] against known inputs.
        E.g. subtotal=100.01, rate=7% → commission=7.00 (not 7.0007 truncated to 7.00)."""

    def test_display_id_format(self, ...):
        """display_id matches NN-YYYYMMDD-NNNN pattern."""

    def test_display_id_sequence_increments(self, ...):
        """Two orders on the same date produce sequence 0001 and 0002."""


class TestOrderPlacementServiceValidation:
    """Input validation — all should raise before any DB write commits."""

    def test_past_delivery_window_raises_400(self, ...):
        """delivery_window in the past raises ValidationError."""

    def test_invalid_weekday_raises_400(self, ...):
        """Weekday not in product.delivery_days raises ValidationError."""

    def test_outside_available_window_raises_400(self, freezer, ...):
        """IST time outside product.available_from/available_to raises ValidationError.
        Use freezegun to freeze time to a known out-of-window time."""

    def test_unapproved_vendor_raises_400(self, ...):
        """VendorCommunity.status != 'approved' raises ValidationError."""

    def test_products_from_different_vendors_raises_400(self, ...):
        """Items spanning two vendors raises ValidationError."""

    def test_products_from_different_communities_raises_400(self, ...):
        """Items in a community different from buyer's JWT community raises ValidationError."""

    def test_flash_sale_insufficient_stock_raises_400(self, ...):
        """Flash sale product with flash_sale_qty_remaining < requested_qty raises ValidationError."""


class TestOrderPlacementServiceStockDecrement:
    """Atomic stock behaviour."""

    def test_daily_inventory_decremented_on_success(self, ...):
        """After successful order, DailyInventory.qty_ordered is incremented by order quantity."""

    def test_stock_failure_rolls_back_all_decrements(self, ...):
        """If item 2 of 2 raises InsufficientStockError, item 1's decrement is rolled back.
        DailyInventory remains at 0 for both products."""

    def test_last_unit_succeeds(self, ...):
        """Order for the last available unit succeeds (qty_ordered == max_daily_qty - 1 before)."""

    def test_exceeded_stock_raises_insufficient_stock_error(self, ...):
        """Order for max_daily_qty + 1 units raises InsufficientStockError (409 in view layer)."""


class TestOrderPlacementServicePhase2:
    """Razorpay integration and failure handling."""

    def test_successful_order_returns_payment_pending_with_link(self, ...):
        """Order status is PAYMENT_PENDING and payment_link_url is set after success."""

    def test_razorpay_failure_cancels_order_and_restores_inventory(self, ...):
        """When create_payment_link raises, order.cancel() is called and DailyInventory is restored.
        Patch create_payment_link to raise requests.exceptions.ConnectionError."""

    def test_razorpay_failure_raises_503(self, ...):
        """When create_payment_link raises, ServiceUnavailable (503) is propagated to caller."""
```

### `apps/orders/tests/test_concurrency.py`

Uses `TransactionTestCase` (not `TestCase`) because DB-level lock contention tests require real transaction isolation.

```python
import threading
from django.test import TransactionTestCase


class OrderConcurrencyTest(TransactionTestCase):
    """Tests requiring real DB transactions and row-level locks."""

    def test_last_unit_exactly_one_order_succeeds(self):
        """Two threads simultaneously order the last unit.
        Exactly one gets InsufficientStockError; the other succeeds.
        DailyInventory.qty_ordered ends at max_daily_qty (not over-sold).
        Use threading.Thread, a Barrier for synchronization, and collect results."""

    def test_display_id_sequence_no_duplicates_under_concurrency(self):
        """Ten concurrent orders for the same date produce 10 distinct display_ids.
        Use threading.Thread; collect all display_ids and assert len(set(ids)) == 10."""
```

---

## Key Invariants

- **`subtotal == platform_commission + vendor_payout` always:** Computed once at creation, never recalculated. Denormalized but stable.
- **Atomic rollback:** A stock failure on any item rolls back all prior decrements in the same order automatically. No manual cleanup code is needed.
- **Phase boundary:** The `with transaction.atomic():` block must commit before calling Razorpay. If Razorpay is called inside the block, the DB locks are held for the duration of the external HTTP call.
- **`select_for_update` on DailyOrderSequence:** This row lock is the only mechanism preventing duplicate display IDs under concurrency. Do not move it outside the atomic block.
- **IST for delivery window validation:** Use `timezone.localtime()` for `available_from`/`available_to` comparisons. `available_from`/`available_to` are IST `TimeField` values. `timezone.now()` (UTC) would give wrong results without localtime conversion.
- **Unit price snapshot:** `OrderItem.unit_price` must be copied from `product.price` at order creation time, not referenced by FK. Price changes after order placement must not affect existing orders.
- **`vendor_profile` accessor:** The split 03 Vendor model uses `related_name='vendor_profile'` on a `OneToOne` to User. Verify the actual `related_name` in `apps/vendors/models.py` before writing service code — there is a known ambiguity documented in the plan.

---

## Error Codes Summary

| Condition | Exception | HTTP status (view layer) |
|-----------|-----------|--------------------------|
| Invalid delivery window / vendor not approved / outside order window | `ValidationError` | 400 |
| Flash sale pre-check fails | `ValidationError` | 400 |
| DailyInventory atomic update returns 0 rows | `InsufficientStockError` | 409 |
| Razorpay call fails | `ServiceUnavailable` | 503 |

The view (section 07) is responsible for mapping these exceptions to HTTP responses. The service raises only the appropriate exceptions; it does not construct HTTP responses.