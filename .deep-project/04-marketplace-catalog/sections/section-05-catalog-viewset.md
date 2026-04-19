Now I have all the context needed. Let me generate the section content for `section-05-catalog-viewset`.

# Section 05: Community Catalog ViewSet

## Overview

This section implements `CommunityProductViewSet`, a `ReadOnlyModelViewSet` that serves the community-scoped product browsing API. It is the primary discovery surface for residents browsing their community's marketplace.

**Dependencies (must be completed first):**
- `section-01-models` — `Product`, `DailyInventory`, `Category`, `ProductImage` models
- `section-02-storage-utils` — `get_presigned_url` (used in `ProductListSerializer` for primary image thumbnail)
- `section-04-filters-permissions` — `ProductFilterSet`, JWT community membership check

**File to create:** `/var/www/html/MadGirlfriend/namma-neighbour/namma_neighbor/apps/catalogue/views.py` (add `CommunityProductViewSet`; this file also holds `ProductDetailView` from section-06 and `VendorProductViewSet` from section-07 — coordinate accordingly)

**URL registration:** `namma_neighbor/apps/catalogue/urls.py` — register at `communities/{slug}/products/`

---

## Tests First

File: `namma_neighbor/apps/catalogue/tests/test_catalog_viewset.py`

Testing stack: pytest + pytest-django, factory_boy, freezegun. All tests require an authenticated resident JWT with `community_id` embedded.

### Test stubs

```python
class TestCommunityProductViewSetQueryset:
    """GET /communities/{slug}/products/ — queryset scoping"""

    def test_only_active_products_returned(self, resident_client, community, product_factory):
        """Active products appear; inactive products are excluded."""

    def test_other_community_products_excluded(self, resident_client, community, other_community, product_factory):
        """Products belonging to a different community are never returned."""

    def test_non_resident_gets_403(self, other_community_client, community):
        """A resident whose JWT community_id does not match the URL slug gets 403."""


class TestCommunityProductViewSetFilters:
    """Filter behaviour via ProductFilterSet"""

    def test_category_filter_by_slug(self, resident_client, community, product_factory, category_factory):
        """?category=<slug> returns only products in that category."""

    def test_vendor_filter_by_id(self, resident_client, community, product_factory, vendor_factory):
        """?vendor=<id> returns only that vendor's products."""

    def test_ordering_by_price_ascending(self, resident_client, community, product_factory):
        """?ordering=price returns results ordered cheapest first."""

    def test_ordering_by_rating_descending(self, resident_client, community, product_factory):
        """?ordering=-rating maps to vendor__average_rating descending."""


class TestCommunityProductViewSetPagination:
    """Dynamic pagination: cursor vs limit-offset"""

    def test_default_browse_uses_cursor_pagination(self, resident_client, community, product_factory):
        """No ?ordering param → response contains 'next' cursor link, not 'offset'."""

    def test_ordering_param_uses_limit_offset_pagination(self, resident_client, community, product_factory):
        """?ordering=price → response contains 'count' and 'offset' fields (LimitOffsetPagination)."""


class TestIsAvailableTodayAnnotation:
    """is_available_today annotation via Coalesce subquery"""

    def test_no_daily_inventory_row_means_available(self, resident_client, community, product):
        """Product with no DailyInventory row for today: is_available_today=True (COALESCE treats NULL as 0)."""

    def test_qty_ordered_at_max_means_unavailable(self, resident_client, community, product, daily_inventory_factory):
        """Product where qty_ordered >= max_daily_qty: is_available_today=False."""


class TestTodaysDropsAction:
    """GET /communities/{slug}/products/todays-drops/"""

    def test_returns_products_for_todays_weekday(self, resident_client, community, product_factory, freezer):
        """Products with today's weekday in delivery_days and available_to in the future are returned."""

    def test_excludes_products_not_in_todays_delivery_days(self, resident_client, community, product_factory, freezer):
        """Products for a different weekday are excluded."""

    def test_excludes_products_where_window_has_closed(self, resident_client, community, product_factory, freezer):
        """Products whose available_to is in the past (IST) are excluded."""

    def test_flash_sale_products_sort_to_top(self, resident_client, community, product_factory, freezer):
        """Flash sale products appear before regular products in todays-drops results."""


class TestFlashSalesAction:
    """GET /communities/{slug}/products/flash-sales/"""

    def test_returns_active_flash_sales_only(self, resident_client, community, product_factory):
        """Products with is_flash_sale=True, flash_sale_qty_remaining > 0, flash_sale_ends_at > now are returned."""

    def test_excludes_expired_flash_sales(self, resident_client, community, product_factory, freezer):
        """Flash sale whose ends_at has passed is excluded even if Celery expiry task has not run yet."""

    def test_excludes_flash_sales_with_zero_remaining_qty(self, resident_client, community, product_factory):
        """Flash sale with flash_sale_qty_remaining=0 is excluded."""


class TestSubscriptionsAction:
    """GET /communities/{slug}/products/subscriptions/"""

    def test_returns_only_subscription_products(self, resident_client, community, product_factory):
        """Only products with is_subscription=True are returned."""

    def test_non_subscription_products_excluded(self, resident_client, community, product_factory):
        """Products with is_subscription=False are excluded."""
```

