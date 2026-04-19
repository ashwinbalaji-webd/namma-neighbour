# Implementation Plan: 05-Ordering-Payments

## What We Are Building

This split builds the transactional core of NammaNeighbor: the `orders` and `payments` Django apps. Residents pre-order products from approved vendors during daily drop windows, pay via Razorpay Payment Links, and funds are held in Razorpay Route escrow until the vendor confirms delivery. The split covers order placement (with atomic inventory decrement), FSM-driven order lifecycle, Razorpay webhook processing, auto-cancellation of unpaid orders, dispute handling, and a seller payout dashboard.

This split does **not** build push/SMS notification delivery (stubs only) or product reviews (split 07).

---

## Project Context

NammaNeighbor runs on Django 5.x + DRF 3.15, PostgreSQL 16, Celery 5 + Redis 7, and AWS S3. Auth is phone-OTP → JWT with roles (`resident`, `vendor`, `community_admin`) and `community_id` embedded. Permission classes in `apps/core/permissions.py` read from JWT claims.

**Prerequisites from prior splits:**
- `apps/core/`: `TimestampedModel`, base permissions (`IsResidentOfCommunity`, `IsVendorOfCommunity`, `IsCommunityAdmin`), JWT setup, custom exception handler
- `apps/communities/`: `Community` (has `commission_pct` DecimalField, default 7.50) and `ResidentProfile` (OneToOne to User, `related_name='resident_profile'`)
- `apps/vendors/`: `Vendor` (OneToOne to User, `related_name='vendor_profile'`; has `razorpay_account_id`, `completed_delivery_count`). `VendorCommunity` join table has `missed_window_count` (per-community counter used by split 03 auto-delist logic).
- `apps/catalogue/`: `Product` (has `delivery_days`, `available_from/to`, `max_daily_qty`, `flash_sale_qty_remaining`), `DailyInventory` (has `qty_ordered`, unique on `(product, date)`)

**New dependencies to add to `pyproject.toml`:**
- `django-fsm-2` — maintained fork of `django-fsm` (original archived April 2024); API-compatible
- `razorpay` — official Razorpay Python SDK

---

## Directory Structure

```
apps/
  orders/
    __init__.py
    apps.py
    models.py          # Order, OrderItem, DailyOrderSequence
    serializers.py     # OrderSerializer, OrderItemSerializer, PlaceOrderSerializer
    views.py           # OrderViewSet, BuyerOrderViewSet, VendorOrderViewSet
    permissions.py     # IsOrderBuyer, IsOrderVendor, IsOrderCommunityAdmin
    services.py        # OrderPlacementService (atomic transaction logic)
    urls.py
    admin.py
    tests/
      conftest.py
      factories.py
      test_models.py
      test_views.py
      test_services.py
      test_concurrency.py
  payments/
    __init__.py
    apps.py
    models.py          # WebhookEvent
    views.py           # RazorpayWebhookView
    services/
      razorpay.py      # create_payment_link(), create_route_transfer(), release_transfer_hold()
    tasks.py           # release_payment_hold, cancel_unpaid_order, check_missed_drop_windows
    urls.py
    tests/
      conftest.py
      test_webhook.py
      test_services.py
      test_tasks.py
  notifications/
    __init__.py
    apps.py
    tasks.py           # STUBS: notify_vendor_order_received, notify_buyer_*, etc.
```

---

## Section 1: Models

### Order

`Order` is the central model. It references `ResidentProfile` (buyer), `Vendor`, and `Community`. All financial fields are `DecimalField` — the invariant `subtotal == platform_commission + vendor_payout` must always hold.

**FSM field:** `status = FSMField(default=OrderStatus.PLACED, protected=True)` using `django-fsm-2`. The `protected=True` prevents direct assignment; all status changes go through decorated `@transition` methods.

**Status choices (MVP — OUT_FOR_DELIVERY removed):**
`PLACED`, `PAYMENT_PENDING`, `CONFIRMED`, `READY`, `DELIVERED`, `CANCELLED`, `DISPUTED`, `REFUNDED`

