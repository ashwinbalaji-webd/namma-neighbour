Now I have all the context needed. Let me generate the section content.

# section-06-permissions-serializers

## Overview

This section implements two closely related files that are required by both the buyer endpoints (section-07) and the vendor/admin endpoints (section-08). Neither file has runtime dependencies beyond the `Order` model from section-01; they can be built and tested in parallel with sections 03, 04, 05, and 09 after section-01 is complete.

**Files to create:**
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/orders/permissions.py`
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/orders/serializers.py`

**Tests to add to:**
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/orders/tests/test_views.py` (permission tests go here per the TDD plan)
- Serializer tests may go in `test_views.py` or a new `test_serializers.py`

---

## Dependencies

- **section-01-models** must be complete. Specifically: `Order`, `OrderItem`, `DailyOrderSequence` models in `apps/orders/models.py` and the `OrderStatus` enum.
- `apps/core/permissions.py` must exist with `IsResidentOfCommunity`, `IsVendorOfCommunity`, `IsCommunityAdmin` base permission classes and JWT role/community_id claim reading logic.
- `ResidentProfile` (OneToOne to User, `related_name='resident_profile'`) and `Vendor` (OneToOne to User, `related_name='vendor_profile'`) must exist.

---

## Tests First

All permission tests live in `apps/orders/tests/test_views.py`. Serializer tests may be placed in the same file or in a dedicated `apps/orders/tests/test_serializers.py`.

### Permission Tests

```python
# apps/orders/tests/test_views.py

# --- IsOrderBuyer ---
# Test: has_object_permission returns True when request.user == order.buyer.user
# Test: has_object_permission returns False for a different authenticated user who is not the buyer

# --- IsOrderVendor ---
# Test: has_object_permission returns True when request.user == order.vendor.user
# Test: has_object_permission returns False for the buyer attempting vendor actions

# --- IsOrderCommunityAdmin ---
# Test: has_object_permission returns True when user's JWT role is 'community_admin'
#       AND request.auth['community_id'] == order.community_id
# Test: has_object_permission returns False when community_admin has a different community_id in JWT
```

The permission tests call `permission.has_object_permission(request, view, order)` directly — no HTTP layer needed. Use `APIRequestFactory` and set `request.user` and `request.auth` manually, or use the existing JWT test helpers from `apps/core/`.

### Serializer Tests

```python
# apps/orders/tests/test_serializers.py  (or test_views.py)

# --- PlaceOrderSerializer ---
# Test: raises ValidationError when vendor_id is missing
# Test: raises ValidationError when items list is empty
# Test: raises ValidationError when items list is missing
# Test: valid data passes serializer.is_valid() (does not test service logic)

# --- OrderSerializer ---
# Test: payment_link_url is present in serialized output when order.status == PAYMENT_PENDING
# Test: payment_link_url is absent (or None) when order.status is not PAYMENT_PENDING
#       (e.g., CONFIRMED, DELIVERED)
# Test: nested items field contains correct OrderItemSerializer data

# --- OrderItemSerializer ---
# Test: unit_price in serialized output matches the snapshot value set at order creation,
#       not the current product price (create an order, change product.price, re-serialize,
#       confirm unit_price is unchanged)

# --- PayoutTransactionSerializer ---
# Test: serialized output includes all required fields:
#       order_id, display_id, vendor_payout, transfer_on_hold, hold_release_at, delivery_window
```

---

## Implementation: `apps/orders/permissions.py`

Three DRF object-level permission classes. All three inherit from `rest_framework.permissions.BasePermission` and override `has_object_permission(self, request, view, obj)`. The `obj` passed in is always an `Order` instance.

### `IsOrderBuyer`

Passes when the authenticated user is the buyer of the order.

```python
def has_object_permission(self, request, view, obj):
    """Return True if request.user is the buyer of obj (an Order)."""
    return request.user == obj.buyer.user
```

### `IsOrderVendor`

Passes when the authenticated user is the vendor who received the order.

```python
def has_object_permission(self, request, view, obj):
    """Return True if request.user is the vendor of obj (an Order)."""
    return request.user == obj.vendor.user
```

### `IsOrderCommunityAdmin`

Passes when both conditions are true:
1. The user's JWT role is `community_admin`
2. The `community_id` in the JWT matches `obj.community_id`

The JWT payload is available on `request.auth` as a dict (this is the existing pattern in `apps/core/permissions.py` — follow the same access pattern used there for reading `role` and `community_id` claims).

```python
def has_object_permission(self, request, view, obj):
    """
    Return True if request.user is a community admin for the same
    community as obj (an Order).
    """
    # Read role and community_id from JWT claims (request.auth dict)
    # Check role == 'community_admin' AND community_id matches obj.community_id
```

Note: examine the existing `IsCommunityAdmin` implementation in `apps/core/permissions.py` before writing this — the JWT claim key names (`role`, `community_id`) must match exactly what the existing auth layer sets.

---

## Implementation: `apps/orders/serializers.py`

Four serializers. Use `rest_framework.serializers` throughout.

### `OrderItemSerializer`

Read-only serializer for the `OrderItem` model. All fields are snapshot values stored on the `OrderItem` row — they do not derive from the live `Product`.

Fields: `id`, `product_id`, `product_name` (source: `product.name`, read from product FK at serialization time — this is fine because the product name rarely changes and the FK is set at order time), `quantity`, `unit_price`, `subtotal`.

```python
class OrderItemSerializer(serializers.ModelSerializer):
    """Read-only snapshot of an ordered item."""
    class Meta:
        model = OrderItem
        fields = ['id', 'product_id', 'product_name', 'quantity', 'unit_price', 'subtotal']
