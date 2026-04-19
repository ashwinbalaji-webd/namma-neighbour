Now I have all the context needed. Let me generate the section content.

# Section 08: Image Upload and Management

## Overview

This section implements `ProductImageViewSet`, which handles image upload and deletion for vendor products. It is nested under `vendors/products/{product_id}/images/` and is the final section in the dependency chain (requires sections 01, 02, 03, and 07 to be complete).

**Dependencies (must be complete before starting this section):**
- Section 01 (Models): `Product`, `ProductImage`, `DailyInventory` models
- Section 02 (Storage/Utils): `convert_to_webp()`, `ProductMediaStorage`, `get_presigned_url()`
- Section 03 (Celery Tasks): `generate_product_thumbnail` task
- Section 07 (Vendor Management): `VendorProductViewSet`, `IsApprovedVendor` permission, vendor product URL routing

---

## Files to Create / Modify

- `namma_neighbor/apps/catalogue/views.py` — add `ProductImageViewSet` (the vendor product views from section 07 already exist here)
- `namma_neighbor/apps/catalogue/urls.py` — register the nested image routes
- `namma_neighbor/apps/catalogue/serializers.py` — add `ProductImageSerializer` if not already present
- `tests/catalogue/test_image_upload.py` — new test file

---

## Tests First

File: `tests/catalogue/test_image_upload.py`

Testing stack: `pytest` + `pytest-django`, `factory_boy` for fixtures, `moto` for S3 mocking, mock Celery for task dispatch.

```python
# tests/catalogue/test_image_upload.py

import io
import pytest
from PIL import Image as PILImage
from unittest.mock import patch, MagicMock

# --- Fixtures (factory_boy) ---

# ApprovedVendorFactory, CommunityFactory, ProductFactory, ProductImageFactory
# should be defined in tests/catalogue/factories.py (section 07 may define most of these)

# --- Upload Tests ---

class TestImageUpload:
    def test_upload_jpeg_saved_as_webp_and_thumbnail_dispatched(self, ...):
        """POST with a JPEG file: response 201, image saved to S3 as WebP, generate_product_thumbnail.delay called with image pk."""

    def test_upload_sixth_image_returns_400(self, ...):
        """Product already has 5 images. Uploading a 6th returns HTTP 400."""

    def test_upload_file_over_5mb_returns_400(self, ...):
        """POST with a file whose size exceeds 5MB returns HTTP 400 before Pillow is invoked."""

    def test_upload_non_image_file_returns_400(self, ...):
        """POST with a PDF file: Pillow raises, endpoint returns HTTP 400."""

    def test_first_image_activates_product(self, ...):
        """Product starts with is_active=False. After first image upload, product.is_active is True."""

    def test_first_image_is_primary(self, ...):
        """First image uploaded gets is_primary=True automatically."""

    def test_second_image_does_not_displace_primary(self, ...):
        """Uploading a second image does not change is_primary on the first image."""

    def test_non_owner_cannot_upload(self, ...):
        """A different approved vendor cannot upload to another vendor's product — returns 403."""


# --- Delete Tests ---

class TestImageDelete:
    def test_delete_primary_with_siblings_promotes_next_by_display_order(self, ...):
        """Deleting the primary image when siblings exist: next image by display_order becomes is_primary=True."""

    def test_delete_last_image_deactivates_product(self, ...):
        """Deleting the only remaining image sets product.is_active=False."""

    def test_non_owner_cannot_delete(self, ...):
        """A different vendor cannot delete an image belonging to another vendor's product — returns 403."""
```

### Key Test Setup Notes

- Use `@mock_aws` (moto) on any test that touches S3 so real AWS calls are not made.
- For upload tests that check task dispatch, `patch('apps.catalogue.tasks.generate_product_thumbnail.delay')` and assert it was called once with the new image's pk.
- For the 5MB size test, construct a `SimpleUploadedFile` or `BytesIO` object with a `.size` attribute set to `5 * 1024 * 1024 + 1`.
- For the non-image file test, use a `BytesIO` containing arbitrary bytes (e.g., `b'%PDF-1.4 ...'`) with `content_type='image/jpeg'` to simulate a spoofed Content-Type.

---

