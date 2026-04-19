Now I have all the information needed to generate the section content.

# Section 10: Django Admin

## Overview

This section implements the Django Admin configuration for the `catalogue` app. It registers `Category` and `Product` (with an inline for `ProductImage`) with appropriate list displays, filters, prepopulated fields, and a custom bulk-deactivate action. This section is self-contained once **section-01-models** is complete.

## Dependencies

- **section-01-models** must be complete. The admin simply registers the models defined there (`Category`, `Product`, `ProductImage`) — no other sections are required.

## File to Create

`/var/www/html/MadGirlfriend/namma-neighbour/namma_neighbor/apps/catalogue/admin.py`

## Tests

There are no dedicated TDD stubs for the Django Admin in `claude-plan-tdd.md`. Admin correctness is validated manually via the Django Admin interface or optionally via Django's `AdminSite` test utilities. If you want automated coverage, the conventional approach is:

```python
# tests/test_admin.py (optional, not required for MVP)

class TestCatalogueAdmin:
    def test_category_admin_registered(self):
        """CategoryAdmin is registered with the default admin site."""

    def test_product_admin_registered(self):
        """ProductAdmin is registered with the default admin site."""

    def test_bulk_deactivate_action(self, admin_client, product_factory):
        """Selecting products and running bulk_deactivate sets is_active=False on all."""

    def test_product_image_inline_visible(self, admin_client, product_factory):
        """ProductImage inline appears on the Product change page."""
```

These tests are optional. The critical behaviour (bulk deactivation) can also be covered under integration tests for the model layer.

## Implementation Details

### CategoryAdmin

Register `Category` with the following configuration:

- `prepopulated_fields = {'slug': ('name',)}` — the slug field auto-fills from the name field in the admin UI.
- `list_display` should include: `name`, `slug`, `requires_fssai`, `requires_gstin`.
- `search_fields` on `name` and `slug` for quick lookup.
- No special actions needed — standard CRUD is sufficient.

Stub:

```python
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin config for Category. Prepopulates slug from name."""
    prepopulated_fields = {'slug': ('name',)}
    list_display = (...)
    search_fields = (...)
```

### ProductImageInline

An inline for `ProductImage` nested inside `ProductAdmin`:

- Use `admin.TabularInline` (not `StackedInline`) to keep images compact in a table layout.
- `model = ProductImage`
- `extra = 0` — do not display empty extra form rows (images are uploaded via the API, not the admin).
- `readonly_fields` should include `thumbnail_s3_key`, `thumbnail_s3_key_small`, and the image field itself — these are managed programmatically and should not be hand-edited.
- `fields` (or `readonly_fields`) can include `image`, `is_primary`, `display_order`.

Stub:

```python
class ProductImageInline(admin.TabularInline):
    """Read-mostly inline showing uploaded images for a product."""
    model = ProductImage
    extra = 0
    readonly_fields = (...)
```

### ProductAdmin

Register `Product` with the following configuration:

**`list_display`:** `name`, `community`, `vendor`, `category`, `is_active`, `is_featured`, `price`. This lets administrators scan catalog health at a glance.

**`list_filter`:** `community`, `category`, `is_active`, `is_featured`, `is_flash_sale`. Standard Django right-sidebar filters — no custom filter classes needed here.

**`search_fields`:** `name`, `vendor__user__phone_number` (or `vendor__display_name` — use whatever string field Vendor exposes for admin search). Include `community__name` as well.

**`readonly_fields`:** `created_at`, `updated_at` (from `TimestampedModel`), `flash_sale_qty_remaining` (managed atomically by order logic in split 05 — should not be hand-edited).

**`inlines`:** `[ProductImageInline]`

**`ordering`:** `['-created_at']` by default so newest products appear first.

**Custom action — `bulk_deactivate`:**

