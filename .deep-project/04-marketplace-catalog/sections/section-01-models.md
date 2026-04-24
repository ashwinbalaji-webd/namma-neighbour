Now I have all the context needed. I'll generate the section content for `section-01-models`.

# Section 01: Models

## Overview

This section covers the four Django models that form the data backbone of the `catalogue` app: `Category`, `Product`, `ProductImage`, and `DailyInventory`. It also covers the initial migration with correct cross-app FK dependencies.

No other catalog sections are required before this one. Sections 03, 04, 05, 06, 07, 08, 09, 10, and 11 all depend on this section being complete.

---

## Background and Context

The catalog app lives at `namma_neighbor/apps/catalogue/`. It imports FKs from two already-built apps:

- `communities.Community` — from split 02
- `vendors.Vendor` — from split 03

All models inherit `TimestampedModel` (from split 01), which provides `created_at` and `updated_at` fields.

The Vendor model uses `related_name='vendor_profile'` for its `OneToOneField` to User, meaning the reverse accessor on a User instance is `user.vendor_profile` (i.e., `request.user.vendor_profile`). However, the plan notes the accessor may appear as `vendor_profile_profile` in some contexts — verify the actual `related_name` on the existing Vendor model before writing permission checks.

The project uses `TIME_ZONE = 'Asia/Kolkata'` (IST). All time-window checks in `is_available_today` must compare against `timezone.localtime()`, not `timezone.now()`.

---

## Files to Create or Modify

- `namma_neighbor/apps/catalogue/__init__.py` — empty
- `namma_neighbor/apps/catalogue/apps.py` — standard AppConfig
- `namma_neighbor/apps/catalogue/models.py` — all four models
- `namma_neighbor/apps/catalogue/migrations/0001_initial.py` — initial migration with cross-app dependencies

---

## Tests First

File: `namma_neighbor/apps/catalogue/tests/test_models.py`

Testing stack: pytest + pytest-django, factory_boy for fixtures.

### Category Tests

```python
def test_category_requires_fssai_persists():
    """Category with requires_fssai=True is saved and retrieved correctly."""

def test_category_slug_unique_constraint():
    """Duplicate slug raises IntegrityError at the database level."""
```

### Product Tests

```python
def test_product_is_active_defaults_to_false():
    """is_active must default to False on create (spec override from True)."""

def test_product_clean_rejects_invalid_delivery_days():
    """delivery_days containing 7, -1, or None raises ValidationError."""

def test_product_clean_rejects_available_from_gte_available_to():
    """available_from >= available_to raises ValidationError."""

def test_product_clean_fssai_gate():
    """Product with food category and unverified vendor raises ValidationError."""

def test_product_clean_gstin_gate():
    """Product with GSTIN-required category and blank vendor.gstin raises ValidationError."""

def test_product_composite_indexes_exist():
    """
    Verify three composite DB indexes are present:
    (community, is_active), (community, category, is_active), (vendor, is_active).
    Inspect Product._meta.indexes.
    """
```

### ProductImage Tests

```python
def test_first_image_becomes_primary():
    """First image uploaded to a product auto-sets is_primary=True."""

def test_second_image_does_not_displace_primary():
    """Second image uploaded with is_primary=False leaves first image as primary."""

def test_saving_image_with_is_primary_true_clears_siblings():
    """Saving a new image with is_primary=True clears is_primary on all siblings in same transaction."""

def test_deleting_primary_image_promotes_next_by_display_order():
    """Deleting the primary image promotes the next image (lowest display_order) to primary."""

def test_deleting_last_image_deactivates_product():
    """Deleting the last image sets product.is_active=False."""
```

### DailyInventory Tests

```python
def test_daily_inventory_unique_constraint():
    """Duplicate (product, date) pair raises IntegrityError."""

def test_daily_inventory_default_qty_ordered():
    """qty_ordered defaults to 0 on create."""
```

---

## Implementation Details

### `Category`

Simple lookup table. Fields:

| Field | Type | Notes |
|---|---|---|
| `name` | `CharField` | max_length=100 |
| `slug` | `SlugField` | unique=True |
| `icon_url` | `URLField` | blank=True, null=True |
| `requires_fssai` | `BooleanField` | default=False |
| `requires_gstin` | `BooleanField` | default=False |

`__str__` returns `name`. No custom `save()` or `clean()` needed on Category itself.

### `Product`

