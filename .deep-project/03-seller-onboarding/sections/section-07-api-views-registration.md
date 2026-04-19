I now have enough context to write the complete section. Let me produce the content:

# section-07-api-views-registration

## Overview

This section implements the four vendor-side API views in `apps/vendors/views.py`. These are the views a vendor uses to register their profile, upload KYB documents, submit their application to a community, and check their application status.

This section depends on:
- **section-01**: `Vendor`, `VendorCommunity`, `FSSAIStatus`, `VendorCommunityStatus` models
- **section-02**: `IsVendorOwner` permission class, `ExternalAPIError` exception hierarchy
- **section-05**: `validate_document_file()`, `upload_vendor_document()`, `generate_document_presigned_url()` from `apps/vendors/services/storage.py`
- **section-06**: `VendorRegistrationSerializer`, `DocumentUploadSerializer`, `VendorStatusSerializer` from `apps/vendors/serializers.py`

The Celery task `verify_fssai` (section-09) is only referenced via `.delay()` — its `.delay` is mocked in tests and the task module must exist (even as a stub) for the import not to fail.

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `apps/vendors/views.py` | Create — add all four views |
| `apps/vendors/tests/test_views.py` | Create — write tests first |

---

## Tests First

File: `/var/www/html/MadGirlfriend/namma-neighbour/apps/vendors/tests/test_views.py`

All tests use `pytest.mark.django_db`, `APIClient`, and factories from `apps/vendors/tests/factories.py`. Mock `verify_fssai.delay` with `unittest.mock.patch`. Never call `verify_fssai` directly from view tests — only assert that `.delay` was or was not called.

### Setup / Fixtures (conftest or top of file)

```python
# Fixtures needed:
# - api_client: returns an unauthenticated APIClient
# - auth_client(user): returns APIClient.force_authenticate(user=user)
# - vendor_user: a User with a Vendor already attached (VendorFactory)
# - community: a Community created via CommunityFactory
```

### 6.1 POST /api/v1/vendors/register/

```python
# Test: Creates Vendor and VendorCommunity on success; returns vendor_id and vendor_community_id
#   - POST with valid display_name, bio, logistics_tier, community_slug, category_hint
#   - Assert 201; response contains vendor_id, vendor_community_id, status='pending_review', required_documents

# Test: Sets is_food_seller=True when category_hint='food'
#   - Assert Vendor.is_food_seller=True after registration with category_hint='food'

# Test: required_documents includes 'fssai_cert' when is_food_seller=True
#   - Assert 'fssai_cert' in response['required_documents']

# Test: required_documents does NOT include 'fssai_cert' when is_food_seller=False
#   - Use category_hint='other' or omit it
#   - Assert 'fssai_cert' not in response['required_documents']

# Test: Returns 409 when VendorCommunity already exists for (vendor, community)
#   - Register once, then POST again with same community_slug
#   - Assert 409 Conflict

# Test: Returns 404 when community_slug does not exist
#   - POST with community_slug='does-not-exist'
#   - Assert 404

# Test: Returns 401 when not authenticated
#   - POST without authentication
#   - Assert 401

# Test: Vendor is NOT created twice if user already has a Vendor — reuses existing
#   - Create a Vendor for the user first
#   - POST register; assert Vendor.objects.filter(user=...).count() == 1

# Test: Vendor and VendorCommunity are both created (or neither) — transaction atomicity
#   - Patch VendorCommunity.objects.create to raise IntegrityError
#   - Assert Vendor.objects.count() has not changed from before the request
```

### 6.2 POST /api/v1/vendors/{vendor_id}/documents/

