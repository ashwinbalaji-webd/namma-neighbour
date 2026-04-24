Now I have all the context needed. Let me generate the section content.

# Section 02: Storage and Image Utilities

## Overview

This section implements the standalone storage and image utility helpers for the catalogue app. These have no dependency on catalogue models and can be implemented and tested in parallel with section-01-models.

Two files are created:

- `/var/www/html/MadGirlfriend/namma-neighbour/namma_neighbor/apps/catalogue/storage.py` — `ProductMediaStorage`
- `/var/www/html/MadGirlfriend/namma-neighbour/namma_neighbor/apps/catalogue/utils.py` — `convert_to_webp`, `get_presigned_url`

## Dependencies

- No catalogue model imports are needed in either file.
- Depends on `01-Foundation` having configured `django-storages` with S3Boto3Storage, AWS credentials in settings, and Celery/Redis setup. Those are already in place.
- Python packages required: `django-storages[boto3]`, `boto3`, `Pillow`.

## Tests First

Test file: `/var/www/html/MadGirlfriend/namma-neighbour/namma_neighbor/apps/catalogue/tests/test_storage_utils.py`

Run with: `uv run pytest namma_neighbor/apps/catalogue/tests/test_storage_utils.py`

### Test stubs

```python
import io
import pytest
from PIL import Image, DecompressionBombError
from django.core.files.base import ContentFile

# --- convert_to_webp tests ---

def make_jpeg_file(width=100, height=100):
    """Helper: returns a BytesIO containing a valid JPEG."""
    ...

def make_png_rgba_file(width=100, height=100):
    """Helper: returns a BytesIO containing a valid RGBA PNG."""
    ...

def test_convert_to_webp_jpeg_input_returns_webp_contentfile():
    """JPEG input -> ContentFile with .webp extension and valid WebP content."""
    ...

def test_convert_to_webp_png_rgba_no_error():
    """PNG with alpha channel converts without raising; result is readable WebP."""
    ...

def test_convert_to_webp_non_image_raises():
    """Passing a file whose bytes are not a valid image raises a Pillow exception."""
    ...

def test_convert_to_webp_decompression_bomb_raises():
    """
    Image that exceeds MAX_IMAGE_PIXELS (50_000_000) raises DecompressionBombError.
    Use a synthetic large image or temporarily lower the pixel cap to trigger the error.
    """
    ...

# --- get_presigned_url tests ---

@pytest.mark.django_db
def test_get_presigned_url_returns_url_string(moto_s3):
    """
    With moto mocking AWS, get_presigned_url('some/key.webp') returns a non-empty
    URL string. Fixture `moto_s3` should create the mock bucket used in settings.
    """
    ...

def test_get_presigned_url_reuses_boto3_client():
    """
    Calling get_presigned_url twice does not create two distinct boto3 clients.
    Import the module and assert the module-level client object is the same
    object identity on both calls (id() check or mock patch).
    """
    ...
```

