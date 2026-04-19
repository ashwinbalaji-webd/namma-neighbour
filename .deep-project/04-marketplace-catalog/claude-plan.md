# Implementation Plan: 04-Marketplace-Catalog

## What We Are Building

This split builds the `catalogue` Django app — the core product browsing and listing management system for NammaNeighbor, a hyperlocal marketplace where residents of gated communities can browse and order from pre-approved local vendors.

The catalogue app is responsible for: product categories, product listings (with availability windows and delivery schedules), product images (with async thumbnail generation), flash sales (time-limited, quantity-limited discounts), daily inventory guards, and the discovery APIs that residents use to browse products scoped to their community.

This split does **not** handle order placement, payment, or product reviews — those are splits 05 and 07. It does design the inventory model (`DailyInventory`) and the `is_available_today` availability check that split 05 will write against.

---

## Project Context

NammaNeighbor runs on Django 5.x + DRF 3.15, PostgreSQL 16, Celery 5 + Redis 7, and AWS S3 via django-storages. All models inherit a `TimestampedModel` base that provides `created_at` and `updated_at`. Auth is phone-OTP → JWT with roles and `community_id` embedded in the token. Permission classes read from JWT claims rather than hitting the database.

Three apps are already built:
- **01-Foundation:** User model, PhoneOTP, auth endpoints, Celery config, S3 storage setup, base permission classes
- **02-Community-Onboarding:** `Community`, `Building`, `ResidentProfile` models
- **03-Seller-Onboarding:** `Vendor` model (OneToOneField to User with `related_name='vendor_profile'`, direct FK to Community) with FSSAI verification status, vendor approval workflow, `is_new_seller` property

The catalog app FKs into `communities.Community` and `vendors.Vendor`. It lives at `namma_neighbor/apps/catalogue/`.

**Important related name:** The Vendor–User relationship uses `related_name='vendor_profile'`, so the reverse accessor throughout this split is `request.user.vendor_profile_profile` (not `request.user.vendor_profile`).

---

## Directory Structure

```
apps/catalogue/
  __init__.py
  apps.py
  models.py          # Category, Product, ProductImage, DailyInventory
  serializers.py     # ProductListSerializer, ProductDetailSerializer
  views.py           # CommunityProductViewSet, VendorProductViewSet, ProductDetailView
  filters.py         # ProductFilterSet (django-filter)
  permissions.py     # IsApprovedVendor, IsCommunityAdminOrProductVendorOwner
  tasks.py           # generate_product_thumbnail, expire_flash_sales
  storage.py         # ProductMediaStorage
  utils.py           # get_presigned_url, convert_to_webp
  urls.py
  admin.py
  management/
    commands/
      seed_categories.py
  migrations/
    0001_initial.py
    0002_seed_categories.py  # data migration
```

---

## Section 1: Models

### Category

`Category` is a simple lookup table with a `slug` for URL routing. It carries two compliance flags: `requires_fssai` (true for all food categories) and `requires_gstin` (true for high-value goods like electronics). These flags are checked at product creation time to gate whether a vendor is allowed to list in that category.

Fields: `name` (CharField), `slug` (SlugField unique), `icon_url` (URLField, optional), `requires_fssai` (BooleanField), `requires_gstin` (BooleanField).

### Product

`Product` is the central model. It scopes every product to both a `vendor` and a `community` — a vendor can only sell within their own community. Key design points:

**Availability windows:** `available_from` and `available_to` are `TimeField` values (e.g., 08:00 and 12:00). Together with `delivery_days` (a JSONField storing a list of weekday integers, 0=Monday) they define when orders can be placed. These fields are compared against IST local time (the project uses `TIME_ZONE = 'Asia/Kolkata'`).

**Daily quantity cap:** `max_daily_qty` limits how many units can be ordered per day. The actual counter lives in `DailyInventory`; this field is the ceiling.

**Flash sale fields:** `is_flash_sale`, `flash_sale_qty`, `flash_sale_qty_remaining`, `flash_sale_ends_at` are all inline on `Product` rather than a separate model (matching the spec). Flash sale stock decrements atomically in split 05 using a conditional `F().update()` with a `flash_sale_qty_remaining__gt=0` guard.

