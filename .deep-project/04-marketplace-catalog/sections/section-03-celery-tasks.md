# section-03-celery-tasks

## Overview

This section implements the two Celery tasks in `namma_neighbor/apps/catalogue/tasks.py`:

1. `generate_product_thumbnail` — downloads an uploaded product image from S3 and generates two WebP thumbnail sizes, saving the S3 keys back to the `ProductImage` record.
2. `expire_flash_sales` — a scheduled task that bulk-expires flash sales whose `flash_sale_ends_at` has passed.

This section also documents the required `CELERY_BEAT_SCHEDULE` entry.

---

## Dependencies

- **section-01-models** must be complete before this section. The tasks import `ProductImage` and `Product` from `apps.catalogue.models`. Specifically, `ProductImage` must have the fields: `image` (ImageField), `thumbnail_s3_key` (CharField), `thumbnail_s3_key_small` (CharField), and FKs to `Product`.
- **section-02-storage-utils** must be complete before this section. The boto3 client setup pattern from `utils.py` (module-level cached client with `signature_version='s3v4'`) should be used as the model for the client in `tasks.py`.

---

## Files Created / Modified

- **Created:** `namma_neighbor/apps/catalogue/tasks.py`
- **Created:** `namma_neighbor/apps/catalogue/tests/test_tasks.py`
- **Modified:** `namma_neighbor/config/settings/base.py` — added `expire-flash-sales` to `CELERY_BEAT_SCHEDULE`

## Implementation Notes

- Used lazy `_get_s3_client()` with a module-level `_s3_client = None` sentinel (deferred boto3 initialization)
- Beat schedule entry uses `options: {queue: 'default'}` for consistency with other entries (added in code review)
- All tests patch `_get_s3_client` directly (not the module-level `_s3_client`) to ensure mock_aws context is respected

---

## Tests First

File: `tests/catalogue/test_tasks.py`

Testing stack: pytest + pytest-django, moto for S3 mocking (`@mock_aws`), freezegun for time control, factory_boy for fixtures.

### Test stubs for `generate_product_thumbnail`

```python
@mock_aws
def test_generate_thumbnail_creates_both_sizes(product_image_factory):
    """Given a ProductImage with an original uploaded to mocked S3,
    calling generate_product_thumbnail(image.pk) should:
    - populate image.thumbnail_s3_key with path matching thumb_400_*.webp
    - populate image.thumbnail_s3_key_small with path matching thumb_200_*.webp
    - both keys exist in the mocked S3 bucket
    """
    ...

@mock_aws
def test_generate_thumbnail_sizes_within_bounds(product_image_factory):
    """Both generated thumbnails must be WebP and dimensions must be
    at most 400x400 and 200x200 respectively (Image.thumbnail never upscales).
    Open the S3 object from the mocked bucket with Pillow to verify.
    """
    ...

def test_generate_thumbnail_missing_image_returns_silently():
    """Calling generate_product_thumbnail with a non-existent pk
    should return None without raising any exception.
    ProductImage.DoesNotExist must be caught and swallowed.
    """
    ...

@mock_aws
def test_generate_thumbnail_retries_on_exception(product_image_factory, mocker):
    """When an unexpected exception is raised (e.g., S3 get_object fails),
    the task should call self.retry(exc=exc). Mock the boto3 client's get_object
    to raise ClientError and verify task.retry is invoked.
    """
    ...
```

### Test stubs for `expire_flash_sales`

```python
@freeze_time("2024-06-01 12:00:00")
def test_expire_flash_sales_expires_past_sales(product_factory):
    """Products where is_flash_sale=True AND flash_sale_ends_at is before now
    should be bulk-updated:
    - is_flash_sale → False
    - flash_sale_qty → None
    - flash_sale_qty_remaining → None
    - flash_sale_ends_at → None
    The task should return the count of expired records.
    """
    ...

@freeze_time("2024-06-01 12:00:00")
def test_expire_flash_sales_leaves_future_sales_untouched(product_factory):
    """Products with flash_sale_ends_at in the future must not be modified."""
    ...

@freeze_time("2024-06-01 12:00:00")
def test_expire_flash_sales_skips_already_inactive(product_factory):
    """Products where is_flash_sale=False already are not touched,
    even if flash_sale_ends_at is in the past."""
    ...
```

---

## Implementation Details

### Task: `generate_product_thumbnail`

**Location:** `apps/catalogue/tasks.py`

**Celery binding:** Bound task (uses `self` for retry) — decorate with `@app.task(bind=True, max_retries=3, default_retry_delay=10, queue='default')`.

**Algorithm:**

1. Fetch `ProductImage` by `image_id`. If `ProductImage.DoesNotExist`, return silently.
2. Create a boto3 S3 client (can use the module-level cached client from `utils.py` or create one locally — consistent approach preferred).
3. Derive the S3 key from `image.image.name` (the storage backend stores the relative path in this field).
4. Call `s3_client.get_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=image_s3_key)` and read the body as bytes.
5. Open with `Image.open(io.BytesIO(image_bytes))` and **call `img.load()`** immediately — Pillow's `open()` is lazy and the BytesIO object may not persist; calling `load()` forces full decode while the data is in memory.
6. Convert color mode: if mode is `'P'` (palette) or `'RGBA'`, convert to `'RGBA'`; otherwise convert to `'RGB'`. This avoids WebP encoding errors for paletted PNGs.
7. Generate 400×400 thumbnail:
   - Copy the image (`img.copy()`), call `.thumbnail((400, 400), Image.LANCZOS)` on the copy.
   - Save to `BytesIO` with `format='WEBP', quality=85`.
   - Construct S3 key: `media/products/{product.pk}/thumb_400_{uuid4_hex}.webp`.
   - Upload via `s3_client.put_object(Bucket=..., Key=thumb_400_key, Body=buffer.getvalue(), ContentType='image/webp')`.