Central model. Scoped to both a `vendor` and a `community`. Key design decisions are enumerated below.

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `vendor` | `ForeignKey(Vendor)` | on_delete=PROTECT, related_name='products' |
| `community` | `ForeignKey(Community)` | on_delete=PROTECT, related_name='products' |
| `category` | `ForeignKey(Category)` | on_delete=PROTECT, related_name='products' |
| `name` | `CharField` | max_length=200 |
| `description` | `TextField` | blank=True |
| `price` | `DecimalField` | max_digits=10, decimal_places=2 |
| `unit` | `CharField` | max_length=50 (e.g., "kg", "piece", "dozen") |
| `max_daily_qty` | `PositiveIntegerField` | daily cap ceiling |
| `available_from` | `TimeField` | IST time, order window start |
| `available_to` | `TimeField` | IST time, order window end |
| `delivery_days` | `JSONField` | list of ints 0–6 (0=Monday) |
| `is_active` | `BooleanField` | **default=False** — spec override |
| `is_featured` | `BooleanField` | default=False, set by community admin |
| `is_subscription` | `BooleanField` | default=False |
| `is_flash_sale` | `BooleanField` | default=False |
| `flash_sale_qty` | `PositiveIntegerField` | null=True, blank=True |
| `flash_sale_qty_remaining` | `PositiveIntegerField` | null=True, blank=True |
| `flash_sale_ends_at` | `DateTimeField` | null=True, blank=True |

**`is_active` default is `False`.** This is an intentional override of the original spec (which said `True`). New products are inactive until their first image is uploaded.

**Composite indexes** — define all three in `Meta.indexes`:

```python
class Meta:
    indexes = [
        models.Index(fields=['community', 'is_active']),
        models.Index(fields=['community', 'category', 'is_active']),
        models.Index(fields=['vendor', 'is_active']),
    ]
```

**`clean()` method** — enforce four validation rules:

1. `available_from` must be strictly less than `available_to`. Raise `ValidationError({'available_to': '...'})`.
2. `delivery_days` must be a list of integers, each in range 0–6 with no null entries. Raise `ValidationError({'delivery_days': '...'})` for any violation.
3. FSSAI gate: if `self.category.requires_fssai` is True and `self.vendor.fssai_status != VendorStatus.VERIFIED`, raise `ValidationError('FSSAI verification required to list in this category')`.
4. GSTIN gate: if `self.category.requires_gstin` is True and `not self.vendor.gstin`, raise `ValidationError('GSTIN required to list in this category')`.

The `clean()` method must handle the case where `category` or `vendor` is not yet assigned (guard with `hasattr` or `try/except ObjectDoesNotExist` so partial creates during migrations do not crash).

**`is_available_today` property** — used by the product detail view (single-object path). The list view uses an annotated subquery instead (see section 05).

The property checks all of the following — return `True` only if all pass:

1. Today's IST weekday (`timezone.localtime().weekday()`) is in `self.delivery_days`.
2. Current IST time is between `self.available_from` and `self.available_to`.
3. Daily quota: `qty_ordered < self.max_daily_qty` where `qty_ordered` comes from the `DailyInventory` row for `(self, today_ist_date)`. If no row exists, treat `qty_ordered` as 0.
4. If `self.is_flash_sale` is True: `self.flash_sale_qty_remaining > 0` AND `self.flash_sale_ends_at > timezone.now()`.

### `ProductImage`

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `product` | `ForeignKey(Product)` | on_delete=CASCADE, related_name='images' |
| `image` | `ImageField` | storage=ProductMediaStorage(), upload_to function |
| `thumbnail_s3_key` | `CharField` | max_length=500, blank=True — 400×400 key |
| `thumbnail_s3_key_small` | `CharField` | max_length=500, blank=True — 200×200 key |
| `is_primary` | `BooleanField` | default=False |
| `display_order` | `PositiveIntegerField` | default=0 |

The `upload_to` callable (not a string) should return `media/products/{product_id}/{uuid}.webp`. Define it as a module-level function in `models.py`.

**`save()` override** — two responsibilities:

1. If `self.is_primary` is True: before saving, clear `is_primary=False` on all sibling images (`ProductImage.objects.filter(product=self.product).exclude(pk=self.pk).update(is_primary=False)`). This must happen in the same database transaction as the save.
2. If no primary image exists for the product and `self.is_primary` is not explicitly set, auto-set `is_primary=True` on this (first) image.

