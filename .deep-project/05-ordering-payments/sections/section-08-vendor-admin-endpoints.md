Now I have all the context needed. Let me generate the section content.

# section-08-vendor-admin-endpoints

## Overview

This section implements the vendor-facing and community-admin-facing order management endpoints in `apps/orders/views.py`, along with the payout dashboard. This is the final API layer section and depends on all prior sections being complete.

**Dependencies (must be implemented first):**
- section-01-models: `Order`, `OrderItem`, `OrderStatus` FSM choices
- section-02-order-placement-service: `OrderPlacementService`
- section-03-razorpay-services: `release_transfer_hold()` (called via `mark_delivered()` transition body)
- section-04-webhook-handler: Razorpay client and refund handling (used in `process_refund`)
- section-05-celery-tasks: Celery tasks (scheduled from FSM transition bodies)
- section-06-permissions-serializers: `IsOrderVendor`, `IsOrderCommunityAdmin`, `OrderSerializer`, `PayoutTransactionSerializer`

**Files to create/modify:**
- `apps/orders/views.py` — add vendor and admin ViewSets/views (buyer side already added in section-07)
- `apps/orders/urls.py` — register new routes (buyer routes already registered in section-07)
- `apps/orders/tests/test_views.py` — add vendor and admin endpoint tests

---

## Tests First

All tests go in `apps/orders/tests/test_views.py`. Use `pytest-django` with the `@pytest.mark.django_db` marker. Razorpay calls must be mocked via `unittest.mock.patch`. Use `freezegun.freeze_time` where time-sensitive.

Use factories from `apps/orders/tests/factories.py` (defined in section-01): `OrderFactory`, `OrderItemFactory`. Use vendor/community/resident factories from prior splits.

### Vendor Order List

```python
# Test: GET /api/v1/vendors/orders/ returns only orders belonging to the authenticated vendor
# Test: GET /api/v1/vendors/orders/?date=YYYY-MM-DD narrows results to that delivery_window date
# Test: GET /api/v1/vendors/orders/?status=confirmed narrows results to that status
# Test: Unauthenticated request returns 401
# Test: Authenticated resident (not vendor) returns 403
```

### Consolidated Order Sheet

```python
# Test: GET /api/v1/vendors/orders/consolidated/?date=YYYY-MM-DD returns orders for that date
#       grouped by building/tower (building field on ResidentProfile from communities split)
# Test: Missing date param returns 400
# Test: Returns only the authenticated vendor's orders
```

### Mark Order Ready

```python
# Test: POST /api/v1/orders/{id}/ready/ — vendor marks a CONFIRMED order as READY → 200, status='ready'
# Test: Calling on a PLACED order (not CONFIRMED) → 400 (FSM transition not allowed)
# Test: Buyer attempting to call mark_ready → 403
# Test: Unrelated vendor attempting mark_ready → 403
```

### Mark Order Delivered

```python
# Test: POST /api/v1/orders/{id}/deliver/ — vendor marks a READY order as DELIVERED → 200
# Test: Response includes delivered_at timestamp set to approximately now
# Test: vendor.completed_delivery_count is incremented by 1
# Test: Order with razorpay_transfer_id set → release_transfer_hold is called (mock the service fn)
# Test: Order without razorpay_transfer_id (blank) → request succeeds (200), MANUAL_PAYOUT_REQUIRED is logged
# Test: Buyer attempting to call deliver → 403
```

### Vendor Cancel (Escalate to Dispute)

```python
# Test: POST /api/v1/orders/{id}/vendor-cancel/ — vendor cancels a CONFIRMED order → 200, status='disputed'
# Test: POST /api/v1/orders/{id}/vendor-cancel/ — vendor cancels a READY order → 200, status='disputed'
# Test: Payload must include {"reason": "..."} — missing reason returns 400
# Test: Calling vendor-cancel on a PLACED order (FSM blocks escalate_to_dispute) → 400
# Test: Buyer attempting vendor-cancel → 403
```

### Payout Dashboard

```python
# Test: GET /api/v1/vendors/payouts/ returns pending_amount as sum of vendor_payout
#       for this vendor's orders where transfer_on_hold=True
# Test: settled_amount is sum of vendor_payout for this vendor's orders where
#       transfer_on_hold=False AND delivery_window falls within current calendar month
# Test: transactions list includes order_id, display_id, vendor_payout, transfer_on_hold,
#       hold_release_at, delivery_window fields
# Test: pending_amount and settled_amount are 0 when vendor has no matching orders
# Test: Another vendor's orders do not appear in the result
# Test: Unauthenticated request returns 401
```

### Community Admin — Resolve Dispute

```python
# Test: POST /api/v1/orders/{id}/resolve-dispute/ — admin resolves a DISPUTED order → 200, status='delivered'
# Test: Calling on a non-DISPUTED order → 400 (FSM blocks resolve_dispute)
# Test: Admin with different community_id → 403
# Test: Vendor/buyer attempting resolve-dispute → 403
```