---

## Implementation

### File: `namma_neighbor/apps/catalogue/views.py`

Add `CommunityProductViewSet` to this file. The other sections (`ProductDetailView`, `VendorProductViewSet`) are added in sections 06 and 07.

#### Required imports

```python
from django.utils import timezone
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import CursorPagination, LimitOffsetPagination
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from apps.catalogue.models import Product, DailyInventory
from apps.catalogue.serializers import ProductListSerializer
from apps.catalogue.filters import ProductFilterSet
from apps.communities.models import Community
```

#### Pagination classes

Define two small pagination classes in `views.py` (or in a `pagination.py` file in the same app):

```python
class CatalogCursorPagination(CursorPagination):
    """Default: stable cursor pagination on -created_at. Prevents duplicate products when new listings arrive mid-browse."""
    ordering = '-created_at'
    page_size = 20

class CatalogLimitOffsetPagination(LimitOffsetPagination):
    """Used when ?ordering param is present, because cursor pagination requires a fixed ordering field."""
    default_limit = 20
```

#### CommunityProductViewSet

```python
class CommunityProductViewSet(ReadOnlyModelViewSet):
    """
    ReadOnlyModelViewSet scoped to a single community.
    URL: communities/{slug}/products/
    Nested router param: slug (community slug from URL).

    Security: community_id in JWT must match the resolved community.
    Filtering: ProductFilterSet (category, vendor, is_flash_sale, is_subscription, is_featured).
    Ordering: price, -price, rating, -rating (rating maps to vendor__average_rating).
    Pagination: CursorPagination by default; LimitOffsetPagination when ?ordering is present.
    """
    serializer_class = ProductListSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = ProductFilterSet
    ordering_fields = ['price', 'rating']  # 'rating' remapped to vendor__average_rating in get_queryset

    @property
    def pagination_class(self):
        """Switch pagination strategy based on whether ?ordering is present."""
        ...

    def get_queryset(self):
        """
        1. Resolve Community from URL kwarg 'slug'.
        2. Validate request.user JWT community_id matches community.id — raise PermissionDenied if not.
        3. Filter Product.objects.filter(community=community, is_active=True).
        4. select_related('vendor', 'category'), prefetch_related('images').
        5. Annotate today_qty_ordered using Coalesce(Subquery(DailyInventory...), 0).
        6. If ?ordering=rating or ?ordering=-rating, remap to vendor__average_rating.
        """
        ...

    @action(detail=False, methods=['get'], url_path='todays-drops')
    def todays_drops(self, request, slug=None):
        """
        Returns products available today:
        - delivery_days__contains=[today_weekday] (JSONB @> operator — value must be a list, not a bare int)
        - available_to__gt=timezone.localtime().time()
        Flash sale products sorted to the top of results.
        Uses ProductListSerializer, respects pagination.
        """
        ...

    @action(detail=False, methods=['get'], url_path='flash-sales')
    def flash_sales(self, request, slug=None):
        """
        Returns active flash sales:
        - is_flash_sale=True
        - flash_sale_qty_remaining__gt=0
        - flash_sale_ends_at__gt=timezone.now()
        Uses ProductListSerializer, respects pagination.
        """
        ...

    @action(detail=False, methods=['get'], url_path='subscriptions')
    def subscriptions(self, request, slug=None):
        """
        Returns subscription products:
        - is_subscription=True
        Uses ProductListSerializer, respects pagination.
        """
        ...
```

