Now I have all the context needed. Let me generate the section content.

# Section 07: Vendor Product Management

## Overview

This section implements `VendorProductViewSet` — the CRUD interface that approved vendors use to manage their own product listings. It extends `ModelViewSet` and lives in `namma_neighbor/apps/catalogue/views.py`.

**Dependencies:** Requires section-01-models (Product, Category, DailyInventory models) and section-04-filters-permissions (IsApprovedVendor permission class). This section is a prerequisite for section-08-image-upload.

**Runtime:** Python/Django. Tests run with `uv run pytest`.

---

## Background Context

### Project Stack

- Django 5.x + DRF 3.15, PostgreSQL 16
- Auth: phone-OTP → JWT. Roles and `community_id` are embedded in the JWT token. Permission classes read from JWT claims rather than hitting the database.
- All models inherit `TimestampedModel` (provides `created_at`, `updated_at`).
- The catalogue app lives at `namma_neighbor/apps/catalogue/`.

### Vendor Model Relationship

The `Vendor` model (from split 03-Seller-Onboarding) has a `OneToOneField` to `User` with `related_name='vendor_profile'`. This means the reverse accessor from a user to their vendor profile is `request.user.vendor_profile` — **not** `request.user.vendor_profile_profile`. The plan document contains a note stating `vendor_profile_profile`; treat the canonical form as `vendor_profile` (standard OneToOne reverse accessor naming from split 03).

### Product Model Key Fields (from section-01)

- `vendor` — FK to `vendors.Vendor`
- `community` — FK to `communities.Community`
- `category` — FK to `catalogue.Category`
- `is_active` — `BooleanField(default=False)`: new products start inactive until first image is uploaded
- `available_from`, `available_to` — `TimeField` values defining the daily order window
- `delivery_days` — `JSONField` storing a list of weekday integers (0=Monday through 6=Sunday)
- `max_daily_qty` — integer cap for daily orders
- Flash sale fields: `is_flash_sale`, `flash_sale_qty`, `flash_sale_qty_remaining`, `flash_sale_ends_at`
- `is_featured`, `is_subscription`

### Category Compliance Flags (from section-01)

- `requires_fssai` — True for food categories; vendor must have `fssai_status == VERIFIED`
- `requires_gstin` — True for high-value goods; vendor's `gstin` field must not be blank

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `namma_neighbor/apps/catalogue/views.py` | Add `VendorProductViewSet` class |
| `namma_neighbor/apps/catalogue/serializers.py` | Confirm `ProductListSerializer` and `ProductDetailSerializer` handle vendor-writable fields; add write serializer if needed |
| `namma_neighbor/apps/catalogue/urls.py` | Register `VendorProductViewSet` at `vendors/products/` |
| `tests/catalogue/test_vendor_management.py` | New test file |

---

## Tests First

File: `tests/catalogue/test_vendor_management.py`

Testing stack: pytest + pytest-django, factory_boy for fixtures.

### Test Stubs