```python
# Test: Returns 403 when authenticated user does not own vendor
#   - Authenticate as a different user
#   - POST to /{vendor_id}/documents/
#   - Assert 403

# Test: Rejects file > 5MB with 400
#   - Upload a SimpleUploadedFile with content of 6MB
#   - Assert 400

# Test: Rejects invalid file type (e.g. .exe) with 400
#   - Upload file with .exe extension
#   - Assert 400

# Test: Rejects file with PDF extension but JPEG magic bytes with 400

# Test: Accepts valid PDF, updates govt_id_s3_key
#   - Mock upload_vendor_document to return a fake s3 key
#   - POST document_type='govt_id' with a valid PDF file
#   - Assert 200; Vendor.govt_id_s3_key updated

# Test: Accepts valid JPEG, updates bank_proof_s3_key
#   - POST document_type='bank_proof' with a valid JPEG file
#   - Assert Vendor.bank_proof_s3_key updated

# Test: Uploading fssai_cert with valid fssai_number → verify_fssai.delay called once
#   - Set vendor.fssai_number = '12345678901234'
#   - Upload document_type='fssai_cert' with valid PDF
#   - Assert verify_fssai.delay.call_count == 1

# Test: Uploading fssai_cert without fssai_number → verify_fssai.delay NOT called; response warns
#   - Ensure vendor.fssai_number = ''
#   - Upload document_type='fssai_cert'
#   - Assert verify_fssai.delay not called
#   - Assert response body contains a warning key (e.g. missing_fssai_number=True)

# Test: Returns 400 for invalid document_type value
#   - POST with document_type='invalid_type'
#   - Assert 400
```

### 6.3 POST /api/v1/vendors/{vendor_id}/submit/

```python
# Test: Returns 400 when govt_id_s3_key is empty
#   - Vendor has no govt_id uploaded
#   - Assert 400 with descriptive error

# Test: Returns 400 when bank_proof_s3_key is empty

# Test: Returns 400 when is_food_seller=True and fssai_cert_s3_key is empty

# Test: Returns 400 when fssai_status='failed'
#   - All required docs uploaded, but fssai_status=failed
#   - Assert 400

# Test: Transitions VendorCommunity.status → 'pending_review' on success
#   - All docs uploaded, fssai_status != failed (or not food seller)
#   - Assert VendorCommunity.status == VendorCommunityStatus.PENDING_REVIEW

# Test: Returns 404 when VendorCommunity not found for given community_slug

# Test: Returns 403 when user does not own vendor
```

### 6.4 GET /api/v1/vendors/{vendor_id}/status/

```python
# Test: Returns fssai_status and fssai_expiry_date

# Test: missing_documents is empty when all required docs are uploaded

# Test: missing_documents includes 'fssai_cert' when food seller missing cert
#   - is_food_seller=True, fssai_cert_s3_key=''
#   - Assert 'fssai_cert' in response['missing_documents']

# Test: community_statuses reflects all VendorCommunity records for the vendor
#   - Create two VendorCommunity records for different communities
#   - Assert response['community_statuses'] has two entries

# Test: Returns 403 when user does not own vendor
```

---

## Implementation

File: `/var/www/html/MadGirlfriend/namma-neighbour/apps/vendors/views.py`

Use Django REST Framework class-based views (`APIView` or `GenericAPIView`). All views require `IsAuthenticated` as a baseline; additional permissions are noted per view.

### VendorRegistrationView

`POST /api/v1/vendors/register/`

Permission: `IsAuthenticated`

```python
class VendorRegistrationView(APIView):
    """
    Creates a Vendor profile (or retrieves existing one) and a new VendorCommunity
    membership for the given community_slug.

    Returns:
        201: {vendor_id, vendor_community_id, status, required_documents}
        400: validation error
        401: not authenticated
        404: community not found
        409: VendorCommunity already exists for (vendor, community)
    """
    permission_classes = [IsAuthenticated]
```

Logic steps (implement inside `post()`):
1. Pass `request.data` to `VendorRegistrationSerializer(data=request.data)` — serializer resolves `community_slug` to a `Community` instance and raises `ValidationError` (→ 400) or `Http404` (→ 404) accordingly.
2. Call `serializer.save(user=request.user)` — the serializer's `create()` method handles get-or-create of `Vendor` and atomic creation of `VendorCommunity`. Raises an exception (or returns a sentinel) if the `(vendor, community)` pair already exists — view must translate this to 409.
3. Compute `required_documents`: always `['govt_id', 'bank_proof']`; append `'fssai_cert'` if `vendor.is_food_seller == True`.
4. Return 201 with `vendor_id`, `vendor_community_id`, `status`, `required_documents`.

