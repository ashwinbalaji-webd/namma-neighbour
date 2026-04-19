# Section 06: Product Detail View

## Overview

This section implements `ProductDetailView`, a standalone `RetrieveAPIView` that serves full product information including presigned S3 image URLs, vendor summary, and a live `is_available_today` calculation. It is not nested under the community URL — instead, it validates community membership through JWT claims.

**Dependencies:**
- **section-01-models** must be complete: `Product`, `ProductImage`, `DailyInventory`, `Category`, `Vendor` models
- **section-02-storage-utils** must be complete: `get_presigned_url()` utility with module-level cached boto3 client
- **section-04-filters-permissions** must be complete: base permission classes and JWT community claim validation patterns

## Files to Create / Modify

- `namma_neighbor/apps/catalogue/serializers.py` — add `ProductDetailSerializer` (file may already have `ProductListSerializer` from section-05; extend it)
- `namma_neighbor/apps/catalogue/views.py` — add `ProductDetailView` class (file likely has `CommunityProductViewSet` from section-05; add this view)
- `namma_neighbor/apps/catalogue/urls.py` — register the product detail URL
- `tests/catalogue/test_product_detail.py` — all tests for this section

## Tests First

File: `tests/catalogue/test_product_detail.py`

Testing stack: pytest + pytest-django, factory_boy, moto for S3 mocking, freezegun for time control.

```python
# tests/catalogue/test_product_detail.py

import pytest
from moto import mock_aws
from freezegun import freeze_time

# Tests to implement:

class TestProductDetailView:
    """Tests for GET /api/v1/products/{product_id}/"""

    def test_returns_presigned_urls_for_all_images(self, ...):
        """
        Given a product with two ProductImages (both with thumbnail_s3_key set),
        calling GET /api/v1/products/{product_id}/ with a valid JWT for the
        product's community returns 200 and each image dict contains:
          - 'original_url' (presigned URL string)
          - 'thumbnail_url_400' (presigned URL string for 400×400 thumbnail)
          - 'thumbnail_url_200' (presigned URL string for 200×200 thumbnail)
        Use @mock_aws decorator and pre-seed S3 bucket. Assert all three URLs
        are present and non-empty strings.
        """
        pass

    def test_vendor_summary_keys(self, ...):
        """
        Response 'vendor_summary' dict must contain exactly:
          - 'display_name'
          - 'average_rating'
          - 'is_new_seller'
          - 'completed_delivery_count'
        Assert all four keys are present in the response data.
        """
        pass

    def test_product_different_community_returns_403(self, ...):
        """
        JWT has community_id=1, but product.community_id=2.
        GET must return HTTP 403 (community membership check fails).
        """
        pass

    def test_is_available_today_open_window(self, ...):
        """
        Use freezegun to set current IST time within the product's
        available_from/available_to window on a matching delivery_day.
        Response must contain 'is_available_today': True.
        """
        pass

    def test_is_available_today_window_closed(self, ...):
        """
        Use freezegun to set current IST time after available_to.
        Even if delivery_day matches and qty is available,
        'is_available_today' must be False.
        """
        pass

    def test_unauthenticated_returns_401(self, ...):
        """GET without a JWT token returns HTTP 401."""
        pass

    def test_inactive_product_not_found(self, ...):
        """
        Product with is_active=False should return 404.
        The view must filter on is_active=True (or raise 404 explicitly).
        """
        pass
```

All tests use `@mock_aws` from moto to avoid real S3 calls. The test fixture must create the S3 bucket referenced by `settings.AWS_STORAGE_BUCKET_NAME` before the view is called.

## Serializer: ProductDetailSerializer

File: `namma_neighbor/apps/catalogue/serializers.py`

`ProductDetailSerializer` extends `serializers.ModelSerializer` for the `Product` model.

### Image Representation

For each `ProductImage` related to the product, build a dict with three presigned URLs:

- `original_url`: presigned URL for the image's main S3 key (1 hour TTL)
- `thumbnail_url_400`: presigned URL for `thumbnail_s3_key` (400×400); may be `None` if the Celery task has not yet completed
- `thumbnail_url_200`: presigned URL for `thumbnail_s3_key_small` (200×200); may be `None` if not yet generated

Call `get_presigned_url(s3_key, expiry_seconds=3600)` from `utils.py` for each key. Wrap each call in a conditional guard: if the key field is blank/None, return `None` rather than calling the utility.

The `images` field on the serializer is a `SerializerMethodField` that iterates `instance.images.all()` (the prefetched reverse relation) and builds the list of dicts above.

### Vendor Summary

`vendor_summary` is a `SerializerMethodField`. It accesses `instance.vendor` and returns:

```python
{
    "display_name": vendor.display_name,   # or vendor.user.get_full_name(), per Vendor model
    "average_rating": vendor.average_rating,
    "is_new_seller": vendor.is_new_seller,  # property on Vendor model from section-03-seller-onboarding
    "completed_delivery_count": vendor.completed_delivery_count,  # field on Vendor model
}
```

The `is_new_seller` value is a property defined on the `Vendor` model (split 03). No additional DB query is needed here if `select_related('vendor')` was applied in the view's `get_queryset()`.

### is_available_today

`is_available_today` is a `SerializerMethodField` that calls the `Product` model's `is_available_today` property directly. This is the property-based computation path (single object), not the subquery annotation path used in `CommunityProductViewSet` (which is for list views to avoid N+1 queries).