**Key fields:**
- `buyer` FK to ResidentProfile (on_delete=PROTECT, related_name='orders')
- `vendor` FK to Vendor (on_delete=PROTECT, related_name='received_orders')
- `community` FK to Community (on_delete=PROTECT)
- `display_id` CharField(unique=True) — human-readable NN-YYYYMMDD-NNNN format; globally unique by construction
- `subtotal`, `platform_commission`, `vendor_payout` — all DecimalField(10,2)
- `delivery_window` DateField — the ordered delivery date
- `delivery_notes` TextField(blank=True)
- `razorpay_payment_link_id`, `razorpay_payment_link_url` — set at order creation
- `razorpay_payment_id` — set by webhook on payment capture
- `razorpay_transfer_id` — set after Route transfer created
- `transfer_on_hold` BooleanField(default=True)
- `razorpay_idempotency_key` UUIDField(default=uuid4, unique=True) — used as `reference_id` in payment link
- `hold_release_at` DateTimeField(null=True) — when auto-release fires
- `delivered_at` DateTimeField(null=True, blank=True) — set by `mark_delivered()` transition; used for 24h dispute window
- `cancelled_at` DateTimeField(null=True, blank=True) — set by `cancel()` transition
- `dispute_reason` TextField(blank=True)
- `dispute_raised_at` DateTimeField(null=True)

**DB indexes:** `(vendor, delivery_window, status)`, `(buyer, status)`, `(razorpay_payment_id)`, `(display_id)`

**Concurrency:** Use `ConcurrentTransitionMixin` from django-fsm-2 for optimistic FSM locking. This adds a version field and raises `RetryNeeded` on concurrent transitions to the same order — prevents double-confirm from duplicate webhooks.

**FSM transitions:**

| Method | Source | Target | Who calls it |
|--------|--------|--------|--------------|
| `await_payment()` | PLACED | PAYMENT_PENDING | OrderPlacementService after creating payment link |
| `confirm_payment()` | PAYMENT_PENDING | CONFIRMED | Webhook handler on payment.captured |
| `mark_ready()` | CONFIRMED | READY | Vendor endpoint |
| `mark_delivered()` | READY | DELIVERED | Vendor endpoint |
| `cancel()` | PLACED, PAYMENT_PENDING | CANCELLED | Buyer endpoint |
| `escalate_to_dispute()` | CONFIRMED, READY | DISPUTED | Vendor cancel endpoint (not direct cancel) |
| `raise_dispute()` | DELIVERED | DISPUTED | Buyer endpoint (within 24h of delivery) |
| `resolve_dispute()` | DISPUTED | DELIVERED | Community admin endpoint |
| `process_refund()` | DISPUTED | REFUNDED | Community admin endpoint |

**Guards:**
- `raise_dispute()` has a condition checking `timezone.now() - order.delivered_at <= timedelta(hours=24)` (uses `delivered_at`, not `updated_at`, to prevent any subsequent save from extending the window)
- `mark_delivered()` has NO hard guard on `razorpay_transfer_id` — see transition body below

**Signals / side effects** go in the transition method body (not in guards):
- `await_payment()`: schedule `cancel_unpaid_order.apply_async(args=[order.pk], countdown=1800)`
- `confirm_payment()`: create Route transfer, schedule `release_payment_hold.apply_async(args=[order.pk], eta=now+24h)`, call notification stubs
- `mark_ready()`: call notification stub (buyer — "your order is packed")
- `mark_delivered()`: set `order.delivered_at = timezone.now()`. If `razorpay_transfer_id` is set: call `release_transfer_hold(order)`, update `transfer_on_hold=False`. If blank: log "MANUAL_PAYOUT_REQUIRED" alert with order ID (ops must handle). In both cases: increment `vendor.completed_delivery_count`, call notification stub.
- `cancel()`: set `order.cancelled_at = timezone.now()`. Restore DailyInventory for each item via F() decrement on `qty_ordered`. If `razorpay_payment_id` is set, trigger Razorpay refund.
- `process_refund()`: trigger Razorpay refund

### OrderItem

`OrderItem` is a snapshot of the ordered product at order time.

**Fields:**
- `order` FK to Order (on_delete=CASCADE, related_name='items')
- `product` FK to Product (on_delete=PROTECT)
- `quantity` PositiveIntegerField
- `unit_price` DecimalField(10,2) — snapshot at order time (not live price)
- `subtotal` DecimalField(10,2) — quantity × unit_price

### DailyOrderSequence

Helper model to generate per-date order display IDs.