### Community Admin — Process Refund

```python
# Test: POST /api/v1/orders/{id}/process-refund/ — admin processes refund on DISPUTED order → 200, status='refunded'
# Test: Razorpay refund API is called with correct payment_id (mock the Razorpay client)
# Test: Admin with different community_id → 403
# Test: Vendor/buyer attempting process-refund → 403
```

---

## Implementation

### URL Routes

Add to `apps/orders/urls.py` (section-07 already registers the router and buyer action URLs — append the vendor and admin routes):

```python
# apps/orders/urls.py
# Vendor list and consolidated sheet:
#   GET /api/v1/vendors/orders/          → VendorOrderViewSet (list)
#   GET /api/v1/vendors/orders/consolidated/  → VendorOrderViewSet (consolidated action)
#   GET /api/v1/vendors/payouts/         → VendorPayoutView
#
# Order-level actions (reuse the same router registered in section-07):
#   POST /api/v1/orders/{id}/ready/          → OrderViewSet.ready action
#   POST /api/v1/orders/{id}/deliver/        → OrderViewSet.deliver action
#   POST /api/v1/orders/{id}/vendor-cancel/  → OrderViewSet.vendor_cancel action
#   POST /api/v1/orders/{id}/resolve-dispute/→ OrderViewSet.resolve_dispute action
#   POST /api/v1/orders/{id}/process-refund/ → OrderViewSet.process_refund action
```

All vendor-list routes belong under the `/api/v1/vendors/` prefix. Check the project URL conf (likely in `config/urls.py`) for how sub-prefixes are assembled. The order-level action routes extend the existing `OrderViewSet` router from section-07.

### `VendorOrderViewSet`

Create a separate ViewSet in `apps/orders/views.py` for vendor-scoped list operations:

```python
class VendorOrderViewSet(viewsets.ReadOnlyModelViewSet):
    """
    List and filter orders for the authenticated vendor.
    GET /api/v1/vendors/orders/
    GET /api/v1/vendors/orders/consolidated/
    """
    permission_classes = [IsVendorOfCommunity]
    serializer_class = OrderSerializer

    def get_queryset(self):
        """Filter to vendor's own orders. Apply optional ?date= and ?status= query params."""
        ...

    @action(detail=False, methods=['get'], url_path='consolidated')
    def consolidated(self, request):
        """
        Return orders for ?date= grouped by building/tower.
        Requires ?date= query parameter; return 400 if missing.
        Group by buyer.resident_profile.building (field name from communities split).
        """
        ...
```

### `VendorPayoutView`

A standalone `APIView` (not a ViewSet) for the payout dashboard:

```python
class VendorPayoutView(APIView):
    """
    GET /api/v1/vendors/payouts/
    Returns pending_amount, settled_amount (current month), transactions list.
    """
    permission_classes = [IsVendorOfCommunity]

    def get(self, request):
        """
        pending_amount: Sum of vendor_payout where transfer_on_hold=True for this vendor.
        settled_amount: Sum of vendor_payout where transfer_on_hold=False AND
                        delivery_window__month == today.month AND delivery_window__year == today.year.
        transactions: Queryset of Order serialized with PayoutTransactionSerializer
                      (all orders for this vendor, ordered by delivery_window desc).
        """
        ...
```

### Order-Level Action Methods on `OrderViewSet`

These are additional `@action` decorators on the existing `OrderViewSet` defined in section-07. Add them to the same class:

```python
@action(detail=True, methods=['post'], url_path='ready')
def ready(self, request, pk=None):
    """
    Mark order READY. Permission: IsOrderVendor.
    Calls order.mark_ready() and saves.
    Returns 400 with error detail if FSM transition raises TransitionNotAllowed.
    """
    ...

@action(detail=True, methods=['post'], url_path='deliver')
def deliver(self, request, pk=None):
    """
    Mark order DELIVERED. Permission: IsOrderVendor.
    Calls order.mark_delivered() which:
      - Sets order.delivered_at = timezone.now()
      - Calls release_transfer_hold(order) if razorpay_transfer_id is set
      - Logs MANUAL_PAYOUT_REQUIRED if razorpay_transfer_id is blank
      - Increments vendor.completed_delivery_count
    Returns 200 with updated OrderSerializer data.
    """
    ...

@action(detail=True, methods=['post'], url_path='vendor-cancel')
def vendor_cancel(self, request, pk=None):
    """
    Escalate order to DISPUTED (vendor cancel path). Permission: IsOrderVendor.
    Payload: {"reason": "..."} — reason is required; return 400 if missing.
    Sets order.dispute_reason = reason, order.dispute_raised_at = now().
    Calls order.escalate_to_dispute() and saves.
    Returns 200 with updated OrderSerializer data.
    """
    ...

@action(detail=True, methods=['post'], url_path='resolve-dispute')
def resolve_dispute(self, request, pk=None):
    """
    Resolve dispute in vendor's favour (order returns to DELIVERED).
    Permission: IsOrderCommunityAdmin.
    Calls order.resolve_dispute() and saves.
    Returns 200 with updated OrderSerializer data.
    """
    ...

@action(detail=True, methods=['post'], url_path='process-refund')
def process_refund(self, request, pk=None):
    """
    Issue Razorpay refund and transition order to REFUNDED.
    Permission: IsOrderCommunityAdmin.
    Calls Razorpay refund API (client.payment.refund(order.razorpay_payment_id, {"reverse_all": 1})).
    Then calls order.process_refund() FSM transition and saves.
    Returns 200 with updated OrderSerializer data.
    """
    ...
```

