# TDD Plan: 05-Ordering-Payments

## Testing Stack
- **Framework:** pytest + pytest-django + factory_boy + freezegun
- **Celery:** `CELERY_TASK_ALWAYS_EAGER = True` in test settings — tasks run synchronously in tests
- **Concurrency:** Use `TransactionTestCase` (NOT `TestCase`) for lock-contention tests
- **Razorpay:** Mock at the service function level (`unittest.mock.patch`) — never hit real Razorpay in tests
- **Test layout:** `apps/orders/tests/` and `apps/payments/tests/`

---

## Section 1: Models

### Factories (write first, used by all other tests)

```
# factories.py — apps/orders/tests/
# OrderFactory: status=PLACED, buyer/vendor/community from prior split factories
# OrderItemFactory: linked to Order, product snapshot fields
# DailyOrderSequenceFactory: date=today, last_sequence=0
# WebhookEventFactory (in payments tests): unique event_id, event_type='payment.captured'
```

### Model field tests (`test_models.py`)

```
# Test: Order.subtotal == platform_commission + vendor_payout invariant on a factory instance
# Test: Order.display_id enforces unique constraint at DB level (two orders with same display_id raise IntegrityError)
# Test: Order.razorpay_idempotency_key is auto-generated UUID and unique across rows
# Test: OrderItem.subtotal == quantity * unit_price
# Test: Order.delivered_at is None by default; set by mark_delivered() transition
# Test: Order.cancelled_at is None by default; set by cancel() transition
# Test: DailyOrderSequence date field is unique (duplicate date raises IntegrityError)
```

### FSM transition tests (`test_models.py`)

```
# Test: PLACED → PAYMENT_PENDING via await_payment() succeeds
# Test: PLACED → CONFIRMED directly raises TransitionNotAllowed (FSM protected)
# Test: PAYMENT_PENDING → CONFIRMED via confirm_payment() succeeds
# Test: CONFIRMED → READY via mark_ready() succeeds
# Test: READY → DELIVERED via mark_delivered() succeeds
# Test: PLACED → CANCELLED via cancel() succeeds; cancelled_at is set
# Test: PAYMENT_PENDING → CANCELLED via cancel() succeeds
# Test: CONFIRMED → CANCELLED directly raises TransitionNotAllowed
# Test: DELIVERED → DISPUTED via raise_dispute() succeeds when within 24h of delivered_at
# Test: raise_dispute() raises TransitionNotAllowed when delivered_at is >24h ago (use freezegun)
# Test: DISPUTED → DELIVERED via resolve_dispute() succeeds
# Test: DISPUTED → REFUNDED via process_refund() succeeds
# Test: CONFIRMED → DISPUTED via escalate_to_dispute() succeeds (vendor cancel path)
# Test: mark_delivered() proceeds even when razorpay_transfer_id is blank (logs alert, no exception)
# Test: ConcurrentTransitionMixin — two simultaneous confirm_payment() calls raise RetryNeeded on second
```

---

## Section 2: OrderPlacementService

### Service unit tests (`test_services.py`)

```
# Test: Placing a valid order creates Order + OrderItems with correct financial calculations
# Test: platform_commission + vendor_payout == subtotal for various commission_pct values (7%, 10%, 12.5%)
# Test: ROUND_HALF_UP rounding on commission — verify exact paise values for known inputs
# Test: delivery_window on a valid weekday passes; on an invalid weekday returns 400 (ValidationError)
# Test: delivery_window in the past returns 400
# Test: Order is placed only when IST time is within available_from/available_to (use freezegun)
# Test: VendorCommunity.status != 'approved' returns 400 (vendor not approved in community)
# Test: Products from different vendors raises 400
# Test: Products from different communities raises 400
# Test: display_id format is 'NN-YYYYMMDD-NNNN' (four-digit sequence)
# Test: display_id sequence increments correctly across multiple orders for same date
# Test: Phase 1 transaction rolls back if stock check fails (DailyInventory not decremented)
# Test: Phase 2 Razorpay failure cancels the order and restores DailyInventory (mock create_payment_link to raise)
# Test: Successful order returns Order with status=PAYMENT_PENDING and payment_link_url set
```

