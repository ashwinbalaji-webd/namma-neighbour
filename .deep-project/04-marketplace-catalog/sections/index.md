<!-- PROJECT_CONFIG
runtime: python-uv
test_command: uv run pytest
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-models
section-02-storage-utils
section-03-celery-tasks
section-04-filters-permissions
section-05-catalog-viewset
section-06-product-detail
section-07-vendor-management
section-08-image-upload
section-09-admin-endpoints
section-10-django-admin
section-11-seed-categories
END_MANIFEST -->

# Implementation Sections Index: 04-Marketplace-Catalog

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable |
|---------|------------|--------|----------------|
| section-01-models | - | 03, 04, 05, 06, 07, 08, 09, 10, 11 | Yes |
| section-02-storage-utils | - | 03, 05, 06, 08 | Yes |
| section-03-celery-tasks | 01, 02 | 08 | Yes |
| section-04-filters-permissions | 01 | 05, 06, 07, 09 | Yes |
| section-05-catalog-viewset | 01, 02, 04 | - | Yes |
| section-06-product-detail | 01, 02, 04 | - | Yes |
| section-07-vendor-management | 01, 04 | 08 | Yes |
| section-08-image-upload | 01, 02, 03, 07 | - | No |
| section-09-admin-endpoints | 01, 04 | - | Yes |
| section-10-django-admin | 01 | - | Yes |
| section-11-seed-categories | 01 | - | Yes |

## Execution Order

1. **section-01-models**, **section-02-storage-utils** — no dependencies, run in parallel
2. **section-03-celery-tasks**, **section-04-filters-permissions**, **section-10-django-admin**, **section-11-seed-categories** — parallel after batch 1
3. **section-05-catalog-viewset**, **section-06-product-detail**, **section-07-vendor-management**, **section-09-admin-endpoints** — parallel after 01 + 04 complete
4. **section-08-image-upload** — last, requires 01 + 02 + 03 + 07

## Section Summaries

### section-01-models
`Category`, `Product`, `ProductImage`, `DailyInventory` models. Includes `is_active=False` default override, composite indexes, `is_available_today` logic, `clean()` validation for FSSAI/GSTIN/time-window gates, and `is_primary` auto-management on ProductImage. Migration files: `0001_initial.py` with correct cross-app dependencies.

### section-02-storage-utils
`ProductMediaStorage` (S3Boto3Storage subclass), `convert_to_webp()` utility (Pillow WebP conversion with decompression bomb guard), and `get_presigned_url()` with module-level cached boto3 client. These are standalone helpers with no model imports needed.

### section-03-celery-tasks
`generate_product_thumbnail` (downloads from S3, creates 400×400 and 200×200 WebP thumbnails, saves S3 keys back to ProductImage) and `expire_flash_sales` (scheduled every 15 min via Celery Beat, bulk-updates expired flash sale products). Includes `CELERY_BEAT_SCHEDULE` config with correct full task path.

### section-04-filters-permissions
`ProductFilterSet` (django-filter, handles category/vendor/is_flash_sale/is_subscription/is_featured), `IsApprovedVendor` permission (vendor role + APPROVED status), and `IsCommunityAdminOrProductVendorOwner` (dual-path: JWT for admin, DB FK for vendor owner).

### section-05-catalog-viewset
`CommunityProductViewSet` (ReadOnlyModelViewSet) with `get_queryset()` community scoping, `is_available_today` annotation via Coalesce subquery, dynamic pagination (CursorPagination vs LimitOffsetPagination), and three custom actions: `todays-drops`, `flash-sales`, `subscriptions`. URLs: `communities/{slug}/products/`.

### section-06-product-detail
`ProductDetailView` (standalone RetrieveAPIView), `ProductDetailSerializer` with presigned S3 URLs for all image sizes, `vendor_summary` dict, and `is_available_today` property-based computation. Validates product community matches JWT claim.

### section-07-vendor-management
`VendorProductViewSet` (ModelViewSet) with FSSAI/GSTIN compliance gates in `perform_create`, `available_from < available_to` validation, `delivery_days` integer validation, community auto-set from vendor profile, `is_active=False` on create, soft-delete on DELETE, and read-only fields after creation. `ProductListSerializer` and `ProductDetailSerializer` wired up.

### section-08-image-upload
`ProductImageViewSet` nested under `vendors/products/{product_id}/images/`. POST: 5MB limit, `convert_to_webp()`, 5-image max, `is_primary` auto-set, product activation on first image, thumbnail task dispatch. DELETE: primary image promotion, product deactivation on last image.

### section-09-admin-endpoints
Community admin feature/unfeature actions (`POST`/`DELETE` `.../feature/`), flash sale activation endpoint (`POST .../flash-sale/`) with `IsCommunityAdminOrProductVendorOwner`, and consolidated order sheet stub (`GET /api/v1/vendors/orders/consolidated/`) returning empty skeleton for split 05 to fill.

### section-10-django-admin
`CategoryAdmin` (CRUD with slug prepopulation, FSSAI/GSTIN flags) and `ProductAdmin` (community/vendor/category filters, ProductImage inline, bulk-deactivate action). Registered in `admin.py`.

### section-11-seed-categories
`seed_categories` management command + `0002_seed_categories.py` data migration. Creates all 11 categories (Seafood, Organic Produce, Baked Goods, Home-cooked Meals, Dairy Products, Flowers & Plants, Handcrafted Decor, Electronics & Gadgets, Clothing & Textiles, Services, Other) with correct FSSAI and GSTIN flags. Uses `get_or_create` on slug (idempotent).
