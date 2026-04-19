# TDD Plan: 04-Marketplace-Catalog

**Testing stack:** pytest + pytest-django, factory_boy for fixtures, moto for S3 mocking, freezegun for time, threading for concurrency tests.

---

## Section 1: Models

### Category
- Test: Category with `requires_fssai=True` saved and retrieved correctly
- Test: `slug` uniqueness constraint raises IntegrityError on duplicate

### Product
- Test: `is_active` defaults to `False` on create (spec override)
- Test: `delivery_days` rejects invalid values (7, -1, null entries) via `clean()`
- Test: `available_from < available_to` enforced in `clean()`
- Test: FSSAI gate in `clean()` — product with food category and unverified vendor raises ValidationError
- Test: GSTIN gate in `clean()` — product with GSTIN category and blank vendor.gstin raises ValidationError
- Test: Composite indexes exist on `(community, is_active)`, `(community, category, is_active)`, `(vendor, is_active)`

### ProductImage
- Test: First image uploaded to product → `is_primary=True` auto-set
- Test: Second image uploaded → first image remains primary
- Test: Saving a new image with `is_primary=True` → clears `is_primary` on all siblings
- Test: Deleting primary image → next image by `display_order` promoted to primary
- Test: Deleting last image → product `is_active` set to False

### DailyInventory
- Test: Unique constraint on `(product, date)` raises IntegrityError on duplicate
- Test: Default `qty_ordered=0`

---

## Section 2: Storage and Image Utilities

### convert_to_webp
- Test: JPEG input → returns ContentFile with `.webp` extension
- Test: PNG with transparency → converts correctly without error
- Test: Malformed/non-image file → raises appropriate Pillow exception (validates `Image.open()` check works)
- Test: File larger than `MAX_IMAGE_PIXELS` → raises `DecompressionBombError`

### get_presigned_url
- Test: Returns a URL string for a valid S3 key (moto mock)
- Test: Module-level boto3 client is reused (not re-created per call)

---

## Section 3: Celery Tasks

### generate_product_thumbnail
- Test: (with `@mock_aws`) Given a ProductImage, task downloads original, generates `thumbnail_s3_key` and `thumbnail_s3_key_small` at correct S3 keys
- Test: Both thumbnails are WebP and within correct pixel dimensions (400×400, 200×200 max)
- Test: `ProductImage.DoesNotExist` → task returns silently without error
- Test: Task retries on unexpected exception (mock S3 raise, verify retry count)

### expire_flash_sales
- Test: (with `freezegun`) Products past `flash_sale_ends_at` are set to `is_flash_sale=False` and all 4 flash sale fields nulled
- Test: Products with future `flash_sale_ends_at` are not touched
- Test: Products where `is_flash_sale=False` already are not touched

---

## Section 4: Filters and Permissions

### ProductFilterSet
- Test: `category` filter by slug returns only products in that category
- Test: `vendor` filter by id returns only that vendor's products
- Test: `is_flash_sale=true` returns only active flash sale products
- Test: `is_subscription=true` returns only subscription products

### IsApprovedVendor
- Test: APPROVED vendor passes permission
- Test: DRAFT/PENDING_REVIEW/SUSPENDED vendor returns 403

### IsCommunityAdminOrProductVendorOwner
- Test: Community admin for matching community → passes
- Test: Vendor owner of the product → passes
- Test: Neither admin nor owner → returns 403

---

## Section 5: Community Catalog ViewSet

- Test: `GET /communities/{slug}/products/` — only returns `is_active=True` products for that community
- Test: `GET .../products/` — products from other communities are excluded
- Test: `category` filter reduces results to correct category
- Test: `ordering=price` returns results ordered by price ascending
- Test: `ordering=-rating` returns results ordered by `vendor__average_rating` descending
- Test: `ordering=price` uses `LimitOffsetPagination` (not cursor)
- Test: Default browse (no ordering) uses `CursorPagination`
- Test: `is_available_today` annotation — product with no DailyInventory row for today → `is_available_today=True` (COALESCE handles NULL as 0)
- Test: `is_available_today` annotation — product with `qty_ordered >= max_daily_qty` → `is_available_today=False`
- Test: `GET .../todays-drops/` — only returns products where today's weekday in `delivery_days` AND `available_to > now`
- Test: `delivery_days__contains=[weekday]` query — products with `delivery_days=[0,1,2]` returned correctly for weekday 1, not for weekday 5
- Test: `GET .../flash-sales/` — only returns active flash sales with remaining qty and future expiry
- Test: Flash sale past `ends_at` excluded from `/flash-sales/` even if Celery task hasn't run yet
- Test: `GET .../subscriptions/` — only returns `is_subscription=True`
- Test: Non-resident of community → 403

---

## Section 6: Product Detail View

- Test: Returns all images with presigned URLs (moto mock)
- Test: `vendor_summary` dict has `display_name`, `average_rating`, `is_new_seller`, `completed_delivery_count`
- Test: Product from different community → 403
- Test: `is_available_today` computed correctly for open window today
- Test: `is_available_today=False` for product whose `available_to` has passed

---

## Section 7: Vendor Product Management

- Test: `POST /vendors/products/` with food category + unverified FSSAI → 403 with message
- Test: `POST /vendors/products/` with GSTIN category + blank gstin → 403 with message
- Test: `POST /vendors/products/` with valid vendor → product created with `is_active=False`
- Test: `community` auto-set from `vendor_profile.community`
- Test: `available_from >= available_to` → 400 validation error
- Test: `delivery_days` with value `[7]` → 400 validation error
- Test: `PATCH` cannot change `category`, `vendor`, or `community`
- Test: `DELETE` soft-deletes (sets `is_active=False`, DB record remains)
- Test: Vendor cannot see or edit another vendor's products

---

## Section 8: Image Upload and Management

- Test: Upload JPEG file → saved as WebP on S3, `thumbnail` task dispatched (mock Celery)
- Test: Upload 6th image → 400 error
- Test: Upload file > 5MB → 400 error
- Test: Upload non-image file (PDF) → Pillow raises, returns 400
- Test: First image upload → product `is_active` set to True
- Test: First image → `is_primary=True`
- Test: Delete primary image with siblings → next by `display_order` promoted
- Test: Delete last image → product `is_active=False`
- Test: Non-vendor-owner cannot upload to another vendor's product

---

## Section 9: Admin Feature and Flash Sale Endpoints

- Test: `POST .../feature/` by community admin → `is_featured=True`
- Test: `DELETE .../feature/` by community admin → `is_featured=False`
- Test: Feature endpoint by non-admin → 403
- Test: Feature product from different community → 403 or 404
- Test: `POST .../flash-sale/` with `qty=10, ends_at=future` → flash sale fields set
- Test: `POST .../flash-sale/` with `qty=0` → 400
- Test: `POST .../flash-sale/` with `ends_at` in the past → 400
- Test: Flash sale activated by vendor owner (not admin) → succeeds
- Test: Flash sale activated by non-owner non-admin → 403

---

## Section 11: Category Seed Data

- Test: `seed_categories` command creates all 11 categories
- Test: Command is idempotent — running twice does not create duplicates
- Test: `Seafood` has `requires_fssai=True`
- Test: `Electronics & Gadgets` has `requires_gstin=True`