## Implementation Details

### ProductImageSerializer

File: `namma_neighbor/apps/catalogue/serializers.py`

```python
class ProductImageSerializer(serializers.ModelSerializer):
    """Serializer for ProductImage. image_url is a presigned S3 URL."""

    image_url = serializers.SerializerMethodField()

    def get_image_url(self, obj):
        """Return a 1-hour presigned URL for obj.image field's S3 key."""
        ...

    class Meta:
        model = ProductImage
        fields = ['id', 'image_url', 'is_primary', 'display_order']
        read_only_fields = fields
```

### ProductImageViewSet

File: `namma_neighbor/apps/catalogue/views.py`

```python
class ProductImageViewSet(viewsets.ViewSet):
    """
    Handles image upload (POST) and deletion (DELETE) for a vendor's product.
    Nested under: /api/v1/vendors/products/{product_id}/images/
    """

    permission_classes = [IsAuthenticated, IsApprovedVendor]

    def get_product(self, request, product_id):
        """
        Retrieve the product, enforce ownership: product.vendor must be
        request.user.vendor_profile_profile.
        Raises Http404 or PermissionDenied as appropriate.
        """
        ...

    def create(self, request, product_id=None):
        """
        POST /api/v1/vendors/products/{product_id}/images/

        Steps (in order):
        1. Check file size <= 5MB (reject before Pillow opens file).
        2. Check product image count < 5 (reject before S3 upload).
        3. Call convert_to_webp(file) — validates format, normalizes to WebP.
        4. Save ProductImage (django-storages handles S3 PUT via ImageField).
        5. If no primary image exists on product: set is_primary=True and save.
        6. If product.is_active is False: set is_active=True and save product.
        7. Dispatch generate_product_thumbnail.delay(image.pk).
        8. Return 201 with ProductImageSerializer data.
        """
        ...

    def destroy(self, request, product_id=None, pk=None):
        """
        DELETE /api/v1/vendors/products/{product_id}/images/{pk}/

        Steps (in order):
        1. Validate user owns the product via get_product().
        2. Fetch the image (404 if not found or not belonging to this product).
        3. Capture was_primary = image.is_primary.
        4. Count remaining images on product before deletion.
        5. Delete the DB record (S3 objects are orphaned — cleaned by S3 lifecycle policy).
        6. If was_primary and siblings remain: promote next image by display_order to is_primary=True.
        7. If no images remain: set product.is_active=False and save product.
        8. Return 204 No Content.
        """
        ...
```

### URL Registration

File: `namma_neighbor/apps/catalogue/urls.py`

The image upload routes are nested under the vendor product routes established in section 07. Register `ProductImageViewSet` as a nested router under the vendor products:

```python
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers as nested_routers  # drf-nested-routers

vendor_router = DefaultRouter()
vendor_router.register(r'vendors/products', VendorProductViewSet, basename='vendor-product')

product_images_router = nested_routers.NestedDefaultRouter(
    vendor_router, r'vendors/products', lookup='product'
)
product_images_router.register(r'images', ProductImageViewSet, basename='product-image')

urlpatterns = [
    # ... community catalog URLs from section 05 ...
    path('', include(vendor_router.urls)),
    path('', include(product_images_router.urls)),
]
```

This produces:
- `POST /api/v1/vendors/products/{product_pk}/images/` → `ProductImageViewSet.create`
- `DELETE /api/v1/vendors/products/{product_pk}/images/{pk}/` → `ProductImageViewSet.destroy`

---

## Detailed Behaviour Specifications

### Upload: Size Validation

The 5MB check happens before any Pillow call. Check `request.FILES['image'].size`. If `> 5 * 1024 * 1024`, return `Response({'detail': 'Image must be under 5MB.'}, status=400)`.

### Upload: Image Count Check

Query `ProductImage.objects.filter(product=product).count()`. If `>= 5`, return `Response({'detail': 'Maximum 5 images per product.'}, status=400)`. This must happen before the S3 upload to prevent partial state (file on S3 but record rejected in DB).

### Upload: WebP Conversion