```python
import pytest
from django.urls import reverse
# Import factories for Vendor, User, Community, Category, Product


class TestVendorProductCreate:
    """POST /api/v1/vendors/products/"""

    def test_food_category_unverified_fssai_returns_403(self, api_client, approved_vendor, food_category):
        """
        Vendor whose fssai_status != VERIFIED attempts to list in a category
        where requires_fssai=True. Expects HTTP 403 with message
        'FSSAI verification required to list in this category'.
        """

    def test_gstin_category_blank_gstin_returns_403(self, api_client, approved_vendor, gstin_category):
        """
        Vendor with blank gstin attempts to list in a category where
        requires_gstin=True. Expects HTTP 403 with message
        'GSTIN required to list in this category'.
        """

    def test_valid_create_sets_is_active_false(self, api_client, approved_vendor, basic_category):
        """
        Valid POST with all required fields and no compliance blockers.
        Asserts product is created and is_active=False on the returned object.
        """

    def test_community_auto_set_from_vendor_profile(self, api_client, approved_vendor, basic_category):
        """
        The 'community' field should not be accepted in the request payload.
        Asserts product.community == approved_vendor.community after creation.
        """

    def test_available_from_gte_available_to_returns_400(self, api_client, approved_vendor, basic_category):
        """
        Payload with available_from == available_to or available_from > available_to
        returns HTTP 400.
        """

    def test_delivery_days_out_of_range_returns_400(self, api_client, approved_vendor, basic_category):
        """
        Payload with delivery_days=[7] (invalid weekday integer) returns HTTP 400.
        """

    def test_delivery_days_negative_returns_400(self, api_client, approved_vendor, basic_category):
        """
        Payload with delivery_days=[-1] returns HTTP 400.
        """


class TestVendorProductPatch:
    """PATCH /api/v1/vendors/products/{pk}/"""

    def test_patch_cannot_change_category(self, api_client, approved_vendor, vendor_product):
        """
        PATCH request with a different category value should be rejected or ignored.
        The category on the product must remain unchanged.
        """

    def test_patch_cannot_change_vendor(self, api_client, approved_vendor, vendor_product):
        """
        PATCH request with a different vendor id should be rejected or ignored.
        """

    def test_patch_cannot_change_community(self, api_client, approved_vendor, vendor_product):
        """
        PATCH request with a different community value should be rejected or ignored.
        """

    def test_patch_mutable_fields_succeed(self, api_client, approved_vendor, vendor_product):
        """
        PATCH on mutable fields (e.g., max_daily_qty, available_from, available_to)
        should succeed with HTTP 200.
        """


class TestVendorProductDelete:
    """DELETE /api/v1/vendors/products/{pk}/"""

    def test_delete_soft_deletes(self, api_client, approved_vendor, vendor_product):
        """
        DELETE sets product.is_active=False. The DB record still exists.
        The product should no longer appear in the vendor's product list
        (since the viewset filters active products by default, or the vendor
        can filter — verify the exact behavior in get_queryset).
        """

    def test_delete_db_record_remains(self, api_client, approved_vendor, vendor_product):
        """
        After DELETE, Product.objects.filter(pk=vendor_product.pk).exists() is True.
        """


class TestVendorProductIsolation:
    """Vendors cannot access each other's products."""

    def test_vendor_cannot_list_other_vendors_products(
        self, api_client, approved_vendor, another_approved_vendor, another_vendor_product
    ):
        """
        GET /vendors/products/ for approved_vendor returns only their own products,
        not another_vendor_product.
        """

    def test_vendor_cannot_edit_other_vendors_product(
        self, api_client, approved_vendor, another_vendor_product
    ):
        """
        PATCH /vendors/products/{another_vendor_product.pk}/ returns 404
        (queryset scoping means the other vendor's product is not found).
        """
```

### Fixtures Needed

Define these in `tests/catalogue/conftest.py` or a shared conftest using factory_boy:

- `approved_vendor` — a `Vendor` with `status=VendorStatus.APPROVED`, linked to a `Community`
- `another_approved_vendor` — a second approved vendor in the same community
- `basic_category` — a `Category` with `requires_fssai=False`, `requires_gstin=False`
- `food_category` — a `Category` with `requires_fssai=True`
- `gstin_category` — a `Category` with `requires_gstin=True`
- `vendor_product` — a `Product` owned by `approved_vendor`, `is_active=False`
- `another_vendor_product` — a `Product` owned by `another_approved_vendor`

---

## Implementation Details

### VendorProductViewSet

**Location:** `namma_neighbor/apps/catalogue/views.py`

**Class definition sketch:**

```python
class VendorProductViewSet(ModelViewSet):
    """
    CRUD for a vendor's own product listings.

    Permission: IsApprovedVendor (from section-04).
    All mutations are scoped strictly to the authenticated vendor.
    """
    permission_classes = [IsApprovedVendor]
    # serializer_class: use ProductListSerializer for list/create,
    # ProductDetailSerializer for retrieve/update.
    # Or define a write serializer — see Serializer section below.

    def get_queryset(self):
        """
        Returns only the products owned by the requesting vendor.
        Uses select_related for efficiency.
        Never returns another vendor's products.
        """

    def get_serializer_class(self):
        """
        Returns ProductDetailSerializer for retrieve, update, partial_update.
        Returns ProductListSerializer (or a VendorProductWriteSerializer) for
        list and create.
        """

    def perform_create(self, serializer):
        """
        1. Extract vendor from request.user.vendor_profile.
        2. Extract community from vendor.community.
        3. Run FSSAI compliance gate:
           - if category.requires_fssai and vendor.fssai_status != VendorStatus.VERIFIED:
               raise PermissionDenied("FSSAI verification required to list in this category")
        4. Run GSTIN compliance gate:
           - if category.requires_gstin and not vendor.gstin:
               raise PermissionDenied("GSTIN required to list in this category")
        5. Save with vendor=vendor, community=community, is_active=False.
        """

    def perform_destroy(self, instance):
        """
        Soft-delete: set is_active=False and save.
        Do NOT call instance.delete().
        """

    def partial_update(self, request, *args, **kwargs):
        """
        Ensures partial=True is passed to the serializer (standard DRF override
        or rely on the built-in partial_update from ModelViewSet).
        """
```