**Feature and subscription flags:** `is_featured` is set by community admins and causes the product to sort to the top of catalog results. `is_subscription` marks recurring-delivery products (daily milk, weekly sabji box).

Three composite database indexes: `(community, is_active)`, `(community, category, is_active)`, `(vendor, is_active)`. These directly serve the most common catalog queries.

**Spec override — `is_active` default:** The original spec defines `is_active = models.BooleanField(default=True)`. This split overrides it to `default=False`. New products are created inactive until at least one image is uploaded, at which point the upload endpoint sets `is_active=True`. This prevents ghost listings in the catalog.

### ProductImage

Images are stored via a custom `ProductMediaStorage` (a subclass of `S3Boto3Storage` pointing at `media/products/`). All uploaded images — regardless of original format (JPEG, PNG, WEBP) — are converted to WebP before upload for consistent format and better compression. The upload path function ensures the S3 key follows the `media/products/{product_id}/{uuid}.webp` convention.

The model stores the main image as a Django `ImageField` (path tracked by django-storages), and two thumbnail S3 keys as raw CharFields: `thumbnail_s3_key` for 400×400 (catalog grid) and `thumbnail_s3_key_small` for 200×200 (cart/order summary). Thumbnails are generated asynchronously by a Celery task after upload.

`is_primary` management is automatic: the first image uploaded to a product becomes primary; if the primary image is deleted, the next image by `display_order` is promoted. At the model level, saving with `is_primary=True` clears that flag on all sibling images in the same transaction.

Maximum 5 images per product — enforced in the upload view before saving.

### DailyInventory

`DailyInventory` tracks how many units of a product have been ordered on a given date. It has a unique constraint on `(product, date)`.

**Scope in this split:** We define the model and the `is_available_today` availability check. The `qty_ordered` increment is implemented in split 05 when order placement is built.

The `is_available_today` check combines: delivery day matches today (IST weekday), order window is still open (current IST time between `available_from` and `available_to`), daily quota not exhausted (`qty_ordered < max_daily_qty`), and for flash sales: `flash_sale_qty_remaining > 0` and `flash_sale_ends_at > now`.

**Missing-row handling:** If no `DailyInventory` row exists for `(product, today)`, treat `qty_ordered` as 0 (not as unavailable). Use `Coalesce(subquery_value, 0)` in the annotation so NULL resolves to 0 ordered.

---

## Section 2: Storage and Image Utilities

### ProductMediaStorage

A subclass of `S3Boto3Storage` in `storage.py` with `location=''` (empty, so `upload_to` controls the full path), `default_acl='private'`, `file_overwrite=False`. All product image files go through this storage class. The `upload_to` function returns `media/products/{product_id}/{uuid}.webp` — the full path from S3 root, so `location` must be empty to avoid doubling the prefix.

### WebP Conversion

`utils.convert_to_webp(image_file) -> ContentFile` in `utils.py`. Before any image processing, the module sets `Image.MAX_IMAGE_PIXELS = 50_000_000` (≈7000×7000) to prevent Pillow decompression bomb attacks. The function opens the file with `Image.open()` to verify it is a valid image (not a spoofed Content-Type), converts to the appropriate color mode (RGBA for WebP transparency, RGB otherwise), saves to a `BytesIO` buffer at quality=85, and returns a `ContentFile` named `{uuid}.webp`. Called unconditionally in the upload view — even existing WebP files are re-encoded for consistent quality settings (intentional trade-off confirmed in design review).

### Presigned URL Generation

`utils.get_presigned_url(s3_key, expiry_seconds=3600) -> str`. Uses a module-level cached boto3 client (created once at import time, not per call) with `signature_version='s3v4'` (required for all AWS regions). This avoids 20+ client instantiations per catalog page load. Used in `ProductDetailSerializer` for per-image presigned URLs. **List views** (`ProductListSerializer`) serve `primary_image_thumbnail_url` via presigned URL as well — these are cached at the module level to minimize latency.

---

## Section 3: Celery Tasks

### generate_product_thumbnail(image_id)

Queue: `default`. Bound task with `max_retries=3`, `default_retry_delay=10`.