**Fields:**
- `date` DateField (unique=True)
- `last_sequence` PositiveIntegerField(default=0)

**Usage:** Inside `OrderPlacementService`, within the same `transaction.atomic()` block, acquire a row lock via `DailyOrderSequence.objects.select_for_update().get_or_create(date=delivery_window)`, increment `last_sequence`, save, and use it to format `display_id`.

### WebhookEvent (in payments app)

Idempotency log for Razorpay webhook deliveries.

**Fields:**
- `event_id` CharField(255, unique=True, db_index=True) — from `X-Razorpay-Event-ID` header
- `event_type` CharField(100)
- `payload` JSONField
- `created_at` auto

---

## Section 2: OrderPlacementService (Atomic Transaction)

All order placement logic lives in `apps/orders/services.py` as a static method `OrderPlacementService.place_order(user, payload)`. This keeps the view thin and makes the logic testable in isolation.

**The method uses two phases** — the Razorpay API call is outside the transaction to avoid holding DB locks during an external HTTP call.

### Phase 1 — `transaction.atomic()` (DB operations only)

1. **Validate vendor and community:** All items must belong to the same vendor. Fetch the `VendorCommunity` row for `(vendor, community)` where `community` comes from each product's `product.community` (which must equal the buyer's JWT `community_id`). The `VendorCommunity.status` must be `'approved'`. Raise 400 if vendor is not approved in this community or if products span multiple vendors/communities.

2. **Validate delivery window:** `payload.delivery_window` must be a date in the future (or today). The weekday of `delivery_window` must be in every product's `delivery_days`. The current IST time must be within each product's `available_from`/`available_to` window.

3. **Validate flash sales:** For flash sale products, check `flash_sale_qty_remaining >= requested_qty`.

4. **Atomic stock decrement per item:** For each item, perform an F() optimistic update on `DailyInventory`:
   - `get_or_create(product=product, date=delivery_window)` to ensure the row exists
   - `filter(product=product, date=delivery_window, qty_ordered__lte=product.max_daily_qty - qty).update(qty_ordered=F('qty_ordered') + qty)`
   - If `updated == 0`: raise `InsufficientStockError` — the entire transaction rolls back, restoring all prior decrements atomically
   - For flash sale products: additionally `filter(pk=product_id, flash_sale_qty_remaining__gte=qty).update(flash_sale_qty_remaining=F('flash_sale_qty_remaining') - qty)`

5. **Generate display_id:** Select-for-update on `DailyOrderSequence`, increment sequence, format `NN-{YYYYMMDD}-{seq:04d}`.

6. **Calculate financials:**
   - `subtotal` = sum of all item subtotals
   - `commission_rate` = `community.commission_pct / Decimal('100')`
   - `platform_commission` = `(subtotal * commission_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)`
   - `vendor_payout` = `subtotal - platform_commission`

7. **Create Order (status=PLACED) and OrderItems.** Commit transaction.

### Phase 2 — Outside `transaction.atomic()` (Razorpay call)

8. **Generate Razorpay Payment Link** via `create_payment_link(order)` service function. If Razorpay call succeeds: store `razorpay_payment_link_id` and `razorpay_payment_link_url` on the order, then call `order.await_payment()` (transitions to PAYMENT_PENDING, schedules 30-minute auto-cancel). If Razorpay call fails: call `order.cancel()` (which restores inventory), raise a 503 to the buyer.

9. **Return** the saved Order instance.

---

## Section 3: Razorpay Services

`apps/payments/services/razorpay.py` — three functions, each using a module-level cached Razorpay client.

### `create_payment_link(order) -> dict`

Creates a Razorpay Payment Link. Payload:
- `amount`: `int(order.subtotal * 100)` (paise)
- `currency`: "INR"
- `description`: order description including vendor display name
- `customer`: buyer's name and phone
- `notify`: `{"sms": True}`
- `callback_url`: `{APP_BASE_URL}/api/v1/payments/callback/`
- `reference_id`: `str(order.razorpay_idempotency_key)` — used to look up the order in the webhook

### `create_route_transfer(order) -> str`

Creates a Route transfer from the captured payment to the vendor's linked account. Called inside the `payment.captured` webhook handler.

