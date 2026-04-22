I now have all the context needed. Let me produce the section content.

# Section 05: S3 Document Upload

## Overview

This section implements the file validation and S3 storage layer for vendor KYB documents. It is a utility layer that the API views (section-07) and admin workflow views (section-08) depend on. It has no dependency on sections 02, 03, or 04 — only on the `Vendor` model from section-01.

The work splits into three parts:

1. **`validate_document_file()`** — a standalone function in `apps/vendors/services/storage.py` that applies three sequential validation layers (size, extension, magic bytes)
2. **`upload_vendor_document()`** — an upload helper in the same file that generates a unique S3 key and updates the vendor's `*_s3_key` field
3. **`generate_document_presigned_url()`** — a helper in `apps/core/storage.py` that uses `boto3` directly to sign a private S3 object URL

---

## Dependencies

- **section-01** must be complete: the `Vendor` model must exist with fields `govt_id_s3_key`, `bank_proof_s3_key`, `fssai_cert_s3_key`, `gst_cert_s3_key`
- `DocumentStorage` must already be configured in `apps/core/storage.py` — this section only adds the `generate_document_presigned_url` helper to that existing file
- The `filetype` Python package (or `python-magic`) must be added to project dependencies

---

## Tests First

Test file: `apps/vendors/tests/test_services.py` (the storage-related tests live in the same file as other service tests, or in a dedicated `test_storage.py`).

### 5.1 File Validation Tests

```python
# Test: validate_document_file raises ValidationError for file > 5MB
#   Create an InMemoryUploadedFile whose size attribute is 5 * 1024 * 1024 + 1 bytes
#   Assert ValidationError is raised with a descriptive message mentioning size

# Test: validate_document_file raises ValidationError for .exe extension
#   Create an InMemoryUploadedFile with name='malware.exe'
#   Assert ValidationError is raised

# Test: validate_document_file raises ValidationError for PDF extension but JPEG magic bytes
#   File named 'id.pdf', first bytes are FF D8 FF (JPEG magic)
#   Assert ValidationError is raised (magic bytes do not match declared extension)

# Test: validate_document_file raises ValidationError for JPEG extension but PDF magic bytes
#   File named 'cert.jpg', first bytes are 25 50 44 46 (%PDF magic)
#   Assert ValidationError is raised

# Test: validate_document_file accepts valid PDF
#   File named 'cert.pdf', first bytes are b'%PDF-1.4 ...' (at least 4 bytes)
#   Assert no exception raised, function returns normally

# Test: validate_document_file accepts valid JPEG
#   File named 'photo.jpg', first bytes are b'\xff\xd8\xff' followed by padding
#   Assert no exception raised

# Test: validate_document_file accepts valid PNG
#   File named 'photo.png', first bytes are b'\x89PNG\r\n\x1a\n' (PNG magic)
#   Assert no exception raised
```

Notes on test setup:
- Use `django.core.files.uploadedfile.InMemoryUploadedFile` or `SimpleUploadedFile` from `django.test`
- For magic byte tests, the file content must actually start with the correct (or incorrect) byte sequence — `content_type` argument is not used for detection; only the raw bytes matter
- The `filetype` library detects type from the first ~262 bytes, so any filler can follow the magic bytes

### 5.2 S3 Upload Tests

```python
# Test: S3 key follows pattern documents/vendors/{vendor_id}/{document_type}/{uuid}.{ext}
#   Mock the DocumentStorage._save / boto3 client so no real upload happens
#   Call upload_vendor_document(vendor, 'govt_id', file)
#   Assert vendor.govt_id_s3_key matches the pattern regex:
#     r'^documents/vendors/\d+/govt_id/[0-9a-f-]{36}\.(pdf|jpg|jpeg|png)$'

# Test: UUID in key is unique across two uploads of the same file
#   Call upload_vendor_document twice with identical input files
#   Assert the two resulting s3_keys are different

# Test: After upload, vendor.*_s3_key is updated in database
#   After calling upload_vendor_document(vendor, 'bank_proof', file)
#   Refresh vendor from DB
#   Assert vendor.bank_proof_s3_key is non-empty and equals the returned key
```

### 5.3 Presigned URL Tests

```python
# Test: generate_document_presigned_url returns a URL string
#   Mock boto3.client('s3').generate_presigned_url to return 'https://example.com/signed'
#   Assert return value is a string

# Test: generate_document_presigned_url uses signature_version=s3v4
#   Capture the kwargs passed to boto3.Session or boto3.client
#   Assert Config(signature_version='s3v4') was used

# Test: generate_document_presigned_url uses ExpiresIn=3600
#   Capture the generate_presigned_url call arguments
#   Assert Params includes ExpiresIn=3600 or the call uses ExpiresIn=3600
```

---

## Implementation

### New File: `apps/vendors/services/storage.py`

This file contains `validate_document_file()` and `upload_vendor_document()`.

#### `validate_document_file(file: UploadedFile) -> None`

Docstring: Validates an uploaded file against three sequential layers. Raises `django.core.exceptions.ValidationError` at the first failed layer.

Layer 1 — Size:
- `file.size` must be less than or equal to `5 * 1024 * 1024` (5 MB)
- Error message should mention the limit in MB

