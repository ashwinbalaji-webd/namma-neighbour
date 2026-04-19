Now I have all the context needed. Let me generate the section content for `section-08-s3-storage`.

# Section 08: S3 Storage

## Overview

This section implements AWS S3 cloud storage for file uploads in NammaNeighbor. It adds the `STORAGES` configuration to `base.py` and creates two reusable storage subclasses — `DocumentStorage` and `MediaStorage` — in `apps/core/storage.py`. These classes are used by `FileField` and `ImageField` definitions across all subsequent splits (KYB documents in split 02/03, product images in split 04, etc.).

**Depends on:** section-01-project-skeleton (settings infrastructure, `apps/core/` app directory exists)

**Parallelizable with:** section-02-core-app, section-03-user-models, section-07-celery-infrastructure, section-09-docker-health

---

## Dependencies

- `django-storages[s3]` (provides `storages.backends.s3boto3.S3Boto3Storage`) — add to `requirements/base.txt`
- `boto3` — pulled in as a dependency of `django-storages[s3]`, no separate entry needed unless pinning
- `moto[s3]` — add to `requirements/development.txt` for optional integration tests

The `storages` package must be added to `THIRD_PARTY_APPS` in `base.py` as `'storages'`. This is assumed done in section-01; if section-01 omitted it, add it here.

---

## Files to Create or Modify

| Path | Action |
|------|--------|
| `apps/core/storage.py` | Create — DocumentStorage and MediaStorage classes |
| `config/settings/base.py` | Modify — add STORAGES dict and AWS_* settings |
| `.env.example` | Modify — document required S3 environment variables |
| `apps/core/tests/test_storage.py` | Create — storage unit tests |

---

## Tests First

File: `apps/core/tests/test_storage.py`

Testing stack: `pytest-django`, `moto` (optional for integration), `unittest.mock`.

### Unit Tests (no real AWS calls)

**Storage class prefix tests**

```python
def test_document_storage_location():
    """DocumentStorage.location == 'documents'"""

def test_media_storage_location():
    """MediaStorage.location == 'media'"""
```

These tests instantiate the storage classes and assert the `location` attribute. They do not require network access or AWS credentials.

**Settings validation tests**

```python
def test_default_storage_backend_is_s3(settings):
    """STORAGES['default']['BACKEND'] is S3Boto3Storage path"""

def test_static_files_storage_is_not_s3(settings):
    """STORAGES['staticfiles']['BACKEND'] is StaticFilesStorage (not S3)"""

def test_s3_default_acl_is_private(settings):
    """STORAGES['default']['OPTIONS']['default_acl'] == 'private'"""

def test_s3_file_overwrite_disabled(settings):
    """STORAGES['default']['OPTIONS']['file_overwrite'] == False"""

def test_s3_presigned_url_ttl(settings):
    """STORAGES['default']['OPTIONS']['querystring_expire'] == 3600"""

def test_s3_region_is_ap_south_1(settings):
    """STORAGES['default']['OPTIONS']['region_name'] == 'ap-south-1'"""
```

**TDD plan notes (from `claude-plan-tdd.md` Section 6):**

- Test: `DocumentStorage` generates keys prefixed with `documents/`
- Test: `MediaStorage` generates keys prefixed with `media/`
- Test: `AWS_DEFAULT_ACL` is `'private'` (verified via OPTIONS in STORAGES dict)
- Test: Uploading a file via `DocumentStorage` does not overwrite an existing file with the same name (different key generated) — verify `file_overwrite=False`

**Key name / non-overwrite test**

```python
def test_document_storage_no_overwrite():
    """
    With file_overwrite=False, uploading two files with the same name to
    DocumentStorage must produce two distinct S3 keys. Verify by checking
    that get_available_name() returns a modified path when the original path
    already exists (mock storage.exists() to return True).
    """
```

### Optional Integration Test (moto)

```python
@pytest.mark.integration
def test_document_storage_upload_and_presign(s3_bucket):
    """
    Using moto's mock S3:
    1. Upload a small file via DocumentStorage
    2. Assert the key starts with 'documents/'
    3. Assert a presigned URL is generated (non-empty string starting with 'https://')
    Requires @mock_s3 decorator and bucket pre-creation fixture.
    """
```

This test is optional — mark it `@pytest.mark.integration` and skip in CI unless `INTEGRATION_TESTS=1`. A `conftest.py` fixture creates the mock bucket:

```python
# apps/core/tests/conftest.py
@pytest.fixture
def s3_bucket():
    """Create a mock S3 bucket using moto for integration tests."""
```

---

## Implementation Details

### `apps/core/storage.py`

