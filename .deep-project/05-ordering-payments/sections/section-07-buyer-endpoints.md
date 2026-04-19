Now I have all the context needed to generate the section content. Let me produce the complete, self-contained section for `section-07-buyer-endpoints`.

# Section 07: Buyer Endpoints

## Overview

This section implements the buyer-facing side of the orders API. It covers the `BuyerOrderViewSet` in `apps/orders/views.py`, the URL configuration in `apps/orders/urls.py`, and the corresponding view-layer tests. The section sits at the top of the API layer — it depends on the models, placement service, permissions, and serializers being in place but does not share implementation concerns with the vendor/admin endpoints (section 08).

**Dependencies (must be complete before implementing this section):**
- `section-01-models`: `Order`, `OrderItem`, `DailyOrderSequence`, `OrderStatus` FSM choices
- `section-02-order-placement-service`: `OrderPlacementService.place_order()`, `InsufficientStockError`
- `section-06-permissions-serializers`: `IsOrderBuyer`, `IsOrderVendor`, `IsOrderCommunityAdmin`, `PlaceOrderSerializer`, `OrderSerializer`

---

## Files to Create or Modify

| File | Action |
|------|--------|
| `apps/orders/views.py` | Create (buyer section; vendor/admin views added in section 08) |
| `apps/orders/urls.py` | Create |
| `apps/orders/tests/test_views.py` | Create (buyer endpoint tests; vendor/admin tests added in section 08) |
| `config/urls.py` (or project root URLconf) | Modify to include `apps.orders.urls` |

---

## Tests First

All tests live in `apps/orders/tests/test_views.py`. Use `pytest-django`, `factory_boy` factories from `apps/orders/tests/factories.py` (defined in section 01), and `freezegun` for time-sensitive assertions.

Test settings must include:
- `CELERY_TASK_ALWAYS_EAGER = True` (tasks execute synchronously)
- All Razorpay calls mocked at the service function level via `unittest.mock.patch('apps.payments.services.razorpay.create_payment_link')`

### Authentication and Authorization Tests

```python
# POST /api/v1/orders/ — unauthenticated → 401
# POST /api/v1/orders/ — authenticated user with role != 'resident' → 403
# GET /api/v1/orders/ — unauthenticated → 401
# GET /api/v1/orders/{id}/ — unauthenticated → 401
```

### Place Order — `POST /api/v1/orders/`

```python
# Test: Valid payload with mocked Razorpay → 201
#   Response body contains: order_id, display_id, status='payment_pending', payment_link_url
# Test: Invalid delivery_window weekday (product not available on that day) → 400
# Test: delivery_window in the past → 400
# Test: Out-of-stock product (DailyInventory exhausted) → 409
# Test: vendor not approved in community → 400
# Test: Razorpay create_payment_link raises exception → 503, order is CANCELLED
# Test: Items from multiple vendors → 400
```

### List My Orders — `GET /api/v1/orders/`

```python
# Test: Returns only the authenticated buyer's own orders (orders from another buyer not included)
# Test: ?status=confirmed returns only CONFIRMED orders for this buyer
# Test: ?status= with unknown value → 400 or empty list (define in implementation)
# Test: Pagination — page param works; default page size respected
```

### Order Detail — `GET /api/v1/orders/{id}/`

```python
# Test: Buyer retrieves own order → 200, full serialized Order including nested items
# Test: Vendor of the same order retrieves it → 200 (IsOrderVendor permission)
# Test: Community admin with matching community_id retrieves it → 200
# Test: An unrelated authenticated user (different buyer) → 403
```

### Cancel Order — `POST /api/v1/orders/{id}/cancel/`

```python
# Test: Buyer cancels order in PLACED status → 200, response status='cancelled'
# Test: Buyer cancels order in PAYMENT_PENDING status → 200, response status='cancelled'
# Test: Buyer attempts to cancel a CONFIRMED order → 403
#   (FSM does not allow cancel() from CONFIRMED; view must catch TransitionNotAllowed or check status)
# Test: Non-buyer (different authenticated user) attempts cancel → 403
# Test: Cancel restores DailyInventory qty_ordered (check DB after cancel)
```

### Raise Dispute — `POST /api/v1/orders/{id}/dispute/`

```python
# Test: Buyer raises dispute within 24h of delivered_at → 200, status='disputed'
#   Use freezegun to freeze time to delivered_at + 1 hour
# Test: Buyer raises dispute >24h after delivered_at → 400
#   Use freezegun to freeze time to delivered_at + 25 hours
# Test: Order is in CONFIRMED (not DELIVERED) → 400
# Test: Non-buyer attempts to raise dispute → 403
# Test: Payload must include "reason" field; missing → 400
# Test: dispute_reason is stored on order after successful raise
```

---

## Implementation Details

### `apps/orders/views.py` — Buyer Side

Create a single `BuyerOrderViewSet` (or an equivalent set of class-based views) covering all five buyer actions. Using a `ModelViewSet` base with custom actions is the recommended approach. The viewset handles `list`, `retrieve`, `create`, and two custom actions (`cancel`, `dispute`).

**Base configuration:**
- `serializer_class = OrderSerializer`
- `permission_classes` must be set per-action (see below)
- `get_queryset()` filters to `Order.objects.filter(buyer=request.user.resident_profile)` so a buyer never sees another buyer's orders in list/retrieve

**Action-level permissions:**

