Now I have all the context needed to write the section. Let me compose the complete, self-contained section content.

# Section 09: Admin Feature and Flash Sale Endpoints

## Overview

This section implements three HTTP endpoints for community admin and vendor actions related to product merchandising:

1. **Feature/Unfeature** — Community admins can toggle `is_featured` on a product.
2. **Flash Sale Activation** — Community admins or the product's vendor owner can start a flash sale.
3. **Consolidated Order Sheet Stub** — A vendor-accessible endpoint returning an empty order summary skeleton for split 05 to populate.

This section depends on:
- **section-01-models**: `Product`, `DailyInventory` models and field definitions.
- **section-04-filters-permissions**: `IsCommunityAdminOrProductVendorOwner` permission class and `IsApprovedVendor`.

No other sections are prerequisites. This section does not block any other sections.

---

## Files to Create or Modify

- `namma_neighbor/apps/catalogue/views.py` — add `ProductFeatureView` and `FlashSaleView` and `ConsolidatedOrderSheetView`
- `namma_neighbor/apps/catalogue/serializers.py` — add `FlashSaleSerializer`
- `namma_neighbor/apps/catalogue/urls.py` — register the three endpoint paths
- `tests/catalogue/test_admin_endpoints.py` — all tests for this section

---

## Tests First

File: `tests/catalogue/test_admin_endpoints.py`

All tests use `pytest` + `pytest-django` + `factory_boy`. Use `freezegun` where `ends_at` validation depends on current time.

### Feature / Unfeature Endpoint

```python
class TestProductFeatureEndpoint:
    """Tests for POST/DELETE .../feature/ community admin actions."""

    def test_post_feature_by_community_admin_sets_is_featured_true(self, ...):
        """Community admin POSTs feature → product.is_featured becomes True."""

    def test_delete_feature_by_community_admin_sets_is_featured_false(self, ...):
        """Community admin DELETEs feature → product.is_featured becomes False."""

    def test_feature_by_non_admin_returns_403(self, ...):
        """A regular resident (non-admin) hitting POST feature/ → 403."""

    def test_feature_product_from_different_community_returns_403_or_404(self, ...):
        """Admin of community A cannot feature a product belonging to community B."""
```

### Flash Sale Activation Endpoint

```python
class TestFlashSaleActivationEndpoint:
    """Tests for POST .../flash-sale/."""

    def test_flash_sale_with_valid_payload_sets_fields(self, ...):
        """qty=10, ends_at in future → flash_sale fields written to product."""

    def test_flash_sale_qty_zero_returns_400(self, ...):
        """qty=0 fails validation with a 400 response."""

    def test_flash_sale_ends_at_in_past_returns_400(self, ...):
        """ends_at in the past fails validation with a 400 response."""

    def test_flash_sale_activated_by_vendor_owner_succeeds(self, ...):
        """The product's own vendor (not admin) can activate a flash sale."""

    def test_flash_sale_by_non_owner_non_admin_returns_403(self, ...):
        """An unrelated user triggering POST flash-sale/ → 403."""
```

### Consolidated Order Sheet Stub

```python
class TestConsolidatedOrderSheetStub:
    """Tests for GET /api/v1/vendors/orders/consolidated/."""

    def test_returns_skeleton_payload_for_authenticated_vendor(self, ...):
        """Approved vendor → 200 with {"date": ..., "total_orders": 0, "by_building": {}}."""

    def test_non_vendor_returns_403(self, ...):
        """Resident with no vendor profile hitting this endpoint → 403."""
```

---

## Implementation Details

### URL Configuration

Register these paths in `namma_neighbor/apps/catalogue/urls.py`:

```
POST   /api/v1/communities/{slug}/products/{product_id}/feature/
DELETE /api/v1/communities/{slug}/products/{product_id}/feature/
POST   /api/v1/communities/{slug}/products/{product_id}/flash-sale/
GET    /api/v1/vendors/orders/consolidated/
```

The `{product_id}` path parameter is the integer PK of the product. The `{slug}` is the community slug.

The feature and flash-sale URLs are intentionally nested under the community to enforce community-scoping in the view without relying solely on a permission class.

### ProductFeatureView

Class: `ProductFeatureView(APIView)` in `views.py`.

Permission class: `IsCommunityAdmin` (from `apps.communities.permissions` or equivalent existing permission from split 01). Do **not** use `IsCommunityAdminOrProductVendorOwner` here — only community admins can set the featured flag.

`get_object()` helper method:
- Resolves community from `slug` URL kwarg.
- Calls `get_object_or_404(Product, pk=self.kwargs['product_id'], community=community)`.
- This query embeds the community scope: a product from a different community is a 404, not a 403.

`post(request, slug, product_id)`:
- Call `get_object()`.
- Set `product.is_featured = True` and `product.save(update_fields=['is_featured'])`.
- Return `Response({"is_featured": True}, status=HTTP_200_OK)`.

`delete(request, slug, product_id)`:
- Call `get_object()`.
- Set `product.is_featured = False` and `product.save(update_fields=['is_featured'])`.
- Return `Response({"is_featured": False}, status=HTTP_200_OK)`.

No serializer is needed for this view — the payload is minimal and hand-built.

### FlashSaleSerializer

Add `FlashSaleSerializer` to `serializers.py`. It is a plain `Serializer` (not `ModelSerializer`) with three fields:

