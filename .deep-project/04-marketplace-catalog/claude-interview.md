# Interview Transcript: 04-Marketplace-Catalog

## Q1: Inventory scope for split 04

**Question:** The spec says inventory management (atomic decrement) is "implemented in split 05 but designed here". For split 04, should we define DailyInventory model + is_available_today property only, leaving the increment-on-order logic to split 05 — or also implement the DailyInventory.qty_ordered increment inside this split's order placement stubs?

**Answer:** Model + property only (Recommended) — Define DailyInventory, is_available_today property, and read-only availability checks. Split 05 handles the write path.

---

## Q2: Image upload approach

**Question:** The spec stores product images as s3_key CharField (raw S3 key), not Django ImageField. For the upload view, how should we handle the S3 upload?

**Answer:** Use django-storages ImageField — use ImageField(storage=S3Boto3Storage()) and let django-storages handle the upload, storing path in s3_key.

---

## Q3: Timezone for time window comparisons

**Question:** The todays-drops endpoint checks if current time is within the product's available_from–available_to window. Should this time comparison use IST (Asia/Kolkata) timezone, and should it be enforced at the Django USE_TZ / TIME_ZONE settings level?

**Answer:** IST (Asia/Kolkata) — USE_TZ=True + TIME_ZONE='Asia/Kolkata'. All datetime comparisons use IST; Django converts to UTC for storage.

---

## Q4: Consolidated order sheet in split 04

**Question:** The consolidated order sheet (GET /api/v1/vendors/orders/consolidated/) needs order data from split 05 which doesn't exist yet. How should split 04 handle this endpoint?

**Answer:** Stub endpoint now — Register the URL and return an empty structure; split 05 fills in the real query.

---

## Q5: Rating ordering

**Question:** The spec's ordering param includes 'rating' but Product has no rating field — only Vendor.average_rating. Should ordering by 'rating' sort by vendor__average_rating, or should we skip 'rating' as an ordering option in this split?

**Answer:** vendor__average_rating — ordering=-rating sorts by the vendor's average_rating descending; annotate or use related field traversal.

---

## Q6: Flash sale activation permission

**Question:** For the flash sale activation endpoint, the spec says permission is "IsCommunityAdmin OR vendor can trigger for their own product". Should this be one endpoint with a combined permission check, or two separate endpoints?

**Answer:** Single endpoint with combined permission — One POST endpoint; permission class checks: is CommunityAdmin OR (IsVendorOwner of this product).

---

## Q7: is_available_today computation

**Question:** For ProductListSerializer, "is_available_today" needs to check DailyInventory.qty_ordered < max_daily_qty. How should this be computed in a catalog list response (potentially 20+ products)?

**Answer:** Annotate via subquery (Recommended) — Use a Subquery annotation in get_queryset() to compute availability in one DB round-trip; no N+1.

---

## Q8: Thumbnail task invocation

**Question:** For the thumbnail generation task: the spec lists two thumbnail sizes (400×400 for catalog grid, 200×200 for cart/order). Should one Celery task generate BOTH sizes in a single invocation, or should the task accept a 'size' parameter and be called twice?

**Answer:** Single task, generates both sizes — generate_product_thumbnail(image_id) creates 400×400 AND 200×200 in one task; both keys stored on ProductImage.

---

## Q9: Thumbnail storage fields

**Question:** The spec has a single thumbnail_s3_key on ProductImage, but the task generates both 400×400 and 200×200. Where should the 200×200 key be stored?

**Answer:** Add thumbnail_s3_key_small field — Add thumbnail_s3_key (400×400) and thumbnail_s3_key_small (200×200) as separate fields on ProductImage.

---

## Q10: Image format on upload

**Question:** The spec says images upload to S3 path ending in '.webp'. Should the upload view convert all images (JPG, PNG) to WebP format before storing, or preserve the original format?

**Answer:** Convert everything to WebP — View/Celery converts JPG/PNG to WebP on upload; consistent format, better compression.

---

## Q11: Primary image auto-management

**Question:** When a vendor uploads their first product image, should it automatically be set as is_primary=True? And when they delete the primary image, should the next image auto-promote?

**Answer:** Auto-set primary (Recommended) — First image auto-gets is_primary=True. If deleted, next image (by display_order) auto-promotes to primary.