| Action | Permission |
|--------|------------|
| `create` (POST /) | `IsResidentOfCommunity` (from `apps/core/permissions.py`) |
| `list` (GET /) | `IsResidentOfCommunity` |
| `retrieve` (GET /{id}/) | `IsOrderBuyer \| IsOrderVendor \| IsOrderCommunityAdmin` (any of the three) |
| `cancel` | `IsOrderBuyer` |
| `dispute` | `IsOrderBuyer` |

For `retrieve`, the `get_queryset()` base filter (buyer only) would block the vendor/admin from fetching the order. Override `get_object()` or use a separate broader queryset for the retrieve action so that the permission class, not the queryset, acts as the gate.

**`create` action:**
- Use `PlaceOrderSerializer` for input validation
- Call `OrderPlacementService.place_order(request.user, validated_data)`
- Catch `InsufficientStockError` → return HTTP 409 with `{"detail": "..."}`
- Catch `ValidationError` (from service layer) → return HTTP 400
- On success: return HTTP 201 with `OrderSerializer(order).data`
- Razorpay failure inside the service raises a service-specific exception; catch it and return HTTP 503

**`list` action:**
- Support `?status=` query parameter; filter queryset by `status__iexact` if present
- Support pagination using the project's default pagination class (set in DRF settings)

**`cancel` action (`POST /{id}/cancel/`):**
- Fetch order, check `IsOrderBuyer` permission at object level
- If `order.status` is CONFIRMED or READY (or later): return HTTP 403 with `{"detail": "Cannot cancel a confirmed order. Raise a dispute instead."}`
- Otherwise call `order.cancel()` and `order.save()`
- Return HTTP 200 with updated `OrderSerializer` data

The FSM `cancel()` transition is only allowed from PLACED and PAYMENT_PENDING (per the transition table). If the status is anything else, `TransitionNotAllowed` will be raised. The view can either let that propagate and catch it, or check the status explicitly before calling the transition. Prefer the explicit status check for a cleaner 403 error message distinguishing "cannot cancel confirmed" from generic permission failure.

**`dispute` action (`POST /{id}/dispute/`):**
- Require `{"reason": "..."}` in request body; return 400 if missing or blank
- Fetch order, check `IsOrderBuyer` object permission
- The `raise_dispute()` FSM transition has a condition guard checking `timezone.now() - order.delivered_at <= timedelta(hours=24)`. If the guard fails, django-fsm-2 raises `TransitionNotAllowed`
- Catch `TransitionNotAllowed` → return HTTP 400 with `{"detail": "Dispute window has closed or order is not in a disputable state."}`
- On success: set `order.dispute_reason = validated_reason`, `order.dispute_raised_at = timezone.now()`, call `order.raise_dispute()`, `order.save()`
- Return HTTP 200 with updated serializer data

### `apps/orders/urls.py`

Register the `BuyerOrderViewSet` with a `DefaultRouter`. Custom actions `cancel` and `dispute` must be decorated with `@action(detail=True, methods=['post'])` in the viewset. The router will automatically generate the URL patterns for these actions.

```python
# Router prefix: 'orders'
# Generated routes:
#   POST   /api/v1/orders/              → create
#   GET    /api/v1/orders/              → list
#   GET    /api/v1/orders/{pk}/         → retrieve
#   POST   /api/v1/orders/{pk}/cancel/  → cancel
#   POST   /api/v1/orders/{pk}/dispute/ → dispute
```

Register the app URLs under `api/v1/` in the project URLconf. Vendor-specific routes (`/api/v1/vendors/orders/`, `/api/v1/vendors/payouts/`) are added in section 08 and should not be defined here.

---

## Error Response Conventions

Follow the DRF custom exception handler from `apps/core/` (set up in prior splits). All error responses use `{"detail": "..."}` shape. HTTP status codes:

| Scenario | Status Code |
|----------|-------------|
| Unauthenticated | 401 |
| Wrong role or not the buyer/vendor/admin | 403 |
| Validation error (bad input) | 400 |
| Insufficient stock | 409 |
| Razorpay service unavailable | 503 |
| Dispute window expired | 400 |

---

## Key Implementation Notes

- **`get_queryset` vs `get_object` split:** For `list`, filtering to the buyer's own orders is correct. For `retrieve`, the vendor and community admin must also be able to fetch the order by PK. Use `get_permissions()` and a broader queryset override (e.g., `Order.objects.filter(community_id=request.auth['community_id'])` as a loose filter for non-buyers, letting the object-level permission class do the final check). Alternatively, override `get_object()` to use `Order.objects.all()` for retrieve/cancel/dispute actions and rely entirely on object-level permissions.

- **`order.cancel()` side effects:** The FSM transition body (defined in section 01) handles DailyInventory restoration via `F()` decrement per item. The view does not need to manage inventory rollback directly.

- **Dispute `delivered_at` field:** The dispute guard uses `order.delivered_at` (set by `mark_delivered()`), not `order.updated_at`. Do not use `updated_at` as a substitute — any subsequent save to the order would silently extend the dispute window.

- **`display_id` is for humans only:** Return it in the `create` response for display in the mobile app. For programmatic order lookups in tests, use the PK or `razorpay_idempotency_key`.

- **IST-aware time checks in tests:** Use `freezegun.freeze_time` with a UTC timestamp. The dispute window check inside the FSM transition uses `timezone.now()` (UTC-aware), so freeze UTC time in tests, not IST local time.

- **`CELERY_TASK_ALWAYS_EAGER`:** With this setting enabled in tests, `cancel_unpaid_order.apply_async(countdown=1800)` (triggered inside `await_payment()` via `OrderPlacementService`) runs immediately and synchronously. Mock `cancel_unpaid_order` if its side effects would interfere with placement tests, or ensure the test order has `razorpay_payment_id` set so the task exits silently.