- Uses `client.payment.transfer(payment_id, {"transfers": [...]})` 
- `account`: `order.vendor.razorpay_account_id`
- `amount`: `int(order.vendor_payout * 100)`
- `on_hold`: `True`
- Returns `transfer_id` (string)

**Error handling:** If transfer creation fails (e.g., vendor account suspended), log the error with order ID and return `None`. The caller must check and store `None` — order stays CONFIRMED, ops team is alerted via logging/monitoring. Do not cancel the order.

### `release_transfer_hold(order) -> bool`

Makes a raw PATCH request (the Python SDK has no dedicated method) to `https://api.razorpay.com/v1/transfers/{transfer_id}` with `{"on_hold": 0}`. If the transfer is already settled (Razorpay returns 4xx), log the response and return `False` — this is expected when the 24h Celery task fires after manual delivery confirmation. Return `True` on success.

---

## Section 4: Razorpay Webhook Handler

`RazorpayWebhookView` at `POST /api/v1/payments/webhook/`. No authentication (Razorpay cannot provide tokens); verified by HMAC signature. Set `authentication_classes = []` and `permission_classes = [AllowAny]` on the view — this bypasses DRF's SessionAuthentication (which enforces CSRF) and is the correct pattern for externally-called webhook endpoints.

**Processing steps:**

1. Read `request.body` (raw bytes) and `X-Razorpay-Signature` header **before any JSON parsing**.
2. Call `client.utility.verify_webhook_signature(raw_body.decode("utf-8"), signature, RAZORPAY_WEBHOOK_SECRET)`. On `SignatureVerificationError`: return HTTP 400.
3. Parse `json.loads(raw_body)`.
4. Extract `event_id = request.META.get("HTTP_X_RAZORPAY_EVENT_ID", "")`.
5. Try `WebhookEvent.objects.create(event_id=event_id, event_type=event["event"], payload=payload)` inside `transaction.atomic()`. On `IntegrityError` (duplicate delivery): return HTTP 200 immediately.
6. Route to handler based on `event["event"]`:
   - `payment.captured` → `_handle_payment_captured(payload)`
   - `payment.failed` → `_handle_payment_failed(payload)`
   - (others logged and ignored)
7. Wrap handler call in try/except — log exceptions but always return HTTP 200 (prevents Razorpay retries for transient failures).

### `_handle_payment_captured(payload)`

1. Extract `reference_id` from `payload["payload"]["payment"]["entity"]["notes"]["reference_id"]`. When a Payment Link is created with `reference_id`, Razorpay includes it in the payment entity's `notes` dictionary in the webhook payload.
2. Find Order by `razorpay_idempotency_key = UUID(reference_id)`. If not found: log and return.
3. **Idempotency check:** if `order.status != OrderStatus.PAYMENT_PENDING`: return (already processed).
4. Store `razorpay_payment_id` on order and save immediately. This is the idempotency anchor — `cancel_unpaid_order` task checks for a blank `razorpay_payment_id` before cancelling, so this save prevents the race window.
5. Call `order.confirm_payment()` and `order.save()` (transitions to CONFIRMED). The transition body schedules `release_payment_hold.apply_async(args=[order.pk], eta=now+24h)`.
6. Set `hold_release_at = timezone.now() + timedelta(hours=24)`, save.
7. Call `create_route_transfer(order)` — store result in `razorpay_transfer_id`. If result is `None` (transfer failed), log "TRANSFER_CREATION_FAILED" alert with order ID but continue.
8. Call notification stubs.

### `_handle_payment_failed(payload)`

1. Find order by idempotency key.
2. If `order.status == OrderStatus.PAYMENT_PENDING`: call `order.cancel()`, save. The `cancel()` transition body handles inventory restoration atomically (DailyInventory F() decrement per item).
3. Notify buyer (stub).

---

## Section 5: Celery Tasks

### `cancel_unpaid_order(order_id)`

Queue: `payments`. Scheduled 30 minutes after `await_payment()`.
- Fetch order. If `order.status != PAYMENT_PENDING`: return silently (already paid or cancelled).
- If `order.razorpay_payment_id` is set (non-blank): return silently — payment was captured but the webhook handler has not yet finished transitioning the order to CONFIRMED. Do not cancel; the webhook will complete the transition.
- Call `order.cancel()`, save. The `cancel()` transition body handles inventory restoration atomically.

### `release_payment_hold(order_id)`