The task downloads the original image from S3 using boto3's `get_object` (keying off the `image` field's S3 key), opens it with Pillow, generates two thumbnail sizes:
- 400×400 (catalog grid) → stored in `thumbnail_s3_key`  
- 200×200 (cart/order summary) → stored in `thumbnail_s3_key_small`

Both thumbnails are saved as WebP (quality=85) via a `BytesIO` buffer and uploaded via boto3 `put_object`. S3 keys follow the pattern `media/products/{product_id}/thumb_400_{uuid}.webp` and `thumb_200_{uuid}.webp`.

Pillow note: `img.load()` must be called while the file handle is still open — `Image.open()` is lazy and the file closes after the boto3 stream ends. Color mode conversion (RGBA/P → RGB) should happen before resizing. `Image.thumbnail()` is used (not `resize()`) because it never upscales.

On `ProductImage.DoesNotExist`: return silently (image deleted before task ran). On other exceptions: `raise self.retry(exc=exc)`.

### expire_flash_sales()

Queue: `default`. Unbound, no retries needed.

Finds all products where `is_flash_sale=True` AND `flash_sale_ends_at < now()`, and bulk-updates them: sets `is_flash_sale=False`, nulls all four flash sale fields (`flash_sale_qty`, `flash_sale_qty_remaining`, `flash_sale_ends_at`). Returns count of expired records for logging.

Scheduled every 15 minutes via `CELERY_BEAT_SCHEDULE`. **Task name:** use `apps.catalogue.tasks.expire_flash_sales` (not `catalogue.tasks.expire_flash_sales`) — Celery autodiscovers tasks using the full app module path since apps live under `apps/`:
```
'expire-flash-sales': {'task': 'apps.catalogue.tasks.expire_flash_sales', 'schedule': 900.0}
```

Only one Celery Beat instance should run this — multiple Beat processes will double-fire the task. Verify the registered task name at startup via `celery inspect registered`.

---

## Section 4: Filters and Permissions

### ProductFilterSet

Uses `django-filter`'s `FilterSet`. Community scoping and `is_active=True` are applied in `get_queryset()` (not in the FilterSet) because they are security-critical and must not be client-overridable. The FilterSet handles: `category` (filter by slug), `vendor` (filter by id), `is_flash_sale` (BooleanFilter), `is_subscription` (BooleanFilter), `is_featured` (BooleanFilter).

### IsApprovedVendor

Checks two conditions: `IsVendorOfCommunity` (vendor role in JWT + community_id match) AND `request.user.vendor_profile_profile.status == VendorStatus.APPROVED`. Returns 403 if vendor exists but is not approved.

### IsCommunityAdminOrProductVendorOwner

Used for the flash sale activation endpoint. Object-level permission: passes if the user is a community admin for the product's community OR if `request.user.vendor_profile_profile` is the product's vendor. Checked via JWT claims for the admin path and via database FK for the vendor path.

---

## Section 5: Community Catalog ViewSet

`CommunityProductViewSet` extends `ReadOnlyModelViewSet`. It is nested under the community URL (router registers it at `communities/{slug}/products/`).

**get_queryset():** Resolves the community from the `slug` URL param, validates the requesting user is a resident of that community (community_id from JWT must match), filters `is_active=True`, and applies `select_related('vendor', 'category')` and `prefetch_related('images')` for efficiency. The `is_available_today` annotation: annotate `today_qty_ordered` using `Coalesce(Subquery(DailyInventory.objects.filter(product=OuterRef('pk'), date=today).values('qty_ordered')[:1]), 0)`. The `Coalesce(..., 0)` is critical — products with no DailyInventory row for today must be treated as 0 ordered (fully available), not NULL (which would wrongly compute as unavailable). The full `is_available_today` boolean is then computed in the serializer's `to_representation()` using the annotated `today_qty_ordered` value plus `delivery_days`, window check, and flash sale check in Python. This avoids N+1 queries while keeping the SQL manageable.

**`rating` ordering:** When the client passes `ordering=rating` or `ordering=-rating`, this maps to `vendor__average_rating`. Explicitly listed in `ordering_fields` (not `__all__`).

