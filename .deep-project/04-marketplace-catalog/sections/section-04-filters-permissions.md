Now I have all the context needed. Let me generate the section content for `section-04-filters-permissions`.

# Section 04: Filters and Permissions

## Overview

This section implements the `ProductFilterSet` (django-filter), `IsApprovedVendor`, and `IsCommunityAdminOrProductVendorOwner` permission classes for the catalogue app.

**Dependencies:** section-01-models must be complete before this section. Specifically, `Product`, `Category`, and `Vendor` models must be importable from `apps.catalogue.models` and `apps.vendors.models`.

**Blocked sections:** section-05-catalog-viewset, section-06-product-detail, section-07-vendor-management, and section-09-admin-endpoints all import from `filters.py` and `permissions.py` — they cannot be started until this section is done.

---

## Files to Create/Modify

- `/var/www/html/MadGirlfriend/namma-neighbour/namma_neighbor/apps/catalogue/filters.py` — create new
- `/var/www/html/MadGirlfriend/namma-neighbour/namma_neighbor/apps/catalogue/permissions.py` — create new
- `/var/www/html/MadGirlfriend/namma-neighbour/namma_neighbor/apps/catalogue/tests/test_filters_permissions.py` — create new

---

## Tests First

File: `namma_neighbor/apps/catalogue/tests/test_filters_permissions.py`

Testing stack: pytest + pytest-django, factory_boy for fixtures.

### ProductFilterSet Tests

```python
class TestProductFilterSet:
    """Tests for apps.catalogue.filters.ProductFilterSet."""

    def test_category_filter_by_slug(self, community, vendor):
        """Filter by category slug returns only products in that category."""

    def test_vendor_filter_by_id(self, community, vendor):
        """Filter by vendor id returns only that vendor's products."""

    def test_is_flash_sale_filter(self, community, vendor):
        """is_flash_sale=true returns only active flash sale products."""

    def test_is_subscription_filter(self, community, vendor):
        """is_subscription=true returns only subscription products."""

    def test_is_featured_filter(self, community, vendor):
        """is_featured=true returns only featured products."""
```

Key fixture notes:
- Use factory_boy `ProductFactory`, `CategoryFactory`, `VendorFactory` from the test factories module.
- Community scoping and `is_active=True` filtering is NOT part of the FilterSet — those are applied in `get_queryset()`. Tests here should apply the FilterSet directly to an unfiltered queryset to isolate filter behavior.
- To apply the FilterSet in a test: `filterset = ProductFilterSet(data={'category': slug}, queryset=Product.objects.all())` then assert on `filterset.qs`.

### IsApprovedVendor Tests

```python
class TestIsApprovedVendor:
    """Tests for apps.catalogue.permissions.IsApprovedVendor."""

    def test_approved_vendor_passes(self, api_request_factory):
        """Vendor with status=APPROVED passes the permission check."""

    def test_draft_vendor_returns_403(self, api_request_factory):
        """Vendor with status=DRAFT is denied (403)."""

    def test_pending_review_vendor_returns_403(self, api_request_factory):
        """Vendor with status=PENDING_REVIEW is denied."""

    def test_suspended_vendor_returns_403(self, api_request_factory):
        """Vendor with status=SUSPENDED is denied."""
```

Key notes:
- Build a mock request using `APIRequestFactory`, attach a user with `vendor_profile_profile` attribute pointing to a mock `Vendor` instance.
- `IsApprovedVendor.has_permission(request, view)` must return `True` only for `VendorStatus.APPROVED`.
- The permission also checks `IsVendorOfCommunity` (the base vendor role + community_id JWT check from split 01). In unit tests, mock or satisfy that check so the APPROVED status is the only variable.
- Import `VendorStatus` from `apps.vendors.models`.

### IsCommunityAdminOrProductVendorOwner Tests

```python
class TestIsCommunityAdminOrProductVendorOwner:
    """Tests for apps.catalogue.permissions.IsCommunityAdminOrProductVendorOwner."""

    def test_community_admin_for_matching_community_passes(self, api_request_factory, product):
        """User with community admin JWT claim for product's community → passes object permission."""

    def test_vendor_owner_of_product_passes(self, api_request_factory, product):
        """Vendor who owns the product → passes object permission."""

    def test_non_admin_non_owner_returns_403(self, api_request_factory, product):
        """User who is neither admin nor owner → denied."""
```

Key notes:
- This is an object-level permission: call `has_object_permission(request, view, product)`.
- Admin path: check JWT claims (`request.user` has `is_community_admin=True` or equivalent role claim and matching `community_id`). No DB query for the admin path.
- Vendor owner path: compare `request.user.vendor_profile_profile` to `product.vendor` (a FK comparison). This does hit the DB.
- When neither condition is met, `has_object_permission` must return `False` (DRF converts this to 403).

---

## Implementation Details

### `filters.py`

Uses `django_filters.FilterSet`. Community scoping (`community=...`) and `is_active=True` are intentionally excluded from the FilterSet because they are security-critical — a client must never be able to override them. They are applied in `get_queryset()` on the ViewSet.

The FilterSet handles only optional discovery filters:

| Filter param | Type | Lookups against |
|---|---|---|
| `category` | CharFilter | `category__slug` (exact) |
| `vendor` | NumberFilter | `vendor__id` (exact) |
| `is_flash_sale` | BooleanFilter | `is_flash_sale` |
| `is_subscription` | BooleanFilter | `is_subscription` |
| `is_featured` | BooleanFilter | `is_featured` |