### Key implementation details

**Community scoping and resident validation:**

In `get_queryset()`, resolve the community with `get_object_or_404(Community, slug=self.kwargs['slug'])`. Then compare `community.id` against `request.user.community_id` (the claim from the JWT). If they do not match, raise `PermissionDenied`. This check must happen in `get_queryset()` (not a permission class) because it requires the resolved community object.

**`is_available_today` annotation:**

Annotate the queryset with `today_qty_ordered`:

```python
today = timezone.localdate()
today_qty_subq = DailyInventory.objects.filter(
    product=OuterRef('pk'),
    date=today
).values('qty_ordered')[:1]

qs = qs.annotate(
    today_qty_ordered=Coalesce(Subquery(today_qty_subq), Value(0))
)
```

The `Coalesce(..., Value(0))` is critical: when no `DailyInventory` row exists for today, the subquery returns NULL. Without Coalesce, the serializer would receive NULL and could incorrectly mark the product as unavailable. The full `is_available_today` boolean is then computed in `ProductListSerializer.to_representation()` using `today_qty_ordered` plus Python checks for `delivery_days`, window, and flash sale.

**`todays-drops` delivery day filter:**

Use `delivery_days__contains=[today_weekday]` (a list, not a bare integer). PostgreSQL JSONB `@>` containment requires the right side to be the same JSON type as what is stored. Since `delivery_days` is stored as a list of ints, the filter value must also be a list: `[0]` not `0`. A bare integer will silently return zero results.

Example:
```python
today_weekday = timezone.localtime().weekday()  # 0=Monday
qs = self.get_queryset().filter(
    delivery_days__contains=[today_weekday],
    available_to__gt=timezone.localtime().time(),
)
```

Flash sale products sort to the top via annotation + ordering:

```python
from django.db.models import Case, When, IntegerField
qs = qs.annotate(
    flash_priority=Case(
        When(is_flash_sale=True, then=Value(0)),
        default=Value(1),
        output_field=IntegerField()
    )
).order_by('flash_priority', '-created_at')
```

**`rating` ordering remapping:**

`OrderingFilter` expects field names to match model fields. Since `rating` is not a field on `Product`, override `filter_queryset()` or intercept in `get_queryset()`: when `request.query_params.get('ordering')` contains `rating` or `-rating`, manually apply `order_by('vendor__average_rating')` or `order_by('-vendor__average_rating')` and strip the `rating` term so `OrderingFilter` does not error on an unrecognised field.

**Dynamic pagination:**

```python
@property
def pagination_class(self):
    if self.request.query_params.get('ordering'):
        return CatalogLimitOffsetPagination
    return CatalogCursorPagination
```

Note: `pagination_class` is normally a class attribute on `GenericAPIView`. Returning a class from a `@property` works with DRF because DRF reads `self.pagination_class` and then calls `self.pagination_class()` — the property returns the class itself, not an instance.

**Paginating custom actions:**