For the 409 case: catch `IntegrityError` (or a custom exception from the serializer) and return `Response({"detail": "Already registered for this community."}, status=409)`.

### DocumentUploadView

`POST /api/v1/vendors/{vendor_id}/documents/`

Permission: `IsAuthenticated`, `IsVendorOwner` (object-level)

```python
class DocumentUploadView(APIView):
    """
    Accepts multipart/form-data with fields: document_type (str), file (File).
    Validates file via 3-layer check (size → extension → magic bytes), uploads
    to S3, stores the key on the Vendor record.

    If document_type='fssai_cert' and vendor.fssai_number is a valid 14-digit string,
    enqueues verify_fssai.delay(vendor.pk) and sets fssai_status='pending'.

    Returns:
        200: {document_type, s3_key, missing_fssai_number: bool}
        400: validation error (file or document_type invalid)
        401: not authenticated
        403: not the vendor owner
        404: vendor not found
    """
    permission_classes = [IsAuthenticated, IsVendorOwner]
```

Logic steps (implement inside `post()`):
1. Fetch `Vendor` object by `vendor_id`; raise 404 if not found.
2. Call `self.check_object_permissions(request, vendor)` — triggers `IsVendorOwner`.
3. Pass `request.data` and `request.FILES` to `DocumentUploadSerializer`; call `is_valid(raise_exception=True)`. The serializer runs the 3-layer file validation.
4. Call `upload_vendor_document(vendor, document_type, validated_file)` from `apps/vendors/services/storage.py`. This returns the S3 key and updates the appropriate `*_s3_key` field on the vendor.
5. If `document_type == 'fssai_cert'`:
   - Check `vendor.fssai_number` — must be a non-empty string matching `^\d{14}$`.
   - If valid: call `vendor.fssai_status = FSSAIStatus.PENDING; vendor.save(update_fields=['fssai_status'])` then `verify_fssai.delay(vendor.pk)`.
   - If not valid: include `missing_fssai_number: True` in response.
6. Return 200 with `{document_type, s3_key, missing_fssai_number}`.

Import `verify_fssai` lazily inside the method body (or at the top of the module) to avoid circular imports:
```python
from apps.vendors.tasks import verify_fssai
```

### VendorSubmitView

`POST /api/v1/vendors/{vendor_id}/submit/`

Permission: `IsAuthenticated`, `IsVendorOwner` (object-level)

```python
class VendorSubmitView(APIView):
    """
    Submits a vendor's application to a community for admin review.
    Validates that all required documents are uploaded and FSSAI status
    is not 'failed'.

    Request body: {"community_slug": "prestige-oasis"}

    Returns:
        200: {status: 'pending_review'}
        400: missing documents, fssai_status=failed
        401: not authenticated
        403: not the vendor owner
        404: vendor not found, community not found, or VendorCommunity not found
    """
    permission_classes = [IsAuthenticated, IsVendorOwner]
```

Logic steps (implement inside `post()`):
1. Fetch `Vendor` by `vendor_id`; 404 if missing. Call `check_object_permissions`.
2. Resolve `community_slug` from `request.data` to a `Community`; 404 if not found.
3. Look up `VendorCommunity` for `(vendor, community)`; 404 if not found.
4. Validate required documents — build a list of missing keys and return 400 with a descriptive error if any are missing:
   - `govt_id_s3_key` must be non-empty
   - `bank_proof_s3_key` must be non-empty
   - If `vendor.is_food_seller == True`: `fssai_cert_s3_key` must be non-empty