### Permission Composition

For action-level permissions, use DRF's `get_permissions()` override on `OrderViewSet` to return different permission classes per action:

- `ready`, `deliver`, `vendor_cancel` → `[IsOrderVendor]`
- `resolve_dispute`, `process_refund` → `[IsOrderCommunityAdmin]`

The `IsOrderVendor` and `IsOrderCommunityAdmin` permission classes are object-level, so call `self.check_object_permissions(request, order)` explicitly after `get_object()`.

### FSM Error Handling

Wrap all `order.<transition>()` calls in a try/except for `TransitionNotAllowed` (import from `django_fsm`):

```python
from django_fsm import TransitionNotAllowed

try:
    order.mark_ready()
    order.save()
except TransitionNotAllowed:
    return Response({"detail": "Transition not allowed from current status."}, status=400)
```

Apply this pattern consistently across `ready`, `deliver`, `vendor_cancel`, `resolve_dispute`, and `process_refund` actions.

### Consolidated Order Sheet — Grouping Logic

The `consolidated` action returns orders grouped by building. The grouping should happen in Python (not SQL) unless a single annotated query is clean. The response structure should be:

```json
{
  "date": "2024-01-15",
  "groups": [
    {
      "building": "Block A",
      "orders": [ ... ]
    }
  ]
}
```

`building` comes from `order.buyer.user.resident_profile.building` (the field name from the communities split — verify the actual field name in `ResidentProfile` before implementing).

### Payout Aggregation Query

Use Django ORM `aggregate()` with `Sum`:

```python
from django.db.models import Sum
from django.utils import timezone

vendor = request.user.vendor_profile
today = timezone.localdate()

pending = Order.objects.filter(
    vendor=vendor, transfer_on_hold=True
).aggregate(total=Sum('vendor_payout'))['total'] or Decimal('0.00')

settled = Order.objects.filter(
    vendor=vendor,
    transfer_on_hold=False,
    delivery_window__year=today.year,
    delivery_window__month=today.month,
).aggregate(total=Sum('vendor_payout'))['total'] or Decimal('0.00')
```

### Vendor Accessor

Access the `Vendor` model from the request user via `request.user.vendor_profile`. This is the OneToOne reverse accessor with `related_name='vendor_profile'` defined on the `Vendor` model in the vendors split. **Verify the actual `related_name` in `apps/vendors/models.py` before implementing** — there is a known ambiguity noted in the plan around whether the accessor is `vendor_profile` or `vendor_profile_profile`.

---

## Key Notes

**`deliver` action side effects are in the FSM transition body, not the view.** The view calls `order.mark_delivered()` — the transition body (defined in section-01) handles `delivered_at`, `release_transfer_hold()`, `completed_delivery_count`, and notification stubs. The view only wraps this call and handles `TransitionNotAllowed`.

**`vendor-cancel` requires a reason.** Before calling `order.escalate_to_dispute()`, validate the `reason` field from `request.data`. If absent or blank, return 400 before touching the FSM.

**`process-refund` calls Razorpay directly in the view.** Import the Razorpay client from `apps.payments.services.razorpay` (the cached module-level client). Call `client.payment.refund(order.razorpay_payment_id, {"reverse_all": 1})`. If `razorpay_payment_id` is blank (edge case — order was never paid), return 400 without calling the FSM.

**Mocking in tests.** In the `deliver` and `process_refund` tests, patch `apps.payments.services.razorpay.client` to avoid hitting the real Razorpay API:

```python
@patch('apps.payments.services.razorpay.client')
def test_vendor_mark_delivered_with_transfer(mock_client, ...):
    ...
```

**`IsVendorOfCommunity` is a request-level permission** (from `apps/core/permissions.py`, verifies JWT role). `IsOrderVendor` is an object-level permission (from `apps/orders/permissions.py`, verifies `order.vendor.user == request.user`). Use both in sequence for vendor order actions: `IsVendorOfCommunity` guards the request, `IsOrderVendor` guards the specific object.