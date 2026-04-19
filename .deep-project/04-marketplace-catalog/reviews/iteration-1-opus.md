# Opus Review

**Model:** claude-opus-4
**Generated:** 2026-04-02T00:00:00+05:30

---

## Review of Implementation Plan: 04-Marketplace-Catalog

**File reviewed:** `claude-plan.md`

---

### 1. Model Design Issues

**1.1. Spec divergence: `ProductImage` field discrepancy**

The spec defines `ProductImage` with an `s3_key` CharField field. The plan switches to an `ImageField` managed by django-storages. This is a reasonable improvement, but it creates an inconsistency: the plan simultaneously refers to `thumbnail_s3_key` and `thumbnail_s3_key_small` as raw CharFields, while the primary image is an ImageField. This hybrid approach means the Celery task must use two different mechanisms — django-storages for reading the original image (via `instance.image.open()`) but raw boto3 `put_object` for writing thumbnails. The plan should explicitly acknowledge this dual approach and document why thumbnails cannot also use ImageField (or why they should).

**1.2. Missing `price` and `unit` fields in plan's Product model description**

Section 1 describes Product fields in detail but never explicitly lists `price` or `unit`. These are critical fields that should be enumerated in the model description.

**1.3. Missing `flash_sale_price` or discount field**

The flash sale design stores quantity limits but has no mechanism for a discounted price. A flash sale without a price reduction is just a limited-quantity listing. If the regular `price` field is simply used as-is, the plan should state this explicitly. If a discounted price is expected, a `flash_sale_price` field is missing.

**1.4. `delivery_days` JSONField lacks validation**

The plan describes `delivery_days` as "a list of weekday integers, 0=Monday" but specifies no validation. Invalid payloads like `[7, 8, -1]`, `"monday"`, or `null` entries would corrupt data silently.

**1.5. No `description` field mentioned**

The spec includes `description = models.TextField()` on Product but the plan's model description does not mention it.

**1.6. `DailyInventory` missing auto-creation strategy**

The `is_available_today` check queries `DailyInventory` for today's date. But if no row exists for (product, today), the subquery returns NULL. The plan does not specify using `COALESCE(qty_ordered, 0)` to treat missing rows as 0 ordered. Getting this wrong means all products without orders today would incorrectly appear unavailable (or always available, depending on the logic).

**1.7. GSTIN validation not enforced**

Category has `requires_gstin` flag but no corresponding gate at product creation is specified. The plan enforces FSSAI thoroughly but is silent on GSTIN.

---

### 2. API Design Issues

**2.1. `todays-drops` time-based query on JSONField is fragile**

Querying a JSONField for containment requires specific syntax (`delivery_days__contains=[weekday]` for a JSON array). The plan does not specify the exact ORM lookup, which is a common source of bugs.

**2.2. Cursor pagination incompatible with `ordering_fields`**

Section 5 specifies `CursorPagination` on `-created_at` AND exposes `ordering_fields` including `price`, `-price`, and `rating`. DRF's `CursorPagination` requires a fixed, immutable ordering field. If the client requests `ordering=price`, cursor pagination breaks or produces incorrect results. The plan must resolve this conflict.

**2.3. Community slug → JWT community_id double-validation ambiguity**

Section 5 resolves slug to community then compares with JWT `community_id`. The plan should specify: what happens if the slug does not exist (404 vs 403), and whether the slug→id translation is cached.

**2.4. Consolidated order sheet stub is in the wrong app**

`GET /api/v1/vendors/orders/consolidated/` is registered in catalogue but belongs semantically in the orders app (split 05). Registering in catalogue means split 05 must either move it (URL change) or work around a cross-app dependency.

**2.5. No search endpoint**

No full-text search capability is specified. Adding it later requires GIN indexes on `name`/`description`.

---

### 3. Security Concerns

**3.1. FSSAI check in serializer is bypassable via Django Admin**

The FSSAI gate is in the serializer's `validate()`. If a product is created via Django Admin, the serializer is not invoked. Model-level `clean()` or `save()` validation is needed.

**3.2. No rate limiting on image upload**