5. If `vendor.fssai_status == FSSAIStatus.FAILED`, return 400 with message: `"FSSAI verification failed — please update your FSSAI certificate and license number before submitting"`.
6. Atomic transition: `VendorCommunity.objects.filter(pk=vc.pk).update(status=VendorCommunityStatus.PENDING_REVIEW)`.
7. Return 200 with `{"status": "pending_review"}`.

Note: Notifications to community admins (push + SMS) are mentioned in the plan but are out of scope for this split — add a `# TODO: enqueue admin notification task (split 05)` comment where that would go.

### VendorStatusView

`GET /api/v1/vendors/{vendor_id}/status/`

Permission: `IsAuthenticated`, `IsVendorOwner` (object-level)

```python
class VendorStatusView(APIView):
    """
    Returns the vendor's current application state: FSSAI status, any missing
    documents, and per-community approval statuses.

    Returns:
        200: VendorStatusSerializer response
        401: not authenticated
        403: not the vendor owner
        404: vendor not found
    """
    permission_classes = [IsAuthenticated, IsVendorOwner]
```

Logic steps (implement inside `get()`):
1. Fetch `Vendor` by `vendor_id`; 404 if missing. Call `check_object_permissions`.
2. Serialize with `VendorStatusSerializer(vendor)`.
3. Return 200 with serializer data.

The heavy lifting (computing `missing_documents` and `community_statuses`) is done by `VendorStatusSerializer` — the view is intentionally thin.

---

## Response Shapes

### POST /register/ — 201
```json
{
  "vendor_id": 42,
  "vendor_community_id": 7,
  "status": "pending_review",
  "required_documents": ["govt_id", "bank_proof", "fssai_cert"]
}
```

### POST /documents/ — 200
```json
{
  "document_type": "fssai_cert",
  "s3_key": "documents/vendors/42/fssai_cert/abc123.pdf",
  "missing_fssai_number": false
}
```

### POST /submit/ — 200
```json
{
  "status": "pending_review"
}
```

### GET /status/ — 200
```json
{
  "vendor_id": 42,
  "fssai_status": "verified",
  "fssai_expiry_date": "2026-03-31",
  "missing_documents": [],
  "community_statuses": [
    {
      "community_slug": "prestige-oasis",
      "status": "pending_review",
      "rejection_reason": ""
    }
  ]
}
```

---

## Key Design Decisions

**Transaction atomicity on registration**: Both `Vendor` (get-or-create) and `VendorCommunity` (create) must succeed or neither should persist. Wrap in `transaction.atomic()` inside the serializer's `create()` method. The view catches `IntegrityError` and returns 409 — this covers the race condition where two concurrent requests both pass the existence check before either inserts.

**FSSAI number validation in the view vs. task**: The 14-digit `fssai_number` regex check in `DocumentUploadView` is intentional. The Celery task (`verify_fssai`) should also have its own guard, but the view provides an immediate warning to the client that the task will not be triggered.

**`check_object_permissions` must be called explicitly**: DRF's `APIView` does not call `check_object_permissions` automatically — the view must fetch the object first and then call `self.check_object_permissions(request, obj)`. Forgetting this breaks the 403 tests.

**`update_fields` for status transitions**: Use `.update()` or `.save(update_fields=[...])` for atomic field updates to avoid clobbering concurrent changes to unrelated fields.

---

## Dependencies Summary

| Dependency | What it provides |
|------------|------------------|
| section-01 | `Vendor`, `VendorCommunity`, `FSSAIStatus`, `VendorCommunityStatus`, `LogisticsTier` |
| section-02 | `IsVendorOwner` (from `apps/core/permissions.py`) |
| section-05 | `validate_document_file()`, `upload_vendor_document()` (from `apps/vendors/services/storage.py`) |
| section-06 | `VendorRegistrationSerializer`, `DocumentUploadSerializer`, `VendorStatusSerializer` (from `apps/vendors/serializers.py`) |
| section-09 | `verify_fssai` Celery task — only `.delay` import; task body not required, stub is enough |
| section-12 | URL wiring — not needed to run this section's tests if you use `reverse()` or hard-coded paths |