```python
@admin.action(description="Deactivate selected products")
def bulk_deactivate(modeladmin, request, queryset):
    """Sets is_active=False on all selected products (soft-delete equivalent)."""
    updated = queryset.update(is_active=False)
    modeladmin.message_user(request, f"{updated} product(s) deactivated.")
```

Add this action to `ProductAdmin.actions = [bulk_deactivate]`.

Stub:

```python
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin config for Product. Includes image inline and bulk-deactivate action."""
    list_display = (...)
    list_filter = (...)
    search_fields = (...)
    readonly_fields = (...)
    inlines = [ProductImageInline]
    actions = [bulk_deactivate]
    ordering = ['-created_at']
```

## Complete File Skeleton

```python
# namma_neighbor/apps/catalogue/admin.py

from django.contrib import admin
from .models import Category, Product, ProductImage


@admin.action(description="Deactivate selected products")
def bulk_deactivate(modeladmin, request, queryset):
    """Bulk-sets is_active=False. Does not destroy records (preserves order FKs)."""
    ...


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """CRUD admin for Category. Slug auto-fills from name."""
    prepopulated_fields = {'slug': ('name',)}
    list_display = ('name', 'slug', 'requires_fssai', 'requires_gstin')
    search_fields = ('name', 'slug')


class ProductImageInline(admin.TabularInline):
    """Tabular inline for ProductImage within ProductAdmin."""
    model = ProductImage
    extra = 0
    readonly_fields = ('thumbnail_s3_key', 'thumbnail_s3_key_small')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin for Product with community/category filters and image inline."""
    list_display = ('name', 'community', 'vendor', 'category', 'is_active', 'is_featured', 'price')
    list_filter = ('community', 'category', 'is_active', 'is_featured', 'is_flash_sale')
    search_fields = ('name', 'community__name')
    readonly_fields = ('created_at', 'updated_at', 'flash_sale_qty_remaining')
    inlines = [ProductImageInline]
    actions = [bulk_deactivate]
    ordering = ['-created_at']
```

## Implementation Notes

- The `bulk_deactivate` action is a module-level function decorated with `@admin.action`. It must be defined before the `ProductAdmin` class that references it in `actions`.
- `flash_sale_qty_remaining` is a `readonly_field` because it is decremented atomically by split 05's order logic using `F()` expressions and a `__gt=0` guard. Manual edits via admin would break that invariant.
- `extra = 0` on the inline is intentional. Product images are uploaded exclusively through the `ProductImageViewSet` API (section-08), which handles WebP conversion, S3 upload, thumbnail dispatch, and `is_primary` logic. Allowing the admin to upload raw files via the inline would bypass all of that. The inline is read-only context for administrators inspecting a product.
- If `display_order` needs to be editable for reordering purposes, it can be removed from `readonly_fields` in `ProductImageInline` — but `image`, `thumbnail_s3_key`, and `thumbnail_s3_key_small` should remain read-only.
- `TimestampedModel` fields (`created_at`, `updated_at`) are auto-set and must be in `readonly_fields` for Django Admin to display them (they are non-editable fields).

## Quick TODO List

1. Create/open `/var/www/html/MadGirlfriend/namma-neighbour/namma_neighbor/apps/catalogue/admin.py`.
2. Import `admin` from `django.contrib`, and `Category`, `Product`, `ProductImage` from `.models`.
3. Define `bulk_deactivate` as a module-level `@admin.action` function.
4. Implement `CategoryAdmin` with `prepopulated_fields`, `list_display`, `search_fields`.
5. Implement `ProductImageInline` as `TabularInline` with `extra=0` and appropriate `readonly_fields`.
6. Implement `ProductAdmin` with `list_display`, `list_filter`, `search_fields`, `readonly_fields`, `inlines`, `actions`, `ordering`.
7. Run `uv run python manage.py check` to confirm no import errors.
8. Manually verify in the admin UI: slug auto-fills on Category, images appear in the inline on Product, bulk deactivate action appears in the action dropdown.