- `qty`: `IntegerField(min_value=1)` — minimum 1 unit required
- `ends_at`: `DateTimeField()` — must be a timezone-aware datetime
- `product_id` (read-only, returned in response): `IntegerField(read_only=True)`

Custom `validate_ends_at(value)` method:
- Import `timezone` from `django.utils`.
- Raise `serializers.ValidationError` if `value <= timezone.now()`.
- Return `value`.

### FlashSaleView

Class: `FlashSaleView(APIView)` in `views.py`.

Permission class: `IsCommunityAdminOrProductVendorOwner` (from `apps.catalogue.permissions`, built in section 04).

`get_object()` helper:
- Resolves community from `slug` URL kwarg.
- Calls `get_object_or_404(Product, pk=self.kwargs['product_id'], community=community)`.

`post(request, slug, product_id)`:
1. Call `get_object()` to retrieve the product.
2. Call `self.check_object_permissions(request, product)` explicitly — DRF does not call `check_object_permissions` automatically on `APIView`, only on `GenericAPIView`/`ViewSet`.
3. Validate the product is active (`product.is_active`). If not, return `Response({"detail": "Cannot activate flash sale on an inactive product."}, status=HTTP_400_BAD_REQUEST)`.
4. Instantiate `FlashSaleSerializer(data=request.data)` and call `.is_valid(raise_exception=True)`.
5. Write to the product:
   ```
   product.is_flash_sale = True
   product.flash_sale_qty = serializer.validated_data['qty']
   product.flash_sale_qty_remaining = serializer.validated_data['qty']
   product.flash_sale_ends_at = serializer.validated_data['ends_at']
   product.save(update_fields=['is_flash_sale', 'flash_sale_qty', 'flash_sale_qty_remaining', 'flash_sale_ends_at'])
   ```
6. Return `Response({"detail": "Flash sale activated.", "product_id": product.pk}, status=HTTP_200_OK)`.

Note on `flash_sale_qty_remaining`: this is set equal to `qty` at activation time. Split 05 decrements it atomically using a conditional `F()` update when orders are placed.

There is intentionally no deactivation endpoint. Flash sales expire via either the `expire_flash_sales` Celery task (runs every 15 minutes, clears all four flash sale fields on expired products) or naturally when `flash_sale_qty_remaining` hits 0 (which prevents further orders without deactivating the flag).

### ConsolidatedOrderSheetView

Class: `ConsolidatedOrderSheetView(APIView)` in `views.py`.

Permission class: `IsVendorOfCommunity` (from existing permissions, checks vendor role in JWT and community_id claim match — from split 01/04 foundations).

`get(request)`:
1. Parse optional `date` query param (`request.query_params.get('date')`). If absent, default to `timezone.localdate()` (today in IST). If present, parse with `datetime.date.fromisoformat(date_str)`, returning 400 on invalid format.
2. Return:
   ```python
   Response({
       "date": date.isoformat(),
       "total_orders": 0,
       "by_building": {}
   })
   ```

This stub is intentionally minimal. The real implementation is in split 05. The URL must be registered now so split 05 fills the logic without URL changes.

---

## Permissions Summary

| Endpoint | Permission |
|---|---|
| `POST .../feature/` | `IsCommunityAdmin` |
| `DELETE .../feature/` | `IsCommunityAdmin` |
| `POST .../flash-sale/` | `IsCommunityAdminOrProductVendorOwner` |
| `GET .../orders/consolidated/` | `IsVendorOfCommunity` |

`IsCommunityAdmin` is expected to already exist from split 01 (Foundation auth). `IsCommunityAdminOrProductVendorOwner` is defined in section 04 of this split. `IsVendorOfCommunity` is also from split 01.

---

## Key Invariants

**Community scoping via `get_object_or_404`:** Both `ProductFeatureView` and `FlashSaleView` resolve the product with `Product.objects.get(pk=product_id, community=community)`. This means a product in a different community is a 404, not merely a 403. This prevents information leakage about whether a product ID exists in another community.

**`check_object_permissions` must be called explicitly in `FlashSaleView`:** `IsCommunityAdminOrProductVendorOwner` is an object-level permission. On `APIView` (not `GenericAPIView`), DRF does not call `check_object_permissions` automatically. The `post()` method must call `self.check_object_permissions(request, product)` after retrieving the product.

**Flash sale validation order:** Validate that the product is active before running the serializer. Returning 400 for an inactive product before running serializer validation gives a clearer error message and avoids unnecessary serializer overhead.

**`save(update_fields=...)` everywhere:** All writes in this section use `update_fields` to avoid accidentally overwriting concurrent field changes. This is especially important for flash sale activation, which writes four fields atomically at the model level.

**`flash_sale_qty_remaining` initialized to `qty`:** At activation, both `flash_sale_qty` (the cap) and `flash_sale_qty_remaining` (the running counter) are set to `qty`. Split 05 only decrements `flash_sale_qty_remaining`, never `flash_sale_qty`, so the original cap is always preserved for display.

**Consolidated order sheet stub must not return live data:** This endpoint intentionally returns hard-coded zeros. The test should assert that the response shape (`date`, `total_orders`, `by_building`) is correct and that `total_orders` is `0`. Split 05 will replace the body; keeping the test expectation minimal avoids test churn.