Queue: `payments`. Scheduled 24h after `payment.captured`.
- Fetch order. If `order.status == DISPUTED` or `transfer_on_hold=False`: return silently.
- Call `release_transfer_hold(order)`. Log result regardless of success/failure.

### `check_missed_drop_windows()`

Queue: `payments`. Beat schedule: daily at 01:00 IST.
- Find all orders with `delivery_window = yesterday` AND `status` in `[CONFIRMED, READY]`.
- Group missed orders by `(vendor_id, community_id)` pairs.
- For each pair: increment `VendorCommunity.missed_window_count` using `F()` update. This is the counter that drives split 03's auto-delist logic (`auto_delist_missed_windows`).
- Log count of affected `(vendor, community)` pairs.

---

## Section 6: Order Permissions

`apps/orders/permissions.py`:

### `IsOrderBuyer`

Object-level permission. Passes if `request.user == obj.buyer.user`.

### `IsOrderVendor`

Object-level permission. Passes if `request.user == obj.vendor.user`.

### `IsOrderCommunityAdmin`

Object-level permission. Passes if user has `community_admin` JWT role AND `request.auth['community_id'] == obj.community_id`.

---

## Section 7: API Endpoints

### Buyer Endpoints

**Place Order:** `POST /api/v1/orders/`
- Permission: `IsResidentOfCommunity`
- Calls `OrderPlacementService.place_order()`
- Returns: `{order_id, display_id, status, payment_link_url}`

**List My Orders:** `GET /api/v1/orders/?status=&page=`
- Permission: `IsResidentOfCommunity`
- Filtered to buyer's own orders by `get_queryset()`

**Get Order Detail:** `GET /api/v1/orders/{order_id}/`
- Permission: `IsOrderBuyer | IsOrderVendor | IsOrderCommunityAdmin` (any of the three)

**Cancel Order:** `POST /api/v1/orders/{order_id}/cancel/`
- Permission: `IsOrderBuyer`
- Validates buyer can cancel: only from PLACED or PAYMENT_PENDING
- On CONFIRMED/READY: returns 403 (buyer cannot cancel post-payment; must raise dispute)

**Raise Dispute:** `POST /api/v1/orders/{order_id}/dispute/`
- Permission: `IsOrderBuyer`
- Validates status is DELIVERED and within 24h
- Payload: `{"reason": "..."}`

### Vendor Endpoints

**List Vendor Orders:** `GET /api/v1/vendors/orders/?date=&status=&page=`
- Permission: `IsVendorOfCommunity`
- Filtered to vendor's received orders

**Consolidated Order Sheet:** `GET /api/v1/vendors/orders/consolidated/?date=`
- Permission: `IsVendorOfCommunity`
- Returns orders grouped by building/tower for the date (from split 04 stub URL, now implemented)

**Mark Order Ready:** `POST /api/v1/orders/{order_id}/ready/`
- Permission: `IsOrderVendor`
- Calls `order.mark_ready()`, notifies buyer stub

**Mark Order Delivered:** `POST /api/v1/orders/{order_id}/deliver/`
- Permission: `IsOrderVendor`
- Calls `order.mark_delivered()` which releases Route hold, increments delivery count

**Vendor Cancel (CONFIRMED/READY):** `POST /api/v1/orders/{order_id}/vendor-cancel/`
- Permission: `IsOrderVendor`
- Calls `order.escalate_to_dispute()` — goes to DISPUTED, community admin handles
- Payload: `{"reason": "..."}`

**Payout Dashboard:** `GET /api/v1/vendors/payouts/`
- Permission: `IsVendorOfCommunity`
- `pending_amount`: sum of `vendor_payout` where `transfer_on_hold=True`
- `settled_amount`: sum of `vendor_payout` where `transfer_on_hold=False` and current month
- `transactions`: list of Order records with payout info

### Community Admin Endpoints

**Resolve Dispute (vendor right):** `POST /api/v1/orders/{order_id}/resolve-dispute/`
- Permission: `IsOrderCommunityAdmin`
- Calls `order.resolve_dispute()` → status back to DELIVERED

**Process Refund (buyer right):** `POST /api/v1/orders/{order_id}/process-refund/`
- Permission: `IsOrderCommunityAdmin`
- Calls Razorpay refund with `reverse_all=1` then `order.process_refund()`