The auto-primary logic: after calling `super().save()`, check `ProductImage.objects.filter(product=self.product, is_primary=True).exclude(pk=self.pk).exists()`. If False and `self.is_primary` is False, call `ProductImage.objects.filter(pk=self.pk).update(is_primary=True)`.

A cleaner approach: before `super().save()`, check if `self._state.adding` and `not ProductImage.objects.filter(product=self.product, is_primary=True).exists()`, then set `self.is_primary = True`.

**`delete()` override** — two responsibilities:

1. If `self.is_primary` is True: after deletion, find the next image by `display_order` (`ProductImage.objects.filter(product=self.product).order_by('display_order').first()`) and set `is_primary=True` on it.
2. After deletion, if no images remain (`ProductImage.objects.filter(product=self.product).count() == 0`): set `product.is_active=False` and save.

Note: the `delete()` override fires for single-object deletes (`image.delete()`). It does not fire for `queryset.delete()`. Document this constraint in a comment.

**`Meta.ordering`**: `['display_order']`

### `DailyInventory`

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `product` | `ForeignKey(Product)` | on_delete=CASCADE, related_name='daily_inventory' |
| `date` | `DateField` | the calendar date |
| `qty_ordered` | `PositiveIntegerField` | default=0 |

**`Meta.constraints`**:

```python
constraints = [
    models.UniqueConstraint(fields=['product', 'date'], name='unique_product_date_inventory')
]
```

No custom `save()` or `clean()` needed. Split 05 will add the `qty_ordered` increment logic.

---

## Migration: `0001_initial.py`

The migration must declare dependencies on both upstream apps so the `Community` and `Vendor` tables exist before `Product`'s FK columns are created. Replace `<latest>` with the actual latest migration name for each app at the time of writing.

```python
dependencies = [
    ('communities', '<latest_communities_migration>'),
    ('vendors', '<latest_vendors_migration>'),
]
```

Verify the actual latest migration filenames by inspecting `namma_neighbor/apps/communities/migrations/` and `namma_neighbor/apps/vendors/migrations/` before writing the migration file. Django's `makemigrations` will populate this automatically if the models are correct, but the dependency list must be verified manually.

---

## App Registration

Add `'apps.catalogue'` to `INSTALLED_APPS` in `settings.py`. The `AppConfig` in `apps.py` should have:

```python
class CatalogueConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.catalogue'
    label = 'catalogue'
```

---

## Key Invariants to Preserve

- `Product.is_active` **must default to False**. Any code path that sets it to True before an image is uploaded violates the "no ghost listings" invariant.
- `ProductImage.save()` primary-management and `ProductImage.delete()` primary-promotion must execute in the same DB transaction as the underlying record change to avoid a race window where no image is primary.
- The FSSAI and GSTIN gates in `Product.clean()` are the authoritative validation points at the model layer. The serializer's `validate()` in section 07 duplicates this check at the API layer — both must exist so Django Admin cannot bypass the gates.
- `DailyInventory` rows are created by split 05 (order placement). This section only defines the schema and the `is_available_today` read path. Do not implement any write logic here.

---

## Implementation Notes (Actual)

**Files created:**
- `namma_neighbor/apps/catalogue/models.py` — Category, Product, ProductImage, DailyInventory
- `namma_neighbor/apps/catalogue/migrations/0001_initial.py` — with deps on communities/0003 and vendors/0001
- `namma_neighbor/apps/catalogue/tests/test_models.py` — 20 tests (15 spec + 5 is_available_today)
- `namma_neighbor/apps/catalogue/tests/factories.py` — CategoryFactory, ProductFactory, ProductImageFactory, DailyInventoryFactory
- `namma_neighbor/config/settings/test.py` — added FileSystemStorage override to avoid S3 in tests

**Deviations from plan:**
- `storage=ProductMediaStorage()` omitted from ImageField (deferred to section-02 which defines the class)
- `type(day) is not int` used instead of `isinstance` to reject boolean values in delivery_days
- Entire `ProductImage.save()` wrapped in `transaction.atomic()` (spec only wrapped the sibling-clear path)
- Entire `ProductImage.delete()` wrapped in `transaction.atomic()` (spec mentioned but did not show wrapping)
- 5 additional `is_available_today` tests added beyond spec stubs

**Test count:** 20 passed, 0 failed