8. Repeat for 200×200 using `thumb_200_{uuid}.webp` key pattern.
9. Save both keys back to `image.thumbnail_s3_key` and `image.thumbnail_s3_key_small` and call `image.save(update_fields=['thumbnail_s3_key', 'thumbnail_s3_key_small'])`.
10. On any exception other than `DoesNotExist`: `raise self.retry(exc=exc)`.

**Pillow note:** `Image.thumbnail()` (not `Image.resize()`) must be used — `thumbnail()` constrains to the given bounds without upscaling. `Image.LANCZOS` is the resampling filter for quality.

**Color mode note:** RGBA and P modes must be handled before resizing. A `'P'` palette image converted to `'RGBA'` (or `'RGB'` after transparency handling) prevents `OSError: cannot write mode P as WEBP`.

### Task: `expire_flash_sales`

**Location:** `apps/catalogue/tasks.py`

**Celery binding:** Unbound task (no `self` needed, no retries) — decorate with `@app.task(queue='default')`.

**Algorithm:**

1. Get current UTC time: `now = timezone.now()`.
2. Bulk-update in one query:
   ```python
   count = Product.objects.filter(
       is_flash_sale=True,
       flash_sale_ends_at__lt=now
   ).update(
       is_flash_sale=False,
       flash_sale_qty=None,
       flash_sale_qty_remaining=None,
       flash_sale_ends_at=None,
   )
   ```
   Note: `flash_sale_qty` is also nulled per the spec — all four flash sale fields are cleared together.
3. Return `count` so callers and logs can observe how many records were updated.

No retry logic needed — if the DB is unavailable, the next Beat invocation (15 min later) will pick up the same records.

### Celery Beat Schedule

Add to the Django settings (or the Celery app configuration where `CELERY_BEAT_SCHEDULE` is defined — this is already set up in split 01's Foundation app):

```python
CELERY_BEAT_SCHEDULE = {
    ...
    'expire-flash-sales': {
        'task': 'apps.catalogue.tasks.expire_flash_sales',
        'schedule': 900.0,  # every 15 minutes
    },
}
```

**Critical:** The task name must use the full module path `apps.catalogue.tasks.expire_flash_sales`, not `catalogue.tasks.expire_flash_sales`. Celery autodiscovers tasks using the full app module path because the apps directory is under `apps/`. Verify the registered name at startup with `celery inspect registered`.

Only one Celery Beat instance should run — multiple Beat processes will fire the task multiple times per interval.

---

## Stub Signatures

```python
# apps/catalogue/tasks.py

from celery import shared_task  # or from namma_neighbor.celery import app
import io
import uuid
import boto3
from django.conf import settings
from django.utils import timezone
from PIL import Image

# Use a module-level cached boto3 client (same pattern as utils.py)
_s3_client = None

def _get_s3_client():
    """Return module-level cached boto3 S3 client."""
    ...


@app.task(bind=True, max_retries=3, default_retry_delay=10, queue='default')
def generate_product_thumbnail(self, image_id: int) -> None:
    """Download the original product image from S3 and generate WebP thumbnails.

    Creates two thumbnails:
    - 400x400 (catalog grid) -> saved to ProductImage.thumbnail_s3_key
    - 200x200 (cart/order summary) -> saved to ProductImage.thumbnail_s3_key_small

    Silently returns if ProductImage does not exist (deleted before task ran).
    Retries up to 3 times on unexpected exceptions.
    """
    ...


@app.task(queue='default')
def expire_flash_sales() -> int:
    """Bulk-expire flash sales whose flash_sale_ends_at has passed.

    Sets is_flash_sale=False and nulls all four flash sale fields
    (flash_sale_qty, flash_sale_qty_remaining, flash_sale_ends_at, flash_sale_qty)
    on all matching products.

    Returns the count of expired records.
    Scheduled every 15 minutes via CELERY_BEAT_SCHEDULE.
    """
    ...
```

---

## Key Invariants and Edge Cases

**`img.load()` must be called immediately after `Image.open()`:** Pillow defers image decode until pixels are accessed. When opening from a `BytesIO` that holds boto3 stream data, the BytesIO is closed after `get_object` body is consumed. Calling `img.load()` while the BytesIO is still in scope ensures the full image is decoded into memory before any reference to the buffer goes away.

**Use `Image.thumbnail()` not `Image.resize()`:** `thumbnail()` respects aspect ratio and never upscales a smaller image. `resize()` would stretch images to exactly 400×400, distorting non-square products. Catalog images must preserve aspect ratio within the bounding box.

**Color mode conversion before thumbnail:** Convert palette-mode (`'P'`) images to `'RGB'` or `'RGBA'` before calling `thumbnail()`. WebP encoder does not accept palette-mode input and will raise `OSError`.

**`DoesNotExist` is not retried:** Only `ProductImage.DoesNotExist` is silently swallowed. All other exceptions (boto3 `ClientError`, Pillow errors, DB errors) propagate to `self.retry()`. This ensures transient failures are retried while permanent misses (image deleted) are not.

**Thumbnail S3 keys are independent UUIDs:** Each thumbnail gets its own `uuid4().hex` in its key, separate from the original image's UUID. This prevents key collisions if the same image is re-processed.

**Eventual consistency for flash sale expiry:** The `expire_flash_sales` task runs every 15 minutes. The browse endpoint for `/flash-sales/` already filters `flash_sale_ends_at__gt=now` in real time, so expired flash sales vanish from the API immediately even before the task runs. The task clears the model flags for data hygiene only — it is not the gatekeeper for sale visibility.