The property checks, in order:
1. Today's IST weekday is in `product.delivery_days`
2. Current IST time is between `product.available_from` and `product.available_to`
3. For today's `DailyInventory` row: `qty_ordered < product.max_daily_qty` (if no row exists, treat as 0 ordered)
4. If `product.is_flash_sale=True`: additionally check `flash_sale_qty_remaining > 0` and `flash_sale_ends_at > now()`

Use `django.utils.timezone.localtime()` to convert the current UTC time to IST before comparing with the `TimeField` values.

### Serializer fields summary

| Field | Source | Notes |
|---|---|---|
| `id` | model | UUID or integer PK |
| `name` | model | |
| `description` | model | |
| `price` | model | DecimalField |
| `max_daily_qty` | model | |
| `available_from` | model | TimeField, ISO time string |
| `available_to` | model | TimeField, ISO time string |
| `delivery_days` | model | JSONField list of ints |
| `is_active` | model | |
| `is_featured` | model | |
| `is_flash_sale` | model | |
| `flash_sale_qty_remaining` | model | |
| `flash_sale_ends_at` | model | |
| `is_subscription` | model | |
| `category` | model | nested or slug only |
| `images` | SerializerMethodField | list of dicts with presigned URLs |
| `vendor_summary` | SerializerMethodField | dict with 4 keys |
| `is_available_today` | SerializerMethodField | bool |

## View: ProductDetailView

File: `namma_neighbor/apps/catalogue/views.py`

`ProductDetailView` is a standalone `generics.RetrieveAPIView`. It does not use `CommunityProductViewSet` — it is a separate class.

### Class definition stub

```python
class ProductDetailView(generics.RetrieveAPIView):
    """
    Retrieve full details for a single active product.

    URL: GET /api/v1/products/<int:product_id>/
    Permission: IsAuthenticated (community membership validated in get_object)
    Serializer: ProductDetailSerializer
    """
    serializer_class = ProductDetailSerializer
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = 'product_id'

    def get_queryset(self):
        """
        Return active products with all related data prefetched.
        select_related: 'vendor', 'vendor__user', 'category', 'community'
        prefetch_related: 'images'
        Filter: is_active=True only.
        """
        ...

    def get_object(self):
        """
        Retrieve the product, then validate community membership:
        - product.community_id must equal request.user's JWT community_id claim
        - If mismatch: raise PermissionDenied (HTTP 403)
        Call super().get_object() first to handle 404 on missing/inactive product,
        then apply the community check.
        """
        ...
```

### Community validation logic

The JWT contains a `community_id` claim. The permission check in `get_object()` is:

```python
from rest_framework.exceptions import PermissionDenied

product = super().get_object()
jwt_community_id = self.request.auth.get('community_id')  # or via JWT payload accessor
if product.community_id != jwt_community_id:
    raise PermissionDenied("You do not have access to products from this community.")
return product
```

The exact method to extract the JWT community claim depends on the JWT backend used (split 01). Common patterns: `request.user.community_id` if the custom user model carries it, or `request.auth['community_id']` if using a custom token. Align with the pattern used in `CommunityProductViewSet.get_queryset()` from section-05.

### No annotation needed

Unlike `CommunityProductViewSet`, this view does NOT annotate `today_qty_ordered` via a subquery. The `is_available_today` computation is delegated entirely to the serializer's `SerializerMethodField`, which calls the model property. For a single-object detail view, one extra `DailyInventory` query is acceptable.

## URL Registration

File: `namma_neighbor/apps/catalogue/urls.py`

Add the product detail endpoint at:

```
GET /api/v1/products/<int:product_id>/
```

This URL is standalone — not nested under `/communities/{slug}/` and not nested under `/vendors/`. Example registration:

```python
# In catalogue/urls.py (or the project-level urls.py that includes catalogue)
from django.urls import path
from .views import ProductDetailView

urlpatterns = [
    # ... other catalogue URLs
    path('products/<int:product_id>/', ProductDetailView.as_view(), name='product-detail'),
]
```

Confirm the prefix `/api/v1/` is applied at the project-level URL include, not duplicated here.

## Key Invariants

**Community isolation:** A resident of community A must never see product details for community B products. The check is enforced in `get_object()` after the 404 check so the error ordering is: 404 (product inactive or missing) > 403 (wrong community). Do not reveal the existence of products in other communities.

**is_available_today uses property, not annotation:** The list view (`CommunityProductViewSet`) uses a DB-level Coalesce subquery to compute availability to avoid N+1 over 20 products. The detail view skips this and calls the model property, which may issue one additional `DailyInventory` query. This is intentional and acceptable.

**Presigned URLs with None guard:** If `thumbnail_s3_key` or `thumbnail_s3_key_small` is blank (thumbnail Celery task not yet complete), return `None` for those URL fields rather than calling `get_presigned_url` with an empty string. The client must handle `None` gracefully in the image rendering layer.

**No active=False products:** `get_queryset()` filters `is_active=True`. A vendor's own inactive products are accessible only via `VendorProductViewSet` (section-07), not this view.

**select_related on vendor chain:** `vendor__user` must be in `select_related` so `vendor.user.get_full_name()` (or equivalent `display_name`) does not trigger an additional query per request.

## Dependencies Reference

- **section-01-models**: `Product`, `ProductImage`, `DailyInventory` model definitions and `is_available_today` property on `Product`
- **section-02-storage-utils**: `get_presigned_url(s3_key, expiry_seconds)` from `utils.py`
- **section-04-filters-permissions**: `IsApprovedVendor` and base JWT community claim extraction pattern (for reference — this view uses `IsAuthenticated` directly)
- **split-03-seller-onboarding**: `Vendor.is_new_seller` property and `Vendor.completed_delivery_count` field — must exist before `vendor_summary` can be populated