```python
# namma_neighbor/apps/catalogue/filters.py

import django_filters
from .models import Product


class ProductFilterSet(django_filters.FilterSet):
    """
    Optional client-facing filters for the product catalog.

    Security note: community scoping and is_active=True are NOT here.
    They are enforced in ViewSet.get_queryset() and cannot be overridden by clients.
    """
    category = django_filters.CharFilter(field_name='category__slug', lookup_expr='exact')
    vendor = django_filters.NumberFilter(field_name='vendor__id', lookup_expr='exact')
    is_flash_sale = django_filters.BooleanFilter()
    is_subscription = django_filters.BooleanFilter()
    is_featured = django_filters.BooleanFilter()

    class Meta:
        model = Product
        fields = ['category', 'vendor', 'is_flash_sale', 'is_subscription', 'is_featured']
```

Wire up in the ViewSet with:
```python
filter_backends = [DjangoFilterBackend, OrderingFilter]
filterset_class = ProductFilterSet
```

### `permissions.py`

#### IsApprovedVendor

Logic: Two conditions combined with AND:
1. `IsVendorOfCommunity` from split 01 (`apps.auth.permissions` or wherever it lives) — verifies the user has the vendor role in their JWT and their `community_id` JWT claim matches the URL community.
2. `request.user.vendor_profile_profile.status == VendorStatus.APPROVED` — checked against the database.

If the vendor exists but is not APPROVED (e.g., DRAFT, PENDING_REVIEW, SUSPENDED), this must return `False` (HTTP 403), not raise a 404 or 500.

```python
class IsApprovedVendor(BasePermission):
    """
    Passes only if:
    - User has vendor role in JWT and community_id matches (IsVendorOfCommunity).
    - vendor_profile_profile.status == VendorStatus.APPROVED.
    """

    def has_permission(self, request, view) -> bool:
        """Check vendor role (JWT) then APPROVED status (DB)."""
        ...
```

Note: The reverse accessor from `User` to `Vendor` is `vendor_profile_profile` (not `vendor_profile`). This is because `Vendor` has `OneToOneField(User, related_name='vendor_profile')` and the split 01 base also defines something with `vendor_profile` — the actual reverse is `vendor_profile_profile` per the project spec. Use `getattr(request.user, 'vendor_profile_profile', None)` with a `None` guard to avoid `RelatedObjectDoesNotExist`.

#### IsCommunityAdminOrProductVendorOwner

Object-level permission (`has_object_permission`). The `obj` passed in is a `Product` instance.

Two paths — either is sufficient:
1. **Admin path (JWT-only, no DB):** Check JWT claims on `request.user`. The claim that indicates community admin status comes from split 01's auth system. Compare `request.auth['community_id']` (or equivalent) to `obj.community_id`. Return `True` if match + admin role.
2. **Vendor owner path (DB FK):** `getattr(request.user, 'vendor_profile_profile', None)` and compare `.id` to `obj.vendor_id`. Return `True` if they match.

If neither passes: return `False`.

```python
class IsCommunityAdminOrProductVendorOwner(BasePermission):
    """
    Object-level permission for flash sale activation and feature toggles.

    Passes if:
    - User is a community admin for the product's community (checked via JWT).
    - OR user is the vendor who owns the product (checked via DB FK).
    """

    def has_object_permission(self, request, view, obj) -> bool:
        """obj is a Product instance."""
        ...
```

---

## Background Context

### JWT Claim Structure (from split 01)

Auth tokens embed `community_id` and a `role` field. Roles relevant here:
- `vendor` — base vendor role (used by `IsVendorOfCommunity`)
- `community_admin` — community admin role (used by `IsCommunityAdminOrProductVendorOwner`)

Access claims via `request.auth` (the decoded payload dict). The exact key names are established in split 01's `apps.auth` module. Consult `IsVendorOfCommunity` from split 01 for the canonical pattern.

### VendorStatus Values (from split 03)

`apps.vendors.models.VendorStatus` is a `TextChoices` enum with at minimum: `DRAFT`, `PENDING_REVIEW`, `APPROVED`, `SUSPENDED`. Only `APPROVED` should pass `IsApprovedVendor`.

### vendor_profile_profile Accessor

The `Vendor` model in split 03 defines:
```python
user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name='vendor_profile', ...)
```
Because of how this interacts with the rest of the codebase, the reverse accessor on `User` ends up as `vendor_profile_profile`. Always use `request.user.vendor_profile_profile` — not `request.user.vendor_profile` — throughout this split and all downstream sections.

---

## Integration Checklist

- [ ] `ProductFilterSet` in `filters.py`, class `Meta` points to `Product` model
- [ ] `category` filter uses `field_name='category__slug'` (not `category__id`)
- [ ] `IsApprovedVendor`: guards against `AttributeError`/`RelatedObjectDoesNotExist` with a `getattr` + `None` check
- [ ] `IsCommunityAdminOrProductVendorOwner`: admin path hits zero DB queries; vendor path hits one FK comparison
- [ ] Both permission classes return `False` (not raise exceptions) when conditions are not met
- [ ] Both files importable from `apps.catalogue.filters` and `apps.catalogue.permissions`
- [ ] Tests cover all status variants for `IsApprovedVendor` (DRAFT, PENDING_REVIEW, SUSPENDED all denied)
- [ ] Tests cover all three cases for `IsCommunityAdminOrProductVendorOwner` (admin, owner, neither)