Layer 2 — Extension allowlist:
- Extract file extension from `file.name` using `os.path.splitext`
- Normalize to lowercase
- Allowed: `.pdf`, `.jpg`, `.jpeg`, `.png`
- Error message should list allowed types

Layer 3 — Magic bytes:
- Read the first 2048 bytes from the file (then seek back to position 0 with `file.seek(0)`)
- Use `filetype.guess(header_bytes)` to get the detected MIME type
- Accept: `application/pdf`, `image/jpeg`, `image/png`
- If detected MIME does not match the extension family, raise `ValidationError`
- Extension-to-expected-MIME map: `.pdf` → `application/pdf`, `.jpg/.jpeg` → `image/jpeg`, `.png` → `image/png`

Important: always seek the file back to `0` after reading the header bytes, so the caller can still read the full content for upload.

#### `upload_vendor_document(vendor, document_type: str, file: UploadedFile) -> str`

Docstring: Uploads a validated document file to S3, stores the resulting key on the vendor, and returns the S3 key.

Steps:
1. Determine the file extension from `file.name`
2. Build the S3 key: `f"documents/vendors/{vendor.pk}/{document_type}/{uuid.uuid4()}.{ext}"`
3. Upload via `DocumentStorage` (import from `apps.core.storage`) — call `storage.save(key, file)`
4. Map `document_type` to the corresponding model field:
   - `govt_id` → `govt_id_s3_key`
   - `bank_proof` → `bank_proof_s3_key`
   - `fssai_cert` → `fssai_cert_s3_key`
   - `gst_cert` → `gst_cert_s3_key`
5. Set the field and call `vendor.save(update_fields=[field_name])`
6. Return the key string

Valid `document_type` values: `govt_id`, `bank_proof`, `fssai_cert`, `gst_cert`. The serializer (section-06) validates this before calling this function, but a defensive check or a clear `ValueError` is acceptable here.

### Existing File: `apps/core/storage.py`

Add `generate_document_presigned_url` to the existing file — do not replace `DocumentStorage`.

#### `generate_document_presigned_url(s3_key: str) -> str`

Docstring: Generates an S3 presigned URL for private document review. Uses SigV4 (required for ap-south-1). TTL is 1 hour.

Implementation:
- Create a `boto3.Session()` and obtain an S3 client with `Config(signature_version='s3v4')` and `region_name='ap-south-1'`
- `AWS_STORAGE_BUCKET_NAME` should be read from `django.conf.settings`
- Call `client.generate_presigned_url('get_object', Params={'Bucket': bucket, 'Key': s3_key}, ExpiresIn=3600)`
- Return the resulting URL string

The function should not catch exceptions — errors propagate to the view layer (section-08) where they can be logged.

---

## File Paths Summary (Actual)

| Action | Path |
|--------|------|
| Already existed | `apps/vendors/services/__init__.py` |
| Created | `apps/vendors/services/storage.py` |
| Modified (added function + imports) | `apps/core/storage.py` |
| Created | `apps/vendors/tests/test_storage.py` |
| Modified (AWS_STORAGE_BUCKET_NAME as explicit setting) | `config/settings/base.py` |

## Deviations from Plan

- **S3 key prefix**: Key constructed as `vendors/{pk}/{document_type}/{uuid}.{ext}` (NOT `documents/vendors/...`) because `DocumentStorage.location = "documents"` prepends the prefix automatically. `storage.save()` returns the full `documents/vendors/...` key.
- **document_type validation**: Added early `ValueError` guard before S3 upload to prevent orphaned S3 objects.
- **file.seek(0)**: Added defensive seek at start of `upload_vendor_document`.
- **generate_document_presigned_url**: Added prefix guard — raises `ValueError` for keys not starting with `documents/vendors/`.
- **AWS_STORAGE_BUCKET_NAME**: Added as explicit Django setting in `base.py` (accessible via `settings.AWS_STORAGE_BUCKET_NAME`).
- **Test file**: Created as `test_storage.py` (separate from existing `test_services.py` which covers Razorpay).

## Final Test Count: 17 tests in `apps/vendors/tests/test_storage.py`

---

## Package Dependencies

Added to `pyproject.toml`:

```
filetype>=1.2  (boto3 was already present)
```

`filetype` is pure Python and requires no system libraries. If `python-magic` is preferred instead, it requires `libmagic` to be installed system-wide — `filetype` is simpler to deploy and is the recommended choice.

---

## Design Notes

- S3 keys use `uuid4` to guarantee uniqueness — re-uploading the same document never overwrites the previous copy. Old keys become orphaned in S3 (acceptable for MVP; lifecycle cleanup is a future concern).
- `DocumentStorage` handles AWS credentials — the upload helper does not need to configure boto3 itself.
- Presigned URL generation requires a `boto3` client configured separately with SigV4 because `django-storages`' S3 presigned URL generation may default to v2 in some configurations, which fails in `ap-south-1` (Mumbai). By building the client directly in `generate_document_presigned_url`, signature version is guaranteed.
- The 5 MB size limit is set below Razorpay's strictest limit (4 MB images, 2 MB PDFs) with some headroom. This means some valid files between 2–5 MB that Razorpay would reject for their API are accepted in the vault — but that edge case is handled at Razorpay submission time, not at upload time.
- `validate_document_file` is stateless and side-effect free — safe to call from serializer `validate_*` methods without any additional guards.