### Concurrency tests (`test_concurrency.py` — use TransactionTestCase)

```
# Test: Two simultaneous orders for last unit — exactly one succeeds, one raises InsufficientStockError (409)
#   Use threading.Thread or async to issue concurrent requests
# Test: DailyOrderSequence sequence is strictly monotonic under concurrent orders (no duplicate display_ids)
```

---

## Section 3: Razorpay Services

### Service tests (`apps/payments/tests/test_services.py`)

All Razorpay calls mocked via `unittest.mock.patch('apps.payments.services.razorpay.client')`.

```
# Test: create_payment_link builds payload with correct amount (paise), currency, reference_id
# Test: create_payment_link uses str(order.razorpay_idempotency_key) as reference_id
# Test: create_payment_link stores payment_link_id and payment_link_url on order
# Test: create_route_transfer sends correct vendor account, amount in paise, on_hold=True
# Test: create_route_transfer returns transfer_id string on success
# Test: create_route_transfer returns None on Razorpay exception (does not re-raise)
# Test: release_transfer_hold sends PATCH with on_hold=0 to correct transfer_id
# Test: release_transfer_hold returns True on success, False on 4xx (already settled)
```

---

## Section 4: Razorpay Webhook Handler

### Webhook handler tests (`apps/payments/tests/test_webhook.py`)

```
# Test: Valid signature + payment.captured → order transitions to CONFIRMED
# Test: Invalid signature → returns HTTP 400
# Test: Missing X-Razorpay-Signature header → returns HTTP 400
# Test: Duplicate event_id (WebhookEvent already exists) → returns HTTP 200, no double processing
# Test: payment.captured with unknown reference_id → logs and returns HTTP 200 (no crash)
# Test: payment.captured for order not in PAYMENT_PENDING → returns HTTP 200, no state change
# Test: payment.captured → razorpay_payment_id is stored on order before confirm_payment() is called
# Test: payment.captured → create_route_transfer is called with correct order
# Test: payment.captured → hold_release_at is set to approximately now+24h (use freezegun)
# Test: payment.captured with transfer failure (create_route_transfer returns None) → order still CONFIRMED
# Test: payment.failed → order transitions to CANCELLED
# Test: payment.failed → DailyInventory qty_ordered is restored for each item (via cancel() body)
# Test: unknown event type → logged, returns HTTP 200 (no crash)
# Test: reference_id is extracted from payload['payload']['payment']['entity']['notes']['reference_id']
# Test: handler exception is caught, returns HTTP 200 (prevents Razorpay retries)
```

---

## Section 5: Celery Tasks

### Task tests (`apps/payments/tests/test_tasks.py`)

With `CELERY_TASK_ALWAYS_EAGER = True`, tasks run synchronously.

```
# cancel_unpaid_order:
# Test: Order in PAYMENT_PENDING with no payment_id → cancelled, inventory restored
# Test: Order already CONFIRMED (paid) → task returns silently, no state change
# Test: Order already CANCELLED → task returns silently
# Test: Order in PAYMENT_PENDING but razorpay_payment_id is set → task returns silently (race guard)

# release_payment_hold:
# Test: Order with transfer_on_hold=True and not DISPUTED → release_transfer_hold() is called
# Test: Order with status=DISPUTED → task returns silently (hold preserved)
# Test: Order with transfer_on_hold=False → task returns silently (already released)

# check_missed_drop_windows:
# Test: Orders with delivery_window=yesterday and status=CONFIRMED → VendorCommunity.missed_window_count incremented
# Test: Orders with delivery_window=yesterday and status=READY → VendorCommunity.missed_window_count incremented
# Test: Orders with delivery_window=yesterday and status=DELIVERED → not counted
# Test: Multiple missed orders for same (vendor, community) pair → single increment (F() grouped update)
# Test: Orders from different communities increment the correct VendorCommunity rows
```

---

## Section 6: Order Permissions

### Permission tests (`apps/orders/tests/test_views.py`)