Call `convert_to_webp(request.FILES['image'])` from `apps.catalogue.utils`. This function:
- Sets `Image.MAX_IMAGE_PIXELS = 50_000_000` to guard against decompression bomb attacks.
- Opens the file with `Image.open()` and calls `.verify()` / `.load()` to confirm it is a real image (not just a spoofed Content-Type).
- Converts RGBA images for WebP transparency preservation; converts all other modes to RGB.
- Returns a `ContentFile` named `{uuid}.webp`.

If `convert_to_webp` raises any Pillow exception (`PIL.UnidentifiedImageError`, `DecompressionBombError`, etc.), catch it in the view and return `Response({'detail': 'Invalid or unsupported image file.'}, status=400)`.

### Upload: Saving the ProductImage

```python
image_instance = ProductImage(product=product)
image_instance.image.save(converted_file.name, converted_file, save=True)
```

django-storages (`ProductMediaStorage`) handles the S3 PUT automatically via `ImageField.save()`. The S3 key follows `media/products/{product_id}/{uuid}.webp` as defined by the `upload_to` function from section 01.

### Upload: is_primary Auto-Set

After saving, check:
```python
if not ProductImage.objects.filter(product=product, is_primary=True).exclude(pk=image_instance.pk).exists():
    image_instance.is_primary = True
    image_instance.save(update_fields=['is_primary'])
```

This is consistent with the model-level behaviour defined in section 01: saving `is_primary=True` clears the flag on all sibling images in the same transaction.

### Upload: Product Activation

```python
if not product.is_active:
    product.is_active = True
    product.save(update_fields=['is_active'])
```

### Upload: Thumbnail Task Dispatch

```python
from apps.catalogue.tasks import generate_product_thumbnail
generate_product_thumbnail.delay(image_instance.pk)
```

This is an async Celery task (section 03) — dispatch with `.delay()` and do not await.

### Delete: Primary Image Promotion

After deleting the primary image, if other images remain:

```python
next_image = ProductImage.objects.filter(product=product).order_by('display_order').first()
if next_image:
    next_image.is_primary = True
    next_image.save(update_fields=['is_primary'])
```

### Delete: Product Deactivation on Last Image

After deletion:
```python
if not ProductImage.objects.filter(product=product).exists():
    product.is_active = False
    product.save(update_fields=['is_active'])
```

This is the inverse of the first-image activation: prevents imageless ghost listings from appearing in the catalog.

### Delete: S3 Orphan Cleanup

The DB record is deleted but the three S3 objects (original + `thumb_400_*.webp` + `thumb_200_*.webp`) are **not** deleted programmatically. An S3 lifecycle policy on the `media/products/` prefix should be configured separately to expire objects after a retention period. This is intentional — the delete endpoint does not call `boto3.delete_object`.

---

## Key Invariants to Enforce

| Invariant | Enforcement point |
|---|---|
| Max 5 images per product | View, before S3 upload |
| Max 5MB per upload | View, before Pillow |
| Only WebP images stored | `convert_to_webp()` called unconditionally |
| First image activates product | Upload view step 6 |
| Last image deletion deactivates product | Delete view step 7 |
| Primary promotion on primary deletion | Delete view step 6 |
| Vendor ownership | `get_product()` raises 403/404 for non-owner |

---

## Edge Cases

- **Concurrent uploads:** Two simultaneous uploads to a product with 4 images could both pass the count check and result in 6 images. For MVP, a `select_for_update()` on the product row in the count check is sufficient mitigation. A unique constraint on `(product, display_order)` would prevent duplicate display_order but not the count overflow itself.

- **Upload of already-WebP file:** `convert_to_webp()` is called unconditionally even for files already in WebP format. This re-encodes the file at quality=85. This is intentional — it ensures consistent quality settings regardless of origin.

- **Delete of a non-primary image that is the last image:** The last-image deactivation check (`not ProductImage.objects.filter(product=product).exists()`) runs regardless of `was_primary`. A product is deactivated whenever its image count drops to zero.

- **`thumbnail_s3_key` is null at upload time:** The thumbnail fields are null on the newly saved `ProductImage` — thumbnails are generated asynchronously by the Celery task dispatched at step 7. Serializers serving thumbnail URLs must handle null keys (e.g., return `None` for `thumbnail_url` if `thumbnail_s3_key` is null).