**Pagination:** Dynamic pagination class — a property on the ViewSet checks `request.query_params.get('ordering')`. If no `ordering` param is present: use `CursorPagination` on `-created_at` (stable, prevents duplicates on live feeds). If `ordering` param is present (price, -price, rating): switch to `LimitOffsetPagination` for that request, since cursor pagination requires a fixed ordering field and breaks under custom sort. Default page size 20.

**Custom actions** on the same ViewSet (all use `detail=False`):

- `todays-drops`: Filters by `delivery_days__contains=[today_weekday]` (PostgreSQL JSONB `@>` operator — value must be a list `[int]`, not a bare int) AND `available_to__gt=timezone.localtime().time()`. Orders flash sale products to the top of results using `Case/When` or `order_by` with a boolean annotation.

- `flash-sales`: Filters `is_flash_sale=True`, `flash_sale_qty_remaining__gt=0`, `flash_sale_ends_at__gt=timezone.now()`.

- `subscriptions`: Filters `is_subscription=True`.

All three custom actions return `ProductListSerializer`.

---

## Section 6: Product Detail View

`ProductDetailView` is a standalone `RetrieveAPIView` (not nested under community). It resolves the product by `product_id`, validates that `product.community_id` matches the requesting user's JWT `community_id`, and returns `ProductDetailSerializer`.

The serializer populates presigned S3 URLs (1h TTL) for each image's original, 400×400 thumbnail, and 200×200 thumbnail. It includes a `vendor_summary` dict with `display_name`, `average_rating`, `is_new_seller`, `completed_delivery_count`. It computes `is_available_today` using the property (not the subquery annotation, since this is a single-object view).

---

## Section 7: Vendor Product Management

`VendorProductViewSet` handles CRUD for a vendor's own products. It extends `ModelViewSet`.

**get_queryset():** Scoped to `request.user.vendor_profile_profile` — vendors only see their own products.

**Perform create:** Sets `community` from `request.user.vendor_profile_profile.community`. Validates two compliance gates:
1. If `category.requires_fssai=True` → `vendor.fssai_status == VERIFIED`; else 403 "FSSAI verification required to list in this category"
2. If `category.requires_gstin=True` → `vendor.gstin` must not be blank; else 403 "GSTIN required to list in this category"

Both gates are checked in the serializer's `validate()` AND in `Product.clean()` (model-level) so Django Admin cannot bypass them. Validates `available_from < available_to`. Validates `delivery_days` contains only valid weekday integers 0–6 (no nulls, no out-of-range values). Creates product with `is_active=False` (will auto-activate on first image).

**PATCH:** Only a subset of fields are mutable after creation. `category`, `vendor`, `community` are read-only after creation. Update is handled by `partial=True` serializer.

**DELETE:** Soft-delete — sets `is_active=False`. Does not destroy the DB record (orders may reference it).

---

## Section 8: Image Upload and Management

`ProductImageViewSet` handles image upload and deletion. Nested under `vendors/products/{product_id}/images/`.

**Upload (POST):**
1. Validate size (max 5MB) first (reject before Pillow opens). Then call `convert_to_webp()` which uses `Image.open()` to verify the file is a genuine image (not just a spoofed Content-Type). `Image.MAX_IMAGE_PIXELS` cap prevents decompression bombs.
2. Check product has < 5 existing images (else 400)
3. Call `convert_to_webp(file)` to normalize format
4. Save `ProductImage` with the converted file (django-storages handles S3 PUT automatically via `ImageField`)
5. Auto-set `is_primary=True` if no primary exists
6. If product is `is_active=False` (first image scenario): set `is_active=True` and save
7. Dispatch `generate_product_thumbnail.delay(image.pk)`

**Delete (DELETE):**
1. Validate user owns the product
2. If `image.is_primary=True`: after delete, promote next image by `display_order` to primary
3. If deleting the last image: set `product.is_active=False` (inverse of first-image activation — prevents imageless listings)
4. Delete DB record. Three S3 objects are orphaned per deletion (original + 2 thumbnails). An S3 lifecycle policy on the `media/products/` prefix should be configured to expire orphaned objects after a retention period.