---

## Section 8: Serializers

**`PlaceOrderSerializer`** (write-only): Validates `vendor_id`, `delivery_window`, `items[]` (product_id + quantity), `delivery_notes`. Does NOT include financial fields — those are computed server-side.

**`OrderItemSerializer`**: `id`, `product_id`, `product_name` (snapshot), `quantity`, `unit_price`, `subtotal`

**`OrderSerializer`** (read): All Order fields. Nested `items` (OrderItemSerializer). Includes `payment_link_url` (only present when status is PAYMENT_PENDING).

**`PayoutTransactionSerializer`**: `order_id`, `display_id`, `vendor_payout`, `transfer_on_hold`, `hold_release_at`, `delivery_window`

---

## Section 9: Django Admin

`OrderAdmin`: list by community, vendor, status, delivery_window. Inline for OrderItems (read-only). Custom actions: bulk-cancel selected orders (admin-only override).

`WebhookEventAdmin`: list by event_type, created_at. Read-only (no edits).

---

## Section 10: Notifications Stubs

`apps/notifications/tasks.py` — create this file with these empty Celery task stubs (queue='notifications'):
- `notify_vendor_order_received(order_id)` — "New order received"
- `notify_buyer_payment_confirmed(order_id)` — "Payment confirmed"
- `notify_buyer_order_ready(order_id)` — "Order packed and ready"
- `notify_buyer_order_delivered(order_id)` — "Order delivered"
- `notify_community_admin_dispute_raised(order_id)` — "Dispute raised, review needed"
- `notify_buyer_order_cancelled(order_id)` — "Order cancelled"

Call each from the appropriate FSM transition body. Tasks do nothing yet; split 06+ fills them in.

---

## Key Invariants and Edge Cases

**`subtotal == platform_commission + vendor_payout` always:** Computed once at order creation, never recalculated. Stored as denormalized but stable values.

**Atomic rollback on stock failure:** The entire `transaction.atomic()` in `OrderPlacementService` means a stock failure on item 3 automatically restores items 1 and 2. No manual cleanup needed.

**Webhook idempotency is the guard, not the FSM transition guard:** The `WebhookEvent.event_id` unique constraint is the first line of defense against duplicate webhooks. The `order.status != PAYMENT_PENDING` check inside `_handle_payment_captured` is a belt-and-suspenders backup for the case where the unique constraint is bypassed.

**ConcurrentTransitionMixin adds version-based optimistic locking to FSM transitions.** This protects against duplicate `confirm_payment()` calls (e.g., two concurrent webhook deliveries before the idempotency table write). The second call raises `RetryNeeded` and the caller returns 200 (it already processed).

**Release on duplicate delivery confirmation is a no-op:** `release_transfer_hold()` catches 4xx from Razorpay (transfer already settled) and logs — does not raise. Both the manual vendor confirmation path and the 24h Celery path call this function; one will succeed and one will receive a 4xx.

**Order display_id is globally unique:** The `NN-YYYYMMDD-NNNN` format embeds the date, making it globally unique by construction. A `unique=True` DB constraint enforces this. For unambiguous programmatic lookups, prefer the database PK or `razorpay_idempotency_key` — `display_id` is for human-facing display only.

**Unit prices are snapshots:** `OrderItem.unit_price` is set at order creation time. If a vendor later changes a product price, existing orders are not affected. This is intentional.

**IST for all time comparisons:** Use `timezone.localtime()` for order window validation (available_from/to fields are IST TimeFields). Use `timezone.now()` for Razorpay timestamps and Celery ETAs (UTC-aware DateTimeField).

**`vendor_profile` accessor:** Access the Vendor model via `request.user.vendor_profile` (OneToOne reverse with `related_name='vendor_profile'`). Verify the actual related_name in the split 03 Vendor model before implementation — there is a known split 04 ambiguity around whether the accessor is `vendor_profile` or `vendor_profile_profile`.

**Buyer has no self-service escape from CONFIRMED:** A buyer cannot cancel a CONFIRMED or READY order (FSM blocks it) and cannot raise a dispute until DELIVERED (dispute requires `DELIVERED` source state). If a vendor fails to deliver, the buyer must contact the vendor to use `escalate_to_dispute()` or escalate to platform support. This is an intentional MVP limitation — document in the mobile app help text.