```
# Test: IsOrderBuyer passes for the order's buyer user
# Test: IsOrderBuyer fails for a different authenticated user
# Test: IsOrderVendor passes for the order's vendor user
# Test: IsOrderVendor fails for the buyer attempting vendor actions
# Test: IsOrderCommunityAdmin passes for admin with matching community_id in JWT
# Test: IsOrderCommunityAdmin fails for admin with different community_id
```

---

## Section 7: API Endpoints

### Buyer endpoints (`apps/orders/tests/test_views.py`)

```
# POST /api/v1/orders/ (Place Order):
# Test: Unauthenticated request → 401
# Test: Authenticated non-resident → 403
# Test: Valid payload → 201 with order_id, display_id, status='payment_pending', payment_link_url
# Test: Invalid delivery_window weekday → 400
# Test: Out-of-stock product → 409
# Test: vendor not approved in community → 400

# GET /api/v1/orders/?status= (List):
# Test: Returns only the authenticated buyer's orders (not another buyer's)
# Test: status filter works correctly

# GET /api/v1/orders/{id}/ (Detail):
# Test: Buyer can retrieve own order → 200
# Test: Vendor can retrieve their order → 200
# Test: Unrelated user → 403
# Test: Community admin → 200

# POST /api/v1/orders/{id}/cancel/ (Cancel):
# Test: Buyer cancels PLACED order → 200, status=CANCELLED
# Test: Buyer cancels PAYMENT_PENDING order → 200, status=CANCELLED
# Test: Buyer attempts to cancel CONFIRMED order → 403
# Test: Non-buyer attempts cancel → 403

# POST /api/v1/orders/{id}/dispute/ (Raise Dispute):
# Test: Buyer raises dispute within 24h of delivered_at → 200, status=DISPUTED (use freezegun)
# Test: Buyer raises dispute >24h after delivered_at → 400
# Test: Non-DELIVERED order → 400
```

### Vendor endpoints

```
# GET /api/v1/vendors/orders/?date=&status= (Vendor Order List):
# Test: Returns only orders for authenticated vendor
# Test: date filter narrows to delivery_window

# POST /api/v1/orders/{id}/ready/ (Mark Ready):
# Test: Vendor marks CONFIRMED order as READY → 200
# Test: Buyer attempts mark_ready → 403

# POST /api/v1/orders/{id}/deliver/ (Mark Delivered):
# Test: Vendor marks READY order as DELIVERED → 200, delivered_at is set
# Test: vendor.completed_delivery_count incremented
# Test: DELIVERED order with transfer → release_transfer_hold called
# Test: DELIVERED order without transfer → proceeds, MANUAL_PAYOUT_REQUIRED logged

# POST /api/v1/orders/{id}/vendor-cancel/ (Vendor Cancel):
# Test: Vendor cancels CONFIRMED order → 200, status=DISPUTED

# GET /api/v1/vendors/payouts/ (Payout Dashboard):
# Test: pending_amount is sum of vendor_payout for on_hold=True orders for this vendor
# Test: settled_amount is sum for on_hold=False orders in current month
# Test: transactions list contains expected fields
```

### Admin endpoints

```
# POST /api/v1/orders/{id}/resolve-dispute/ (Resolve Dispute):
# Test: Community admin resolves DISPUTED order → 200, status=DELIVERED

# POST /api/v1/orders/{id}/process-refund/ (Process Refund):
# Test: Community admin processes refund → 200, status=REFUNDED
# Test: Razorpay refund API is called with correct payment_id and amount
```

---

## Section 8: Serializers

### Serializer tests (inline in `test_views.py` or `test_serializers.py`)

```
# Test: PlaceOrderSerializer rejects missing vendor_id → ValidationError
# Test: PlaceOrderSerializer rejects empty items list → ValidationError
# Test: OrderSerializer includes payment_link_url only when status=PAYMENT_PENDING
# Test: OrderItemSerializer snapshot fields (unit_price) do not change when product price changes
# Test: PayoutTransactionSerializer returns all required fields
```

---

## Section 9: Django Admin

No automated tests required — admin is verified manually. Standard Django admin registration is assumed to work.

---

## Section 10: Notifications Stubs

```
# Test: Each stub task is importable and callable without error
# Test: Each stub task accepts an order_id argument and returns None
# (Stubs do nothing — tests just verify they don't crash and have the right signature)
```