---

## Section 9: Admin Feature and Flash Sale Endpoints

### Feature/Unfeature (Community Admin)

Two simple actions on a separate view (or community-nested ViewSet action):
- `POST feature/`: sets `is_featured=True`, saves
- `DELETE feature/`: sets `is_featured=False`, saves

Both validate that the product belongs to the community in the URL. Permission: `IsCommunityAdmin`.

### Flash Sale Activation

`POST /api/v1/communities/{slug}/products/{product_id}/flash-sale/`

Permission: `IsCommunityAdminOrProductVendorOwner`. 

Validates: `qty >= 1`, `ends_at > timezone.now()`, product `is_active=True`. Sets flash sale fields on the product. No deactivation endpoint — the Celery task handles expiry, or qty reaching 0 prevents further orders.

### Consolidated Order Sheet Stub

`GET /api/v1/vendors/orders/consolidated/?date=YYYY-MM-DD`

Permission: `IsVendorOfCommunity`. Returns `{"date": "...", "total_orders": 0, "by_building": {}}`. This URL is registered now so split 05 can fill in the real query without changing the URL structure.

---

## Section 10: Django Admin

`CategoryAdmin`: CRUD, `prepopulated_fields={'slug': ('name',)}`, displays `requires_fssai` and `requires_gstin`.

`ProductAdmin`: list displays community, vendor, category, `is_active`, `is_featured`, price. List filter on community and category. Inline for `ProductImage`. Custom action to bulk-deactivate selected products.

---

## Section 11: Category Seed Data

A management command `seed_categories` (also expressed as a data migration `0002_seed_categories.py`) creates 11 categories with correct `requires_fssai` and `requires_gstin` flags. The migration uses `RunPython` so it runs automatically on deploy. The command is idempotent — uses `get_or_create` on `slug`.

**Migration dependencies:** `0001_initial.py` must declare:
```
dependencies = [
    ('communities', '<latest_communities_migration>'),
    ('vendors', '<latest_vendors_migration>'),
]
```
This ensures `Community` and `Vendor` tables exist before `Product`'s FKs are created.

---

## Key Invariants and Edge Cases

**FSSAI gate at product creation:** If `category.requires_fssai=True` and `vendor.fssai_status != VERIFIED`, the create endpoint returns HTTP 403 with the message "FSSAI verification required to list in this category". This is checked in the serializer's `validate()` method with access to `self.context['request'].user.vendor`.

**No products without images:** New products are inactive (`is_active=False`) until the first image upload. The image upload endpoint activates the product. This invariant prevents ghost listings in the catalog.

**Max 5 images enforced in view:** The count check happens before the S3 upload attempt to avoid partial state (uploaded to S3, rejected in DB).

**WebP conversion always happens:** The `convert_to_webp` utility is called unconditionally in the upload view, even for files already in WebP format (re-encoding ensures consistent quality settings).

**Cursor pagination for catalog:** `CursorPagination` on `-created_at` prevents duplicate products appearing when new listings are added mid-browse (a problem with offset pagination on live feeds).

**IST timezone for window checks:** `timezone.localtime()` converts UTC `now()` to IST before comparing with `available_from`/`available_to` TimeFields. This means a product with `available_to=12:00` closes at noon IST regardless of server UTC time.

**Subquery for is_available_today in list:** The DailyInventory check is done as a single annotated subquery rather than per-object property access. This avoids N+1 queries when rendering a 20-product page.

**Flash sale expiry is eventual (±15 min):** The `expire_flash_sales` task runs every 15 minutes. The browse endpoint (`/flash-sales/`) applies a real-time filter `flash_sale_ends_at__gt=now` so expired flash sales vanish from the API immediately. The Celery task just clears the flag on the model for data hygiene.

**Combined flash sale permission:** The same `POST .../flash-sale/` endpoint accepts both community admins and vendor owners. The permission class checks community admin role first (JWT-only, no DB), then vendor ownership (FK comparison). Returning 403 with a clear error message if neither condition is met.

**Soft-delete for products:** PATCH/DELETE on vendor products sets `is_active=False` rather than destroying the record. This preserves referential integrity for orders in split 05.