The image upload endpoint (5MB files, S3 upload + Celery task) has no rate limiting. `django-ratelimit` is already in the project per foundation spec.

**3.3. Image upload file type validation is insufficient**

Extension and Content-Type are spoofable. The plan should specify using `Image.open()` to verify actual format AND setting `Image.MAX_IMAGE_PIXELS` to prevent Pillow decompression bombs.

---

### 4. Performance Concerns

**4.1. Presigned URL generation in list serializer is expensive**

`ProductListSerializer` exposes `primary_image_thumbnail_url`. If this generates a presigned URL per product, that is 20 boto3 API calls per page. The plan should clarify whether list views use presigned URLs or a more efficient mechanism (e.g., public-read thumbnails or cached URLs).

**4.2. `is_available_today` subquery — incomplete specification**

The subquery must handle: (a) no DailyInventory row → COALESCE to 0, (b) compare `qty_ordered` against `max_daily_qty` (on Product, not DailyInventory), (c) delivery_days check, (d) time window check. As written, underspecified.

**4.3. WebP re-encoding degradation**

Re-encoding a WebP at quality=85 that was originally quality=90 degrades the image. Should only re-encode non-WebP files.

---

### 5. Missing Considerations

**5.1. No tests section**

Zero mention of tests. At minimum: model unit tests (availability logic), API integration tests (permissions, community scoping), Celery task tests (thumbnail, expiry), concurrent access tests.

**5.2. No migration dependency chain specified**

Migrations must declare `dependencies = [('communities', '0001_initial'), ('vendors', '0001_initial')]`. Getting this wrong causes migration failures.

**5.3. No error response format specification**

The plan mentions 400/403 errors but never specifies the response body format. Foundation spec uses a custom exception handler — this plan should document expected error shapes.

**5.4. Orphaned S3 objects on image delete**

Three S3 objects are orphaned per deleted image (original + 2 thumbnails). The plan should specify an S3 lifecycle policy to manage this.

**5.5. `flash_sale_qty` reset on expiry**

`expire_flash_sales` nulls `flash_sale_qty_remaining` and `flash_sale_ends_at` but not `flash_sale_qty`. Stale data remains.

---

### 6. Ambiguities

**6.1. `is_active` default: plan says False, spec says True**

A deliberate spec override should be called out explicitly.

**6.2. `available_from < available_to` prevents overnight windows**

If overnight delivery windows (e.g., 22:00–06:00) are ever needed, this validation would need changing.

**6.3. `vendor` vs `vendor_profile` related name**

Split 03 spec defines `Vendor.user = OneToOneField(User, related_name='vendor_profile')`, making the reverse accessor `request.user.vendor_profile`, not `request.user.vendor`. The plan should use the correct related name throughout.

**6.4. Flash sale — no mechanism to cancel or modify active sale**

POST activates, Celery expires, but no endpoint to cancel or extend. Should be documented as intentional.

---

### 7. Architectural Concerns

**7.1. Flash sale fields inline on Product causes write contention**

Every flash sale stock decrement writes to the Product row. Every vendor product edit also writes to it. Separating flash sale state into a separate model would isolate contention. Known spec constraint, but should be flagged.

**7.2. Celery Beat task name may need full module path**

`'catalogue.tasks.expire_flash_sales'` may need to be `'apps.catalogue.tasks.expire_flash_sales'` depending on Celery autodiscover config. Silent failure risk if wrong.

---

### Priority Summary

| Priority | Issue |
|---|---|
| P0 | Cursor pagination + client ordering conflict |
| P0 | DailyInventory missing-row handling (COALESCE) |
| P0 | `vendor_profile` vs `vendor` related name |
| P1 | Presigned URL cost in list views |
| P1 | GSTIN enforcement gap |
| P1 | Celery Beat task name path |
| P1 | FSSAI check in serializer — bypassable via admin |
| P1 | Image decompression bomb protection |
| P1 | No test plan |
| P2 | delivery_days ORM lookup syntax |
| P2 | flash_sale_qty reset on expiry |
| P2 | S3 lifecycle policy for orphaned objects |
| P2 | Migration dependency chain |
| P3 | No search endpoint |
| P3 | No rate limiting on image upload |