Create two storage subclasses. Both inherit from `S3Boto3Storage`. The only thing each class needs to override is `location` — the base class uses this attribute as the key prefix for all uploaded files.

```python
# apps/core/storage.py
from storages.backends.s3boto3 import S3Boto3Storage

class DocumentStorage(S3Boto3Storage):
    """
    S3 storage for sensitive documents: KYB/KYC files, FSSAI certificates,
    GST certificates. Keys are prefixed with 'documents/'.
    Used by: FileField(storage=DocumentStorage()) on vendor/community models.
    """
    location = "documents"

class MediaStorage(S3Boto3Storage):
    """
    S3 storage for public-facing media: product images, vendor logos,
    community photos. Keys are prefixed with 'media/'.
    Used by: ImageField(storage=MediaStorage()) on catalogue/vendor models.
    """
    location = "media"
```

Both classes inherit all behavior from `S3Boto3Storage`: the ACL, `file_overwrite`, `querystring_expire`, region, and credentials come from the `STORAGES` dict in `base.py`. No per-class overrides are needed beyond `location`.

Fields in other apps use these classes as:

```python
document = models.FileField(storage=DocumentStorage())
photo = models.ImageField(storage=MediaStorage())
```

### `config/settings/base.py` — STORAGES dict

Add the following to `base.py`. Use `django-environ` to read the bucket name from the environment. Do not hard-code the bucket name.

```python
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": {
            "bucket_name": env("AWS_STORAGE_BUCKET_NAME"),
            "region_name": "ap-south-1",
            "default_acl": "private",
            "file_overwrite": False,
            "querystring_expire": 3600,  # 1-hour presigned URLs
        },
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
```

**Why `STORAGES` and not `DEFAULT_FILE_STORAGE`:** Django 5.1 deprecates the string-based `DEFAULT_FILE_STORAGE` setting. The `STORAGES` dict is the current API and must be used. Do not use both — they conflict.

**Why static files use `StaticFilesStorage` and not S3:** Static files (`collectstatic`) are served via the web container or a CDN separately configured. Storing static files in S3 via `django-storages` requires separate bucket configuration and `STATIC_URL` adjustments. This is explicitly out of scope for the foundation split.

**AWS credentials:** Do not add `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` to `STORAGES` OPTIONS or to `base.py`. In production, credentials are provided via IAM role attached to the ECS task or EC2 instance profile — boto3 picks these up automatically from the environment. In development, set them in `.env`:

```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

And read them in `base.py` if present:

```python
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default=None)
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default=None)
```

Boto3 reads these from the Django settings namespace automatically when using `django-storages`.

### `.env.example` additions

Add these entries to `.env.example`:

```
# AWS S3 Storage
AWS_STORAGE_BUCKET_NAME=namma-neighbor-dev
AWS_ACCESS_KEY_ID=your-access-key-id
AWS_SECRET_ACCESS_KEY=your-secret-access-key
# Region is hardcoded to ap-south-1 in base.py — no env var needed
```

---

## Key Design Decisions

**`file_overwrite = False`:** When two files share the same name, `S3Boto3Storage` calls `get_available_name()` and appends a random suffix to avoid collision. This is the correct behavior for a marketplace where multiple vendors may upload files with the same filename (e.g., `fssai_certificate.pdf`).

**`default_acl = "private"`:** All uploaded files — both documents and media — are stored as private S3 objects. Access is granted only via presigned URLs, which expire after 1 hour (`querystring_expire = 3600`). This is the correct default for a marketplace: product images should be served through your own CDN/API layer rather than directly from public S3 URLs, and KYB documents must never be publicly accessible.

**`region_name = "ap-south-1"`:** Mumbai region. Hard-coded in settings because NammaNeighbor is India-only at MVP. If multi-region support is ever needed, promote this to an environment variable.

**Presigned URL generation:** When code calls `field.url` on a model instance (e.g., `vendor.fssai_certificate.url`), `S3Boto3Storage` automatically generates a presigned URL valid for `querystring_expire` seconds. No additional code is needed.

**`storages` in INSTALLED_APPS:** The `storages` package does not strictly require being in `INSTALLED_APPS` for `S3Boto3Storage` to function, but it is listed there as `'storages'` so that management commands and app checks work correctly.

---

## What This Section Does Not Cover

- Static file serving configuration (`STATIC_ROOT`, `STATIC_URL`, `collectstatic`) — handled in section-01-project-skeleton
- CloudFront CDN in front of S3 — infrastructure concern, not in foundation split
- S3 bucket creation, IAM policies, or bucket policies — infrastructure/ops concern
- Per-field storage selection on specific models — each model split (02, 03, 04, etc.) adds `storage=DocumentStorage()` or `storage=MediaStorage()` to its own fields