The `moto_s3` fixture should be defined in `conftest.py` at the catalogue tests level. It initialises a mocked S3 environment (using `moto`'s `mock_aws` context manager) and creates the bucket name that matches `settings.AWS_STORAGE_BUCKET_NAME`.

## Implementation

### `storage.py`

```python
# namma_neighbor/apps/catalogue/storage.py

from storages.backends.s3boto3 import S3Boto3Storage
import uuid


def product_image_upload_path(instance, filename):
    """
    Returns S3 key: media/products/{product_id}/{uuid}.webp
    Always .webp because convert_to_webp() normalises format before save.
    `instance` is a ProductImage; instance.product_id may be None on first save
    if the product hasn't been saved yet — callers must ensure product is saved first.
    """
    ...


class ProductMediaStorage(S3Boto3Storage):
    """
    S3 storage backend for all product media.
    - location='' so upload_to controls the full S3 key without prefix doubling.
    - default_acl='private' — all product images are private; access via presigned URLs.
    - file_overwrite=False — never silently replace an existing file.
    """
    location = ''
    default_acl = 'private'
    file_overwrite = False
```

Key points:
- `location = ''` (empty string, not a directory prefix). This is critical. If `location` were set to `'media/products/'`, the `upload_to` path and the `location` prefix would combine, doubling the path.
- The `product_image_upload_path` function uses `uuid.uuid4()` to generate the filename so filenames are never predictable or guessable.

### `utils.py`

```python
# namma_neighbor/apps/catalogue/utils.py

import io
import uuid
import boto3
from botocore.config import Config
from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image

# Set decompression bomb limit before any image operations.
# Prevents Pillow from opening maliciously crafted huge images.
# 50_000_000 px ≈ 7071 x 7071.
Image.MAX_IMAGE_PIXELS = 50_000_000

# Module-level boto3 client — created once at import time, reused for every call.
# signature_version='s3v4' is mandatory for all current AWS regions.
_s3_client = boto3.client(
    's3',
    region_name=settings.AWS_S3_REGION_NAME,
    config=Config(signature_version='s3v4'),
)


def convert_to_webp(image_file) -> ContentFile:
    """
    Converts any uploaded image file to WebP format at quality=85.

    Steps:
    1. Open with Image.open() — this validates the file is a real image, not a
       spoofed Content-Type. Raises PIL.UnidentifiedImageError if not a valid image.
    2. Call img.load() immediately to force decode while the file handle is open.
       Image.open() is lazy — if the file closes before pixels are decoded, Pillow
       may raise on later operations.
    3. Convert color mode: if mode is 'RGBA' or 'P' (palette with transparency),
       convert to 'RGBA' to preserve transparency in WebP; otherwise convert to 'RGB'.
    4. Save to BytesIO buffer as WebP at quality=85.
    5. Return ContentFile(buffer.getvalue(), name='{uuid}.webp').

    Called unconditionally in the upload view — existing WebP files are re-encoded
    for consistent quality settings (intentional).
    """
    ...


def get_presigned_url(s3_key: str, expiry_seconds: int = 3600) -> str:
    """
    Generates a pre-signed S3 GET URL for a private object.

    Uses the module-level _s3_client (not a new client per call) to avoid
    20+ client instantiations per catalog page load.

    Args:
        s3_key: Full S3 object key, e.g. 'media/products/42/abc.webp'.
        expiry_seconds: URL validity window. Default 3600 (1 hour).

    Returns:
        Pre-signed URL string.
    """
    ...
```

Implementation notes for `convert_to_webp`:

- Call `image_file.seek(0)` before `Image.open()` if the file might have been partially read upstream.
- The `img.load()` call is mandatory. `Image.open()` is lazy — the actual pixel data is not decoded until either `load()` is called explicitly or a pixel operation triggers it. Since the input `image_file` may be an in-memory object whose seek position advances, calling `load()` immediately while the handle is fresh guarantees decoding succeeds.
- Color mode handling determines WebP transparency support. WebP supports transparency; JPEG does not. Do not force all images to `RGB` — that silently drops alpha channels on PNGs, potentially creating visual artefacts when the frontend renders them on non-white backgrounds.
- `quality=85` is a project-wide constant for all product images. Do not expose it as a parameter — consistency across all uploads is the goal.

Implementation notes for `get_presigned_url`:

- The `_s3_client` is defined at module scope so that `import apps.catalogue.utils` initialises it once for the lifetime of the process. Do not construct a client inside the function body.
- Pass `Bucket=settings.AWS_STORAGE_BUCKET_NAME` and `Key=s3_key` to `generate_presigned_url('get_object', ...)`.
- `ExpiresIn` is the boto3 parameter name (not `expiry` or `expiry_seconds`).

## File Summary

| File | What to create |
|------|----------------|
| `namma_neighbor/apps/catalogue/storage.py` | `product_image_upload_path` function and `ProductMediaStorage` class |
| `namma_neighbor/apps/catalogue/utils.py` | Module-level `_s3_client`, `Image.MAX_IMAGE_PIXELS` cap, `convert_to_webp()`, `get_presigned_url()` |
| `namma_neighbor/apps/catalogue/tests/test_storage_utils.py` | All test stubs listed above |
| `namma_neighbor/apps/catalogue/tests/conftest.py` | `moto_s3` fixture (creates mock S3 bucket matching `settings.AWS_STORAGE_BUCKET_NAME`) |

## Acceptance Criteria

- `convert_to_webp` accepts JPEG and PNG inputs and returns a `ContentFile` with a `.webp` name.
- `convert_to_webp` raises `PIL.UnidentifiedImageError` (or a subclass) when given a non-image file — the upload view catches this and returns HTTP 400.
- `convert_to_webp` raises `PIL.Image.DecompressionBombError` for images exceeding `MAX_IMAGE_PIXELS=50_000_000` — the upload view catches this and returns HTTP 400.
- `get_presigned_url` returns a non-empty URL string for a valid key.
- `get_presigned_url` uses the same `_s3_client` object on every call (no per-call instantiation).
- All tests pass: `uv run pytest namma_neighbor/apps/catalogue/tests/test_storage_utils.py`

---

## Implementation Notes (Actual)

**Files created:**
- `namma_neighbor/apps/catalogue/storage.py` — `ProductMediaStorage` and `product_image_upload_path`
- `namma_neighbor/apps/catalogue/utils.py` — `_s3_client`, `convert_to_webp`, `get_presigned_url`
- `namma_neighbor/apps/catalogue/tests/conftest.py` — `moto_s3` fixture + `use_filesystem_storage_for_product_images` autouse fixture (patches `ProductImage._meta.get_field('image').storage` to FileSystemStorage in all catalogue tests)
- `namma_neighbor/apps/catalogue/tests/test_storage_utils.py` — 6 tests
- Updated `models.py` to import from `storage.py` and use `storage=ProductMediaStorage()`
- Updated `migrations/0001_initial.py` to reference `apps.catalogue.storage`

**Deviations from plan:**
- P-mode color check uses `img.info.get('transparency') is not None` guard (plan said "palette with transparency" but implementation generalized it)
- `conftest.py` has autouse `use_filesystem_storage_for_product_images` (not in plan) — needed for all catalogue model tests
- `_s3_client` uses `getattr(settings, 'AWS_S3_REGION_NAME', 'ap-south-1')` as fallback (plan referenced settings attribute directly)
- `@pytest.mark.django_db` removed from presigned URL test (no DB needed)
- Decompression bomb test uses `mock.patch.object` instead of direct global mutation

**Test count:** 26 total (20 model tests + 6 storage tests), all passing