Each custom action (`todays_drops`, `flash_sales`, `subscriptions`) must manually invoke pagination since they do not use the default `list()` method. The standard pattern:

```python
qs = self.filter_queryset(base_qs)
page = self.paginate_queryset(qs)
if page is not None:
    serializer = self.get_serializer(page, many=True)
    return self.get_paginated_response(serializer.data)
serializer = self.get_serializer(qs, many=True)
return Response(serializer.data)
```

### File: `namma_neighbor/apps/catalogue/urls.py`

Register `CommunityProductViewSet` using a nested router. The exact nested router setup depends on which router package is used (drf-nested-routers is recommended). The community-level URLs should resolve as:

```
GET /api/v1/communities/{slug}/products/               → CommunityProductViewSet.list
GET /api/v1/communities/{slug}/products/{pk}/          → CommunityProductViewSet.retrieve
GET /api/v1/communities/{slug}/products/todays-drops/  → CommunityProductViewSet.todays_drops
GET /api/v1/communities/{slug}/products/flash-sales/   → CommunityProductViewSet.flash_sales
GET /api/v1/communities/{slug}/products/subscriptions/ → CommunityProductViewSet.subscriptions
```

The `slug` URL kwarg must be passed through to the viewset. With drf-nested-routers, the parent router uses `lookup_field = 'slug'` for the community resource.

### File: `namma_neighbor/apps/catalogue/serializers.py`

`ProductListSerializer` must handle the `today_qty_ordered` annotation injected by the viewset. Add an `is_available_today` `SerializerMethodField` that:

1. Reads `obj.today_qty_ordered` (set by viewset annotation; fall back to `0` if not present for single-object contexts)
2. Checks `obj.delivery_days` contains today's weekday integer (IST)
3. Checks current IST time is between `obj.available_from` and `obj.available_to`
4. Checks `today_qty_ordered < obj.max_daily_qty`
5. If `obj.is_flash_sale`: also checks `obj.flash_sale_qty_remaining > 0` and `obj.flash_sale_ends_at > timezone.now()`

All five conditions must be true for `is_available_today=True`.

Also include `primary_image_thumbnail_url` as a `SerializerMethodField` that calls `get_presigned_url(image.thumbnail_s3_key)` for the primary image, returning `None` if no primary image or no thumbnail key exists yet.

---

## Edge Cases and Invariants

**NULL from DailyInventory subquery:** When no row exists for `(product, today)`, the Coalesce ensures `today_qty_ordered=0`. This means a brand-new product with no order history is correctly shown as available (assuming window and day checks pass). Do not invert this logic.

**Cursor pagination breaks under custom ordering:** `CursorPagination` requires the ordering field to be stable and known at pagination-class definition time. When the client passes `?ordering=price`, the cursor would need to encode a price value — but price is not guaranteed unique and the cursor implementation in DRF cannot handle arbitrary fields gracefully. Switching to `LimitOffsetPagination` for any request with `?ordering` is the correct trade-off.

**Flash sale real-time exclusion:** The `/flash-sales/` action applies `flash_sale_ends_at__gt=timezone.now()` directly on the queryset. This means expired flash sales are excluded immediately from browse results, even if the `expire_flash_sales` Celery task has not run yet (it runs every 15 minutes). The task is for data hygiene, not for browse correctness.

**IST for window and day checks:** All comparisons involving `available_from`, `available_to`, and `delivery_days` must use IST local time via `timezone.localtime()` and `timezone.localdate()`. The project has `TIME_ZONE = 'Asia/Kolkata'` — but in code, always use the `timezone.*` functions explicitly rather than relying on `datetime.now()`, which returns server local time and may not match IST if the server runs in UTC.

**Resident-only access:** A user whose JWT does not carry the matching `community_id` for the requested community slug gets a `PermissionDenied` (403). This is enforced in `get_queryset()` and therefore applies to all actions on the viewset, including `todays_drops`, `flash_sales`, and `subscriptions`.