```

`product_name` requires a `SerializerMethodField` or `source` kwarg pointing to `product.name`.

### `PlaceOrderSerializer`

Write-only serializer used to validate the `POST /api/v1/orders/` request body. This serializer validates shape and types only — it does not touch the database or call any service. The view is responsible for passing `serializer.validated_data` to `OrderPlacementService.place_order()`.

Fields:
- `vendor_id` — IntegerField, required
- `delivery_window` — DateField, required
- `items` — ListField of nested dicts, required, `allow_empty=False`
  - Each item: `product_id` (IntegerField) and `quantity` (IntegerField, min_value=1)
- `delivery_notes` — CharField, `required=False`, `allow_blank=True`, `default=""`

The `items` field can be implemented as a nested serializer or as a `ListField(child=...)`. Either approach is acceptable. The key constraint is `allow_empty=False` so an empty items list fails validation.

```python
class PlaceOrderSerializer(serializers.Serializer):
    """Validates the place-order request body. Does not interact with DB."""
    vendor_id = serializers.IntegerField()
    delivery_window = serializers.DateField()
    items = serializers.ListField(child=..., allow_empty=False)
    delivery_notes = serializers.CharField(required=False, allow_blank=True, default='')
```

### `OrderSerializer`

Full read serializer for `Order`. Returned by the detail endpoint, the list endpoint, and after successful order placement. Nested `items` uses `OrderItemSerializer(many=True, read_only=True)`.

The `payment_link_url` field must only be present (non-null) when `order.status == OrderStatus.PAYMENT_PENDING`. For all other statuses, serialize it as `None`. This can be done with a `SerializerMethodField`.

Fields: `id`, `display_id`, `status`, `subtotal`, `platform_commission`, `vendor_payout`, `delivery_window`, `delivery_notes`, `razorpay_payment_link_url` (conditionally populated), `razorpay_transfer_id`, `transfer_on_hold`, `hold_release_at`, `delivered_at`, `cancelled_at`, `items` (nested), `created_at`, `updated_at`.

```python
class OrderSerializer(serializers.ModelSerializer):
    """Full read representation of an Order with nested items."""
    items = OrderItemSerializer(many=True, read_only=True)
    payment_link_url = serializers.SerializerMethodField()

    def get_payment_link_url(self, obj):
        """Return the Razorpay payment link URL only when payment is pending."""
        # Return obj.razorpay_payment_link_url if status == OrderStatus.PAYMENT_PENDING
        # else return None

    class Meta:
        model = Order
        fields = [...]
```

### `PayoutTransactionSerializer`

Used by the `GET /api/v1/vendors/payouts/` endpoint to list individual order payout records. Read-only.

Fields: `order_id` (source: `id`), `display_id`, `vendor_payout`, `transfer_on_hold`, `hold_release_at`, `delivery_window`.

```python
class PayoutTransactionSerializer(serializers.ModelSerializer):
    """Payout record for a single order, used in the vendor payout dashboard."""
    order_id = serializers.IntegerField(source='id')

    class Meta:
        model = Order
        fields = ['order_id', 'display_id', 'vendor_payout', 'transfer_on_hold',
                  'hold_release_at', 'delivery_window']
```

---

## Key Notes and Edge Cases

**`IsOrderCommunityAdmin` community comparison:** `obj.community_id` is the integer FK value on the Order row. The JWT `community_id` claim is likely also an integer (or may be a string depending on the JWT encoding). Ensure type consistency — compare `int(request.auth['community_id']) == obj.community_id` if there is any risk of type mismatch. Check the existing core permissions implementation to confirm.

**`payment_link_url` conditional exposure:** The Razorpay payment link URL is only actionable while the order is in `PAYMENT_PENDING`. Exposing it after the order moves to `CONFIRMED` (payment captured) is harmless but potentially confusing to the mobile client. Return `None` for all non-PAYMENT_PENDING statuses — the mobile app should not render a payment button for confirmed orders.

**`PlaceOrderSerializer` items nesting:** The nested item structure (`product_id`, `quantity`) passed to `OrderPlacementService.place_order()` must use the same key names that the service expects. Align with the service's `payload.items` access pattern defined in section-02.

**No financial fields on `PlaceOrderSerializer`:** `subtotal`, `platform_commission`, and `vendor_payout` are computed server-side by `OrderPlacementService`. The serializer must not include them as writable fields — this prevents clients from submitting their own financial calculations.

**`product_name` sourcing in `OrderItemSerializer`:** The plan calls this a "snapshot" field but the model stores `product` as a FK, not a denormalized name string. This means `product.name` is read at serialization time, not at order creation. For MVP this is acceptable. If product name changes become a concern, add a `product_name_snapshot` CharField to the `OrderItem` model (that is a section-01 change, not a section-06 concern).