### Serializer Considerations

**Location:** `namma_neighbor/apps/catalogue/serializers.py`

The write path needs these constraints:

- `category`, `vendor`, `community` must be **read-only after creation**. The cleanest approach is to use two serializers: a write serializer for create (accepts `category` but not `vendor` or `community`) and the existing detail serializer for reads.
- Alternatively, override `get_fields()` in a single serializer to mark those three fields as `read_only=True` when updating.

**Validation methods to include in the write serializer (or the existing serializer's `validate()`):**

```python
def validate_delivery_days(self, value):
    """
    Each entry in value must be an integer in range [0, 6].
    Raise serializers.ValidationError if any entry is outside this range,
    is null, or is not an integer.
    """

def validate(self, data):
    """
    Cross-field validation:
    - available_from must be strictly less than available_to.
    - FSSAI and GSTIN gates are also checked here (in addition to perform_create)
      so Django Admin cannot bypass them via model.save().
    Note: The FSSAI/GSTIN check in validate() requires access to the category
    and the vendor. The vendor is read from self.context['request'].user.vendor_profile.
    """
```

The compliance gates must appear in **both** `validate()` (serializer) **and** `Product.clean()` (model) so they cannot be bypassed through the Django Admin or direct model saves.

### Read-Only Fields After Creation

The following fields are **write-once** (set at creation, never mutable via PATCH):

- `category`
- `vendor`
- `community`

Any PATCH payload containing these fields should either raise a 400 validation error or silently ignore them. The recommended approach is to mark them `read_only=True` in the update serializer so they are stripped from incoming data.

### Mutable Fields

All other product fields are mutable via PATCH:

- `name`, `description`, `price`
- `available_from`, `available_to`
- `delivery_days`
- `max_daily_qty`
- `is_flash_sale`, `flash_sale_qty`, `flash_sale_qty_remaining`, `flash_sale_ends_at`
- `is_subscription`

Note: `is_featured` is set by community admins via the admin endpoints (section-09), not directly by the vendor.

### Soft Delete Behavior

`perform_destroy` sets `is_active=False` and saves. The database record is retained because order records in split 05 will reference it via FK. Do not use `instance.delete()`.

The viewset's `get_queryset()` should return all of the vendor's products regardless of `is_active` state (so vendors can see their deactivated products and reactivate them via PATCH). This differs from `CommunityProductViewSet` (section-05), which only exposes `is_active=True` products to residents.

### URL Registration

**Location:** `namma_neighbor/apps/catalogue/urls.py`

```python
from rest_framework.routers import DefaultRouter
from .views import VendorProductViewSet

router = DefaultRouter()
router.register(r'vendors/products', VendorProductViewSet, basename='vendor-product')

urlpatterns = router.urls
```

The catalogue app's `urls.py` is included in the project root `urls.py` under the `api/v1/` prefix. The full URL prefix for vendor product management becomes `/api/v1/vendors/products/`.

---

## Key Invariants to Preserve

1. **No active products without images.** `is_active=False` at creation is mandatory. Section-08 (image upload) sets `is_active=True` on first image upload — do not change this default here.

2. **Compliance gates run in two places.** The FSSAI and GSTIN checks live in both the serializer's `validate()` and `Product.clean()`. Neither should be removed — they serve different bypass vectors (API vs. Django Admin).

3. **Queryset isolation is a security boundary.** `get_queryset()` must scope to the authenticated vendor. A vendor requesting `/vendors/products/{pk}/` for another vendor's product should receive 404 (not found within their queryset), not 403 (forbidden). This is the standard DRF queryset-scoping pattern.

4. **`delivery_days` is a list of integers 0–6.** The PostgreSQL JSONB `@>` containment operator used in section-05's `todays-drops` endpoint requires this exact format. Do not allow strings, nulls, or out-of-range values to be stored.

5. **`available_from < available_to` is strict.** Equal values (e.g., both `08:00`) must be rejected. An order window of zero width is not valid.

6. **Community is not client-controlled.** The vendor's community is always set server-side from `vendor.community`. Accepting a `community` field in the create payload would allow a vendor to list products in a community they do not belong to.