I now have all the information needed to write the section. Let me produce the complete, self-contained section content.

# Section 06: Serializers

## Overview

This section implements all DRF serializers for the `apps/vendors/` app in a single file: `apps/vendors/serializers.py`. Serializers act as the validation and transformation layer between raw HTTP request data and the domain models. They are consumed by the API views in sections 07 and 08.

This section depends on:
- **section-01** — `Vendor`, `VendorCommunity`, `LogisticsTier`, `FSSAIStatus`, `VendorCommunityStatus` models
- **section-02** — `FSSAIVerificationError`, `ExternalAPIError` exception hierarchy (imported for error context only)
- **section-05** — `validate_document_file()` function from `apps/vendors/services/storage.py`, `generate_document_presigned_url()` from `apps/core/storage.py`

---

## File to Create

`/var/www/html/MadGirlfriend/namma-neighbour/apps/vendors/serializers.py`

---

## Tests First

Tests for serializers live in `apps/vendors/tests/test_views.py` (serializer behavior is exercised via the view layer). There are no standalone serializer unit tests — correctness is validated through the view integration tests listed below. The relevant test stubs to write before implementing:

```python
# apps/vendors/tests/test_views.py

# --- VendorRegistrationSerializer (via POST /api/v1/vendors/register/) ---

# Test: Creates Vendor and VendorCommunity on success; returns vendor_id and vendor_community_id
# Test: Sets is_food_seller=True when category_hint='food'
# Test: required_documents includes 'fssai_cert' when is_food_seller=True
# Test: required_documents does NOT include 'fssai_cert' when is_food_seller=False
# Test: Returns 409 when VendorCommunity already exists for (vendor, community)
# Test: Returns 404 when community_slug does not exist
# Test: Returns 401 when not authenticated
# Test: Vendor is NOT created twice if user already has a Vendor — reuses existing
# Test: Vendor and VendorCommunity are both created (or neither) — transaction atomicity

# --- DocumentUploadSerializer (via POST /api/v1/vendors/{vendor_id}/documents/) ---

# Test: Rejects file > 5MB with 400
# Test: Rejects invalid file type with 400
# Test: Accepts valid PDF, updates govt_id_s3_key
# Test: Accepts valid JPEG, updates bank_proof_s3_key
# Test: Returns 400 for invalid document_type value
# Test: Uploading fssai_cert without fssai_number → response warns (missing_fssai_number=True)

# --- VendorStatusSerializer (via GET /api/v1/vendors/{vendor_id}/status/) ---

# Test: Returns fssai_status and fssai_expiry_date
# Test: missing_documents is empty when all required docs are uploaded
# Test: missing_documents includes 'fssai_cert' when food seller missing cert
# Test: community_statuses reflects all VendorCommunity records for the vendor

# --- PendingVendorSerializer (via GET /api/v1/communities/{slug}/vendors/pending/) ---

# Test: Response includes presigned URL for each uploaded document (non-empty s3_key)
# Test: Response includes fssai_warning=True when vendor.fssai_status=failed

# --- VendorPublicProfileSerializer (via GET /api/v1/vendors/{vendor_id}/profile/) ---

# Test: Returns display_name, bio, average_rating, is_new_seller
# Test: Does NOT return fssai_number, razorpay_account_id, *_s3_key fields
```

---

## Serializer Specifications

### 6.1 `VendorRegistrationSerializer`

**Purpose:** Validates and processes the vendor registration request. Resolves the `community_slug` to a `Community` instance and creates both `Vendor` and `VendorCommunity` atomically.

**Input fields:**
- `display_name` — CharField, required
- `bio` — CharField, optional (blank allowed)
- `logistics_tier` — ChoiceField from `LogisticsTier` choices, required
- `community_slug` — CharField, write-only, required
- `category_hint` — CharField, optional (valid value: `"food"`)

**Validation logic (`validate()`):**
- Look up `Community` by `community_slug`; raise `ValidationError` with a 404-style message if not found (the view will translate this to an HTTP 404)
- Store the resolved community on the validated data

**Creation logic (`create()`):**
- Wrap everything in `transaction.atomic()`
- Use `get_or_create` on `Vendor` keyed by `user`; set `display_name`, `bio`, `logistics_tier`
- If `category_hint == "food"`, set `vendor.is_food_seller = True` and save
- Check if `VendorCommunity` already exists for `(vendor, community)` — if so, raise a `ValidationError` (the view will translate this to HTTP 409)
- Create `VendorCommunity(vendor=vendor, community=community, status=VendorCommunityStatus.PENDING_REVIEW)`

**Output (`to_representation()`):**
- `vendor_id`
- `vendor_community_id`
- `status` (always `"pending_review"`)
- `required_documents` — computed list: always includes `"govt_id"` and `"bank_proof"`; appends `"fssai_cert"` when `vendor.is_food_seller == True`

**Stub:**
```python
class VendorRegistrationSerializer(serializers.Serializer):
    """Handles vendor registration and first community membership creation.

    Resolves community_slug to Community; wraps Vendor + VendorCommunity
    creation in transaction.atomic(). Returns required_documents list.
    """
    display_name = serializers.CharField(max_length=150)
    bio = serializers.CharField(allow_blank=True, required=False, default='')
    logistics_tier = serializers.ChoiceField(choices=LogisticsTier.choices)
    community_slug = serializers.CharField(write_only=True)
    category_hint = serializers.CharField(required=False, default='')

    def validate(self, attrs): ...
    def create(self, validated_data): ...
    def to_representation(self, instance): ...
```

---

### 6.2 `DocumentUploadSerializer`

**Purpose:** Validates a document upload request. Enforces `document_type` choice and runs the 3-layer file validation (size → extension → magic bytes) by calling `validate_document_file()` from `apps/vendors/services/storage.py`.

**Input fields:**
- `document_type` — ChoiceField, required. Valid choices: `"govt_id"`, `"fssai_cert"`, `"bank_proof"`, `"gst_cert"`
- `file` — FileField, required (from `multipart/form-data` request)

**Validation logic:**
- `validate_file()` calls `validate_document_file(file)` from `apps/vendors/services/storage.py`; if it raises `ValidationError`, that propagates directly
- No additional cross-field logic needed; file and document_type are validated independently

**`save()` / post-validation behavior (handled in view, not serializer):**
- After `.is_valid()`, the view performs the S3 upload and sets the `fssai_number` warning
- The serializer itself does not perform S3 upload — it only validates

**Response extras:**
- The serializer does not produce `missing_fssai_number` in `to_representation`; the view injects this into the response after calling `validated_data` logic

**Stub:**
```python
class DocumentUploadSerializer(serializers.Serializer):
    """Validates document_type choice and file content (size, extension, magic bytes).

    Does NOT perform S3 upload — that is handled by the view after validation.
    """
    DOCUMENT_TYPE_CHOICES = ['govt_id', 'fssai_cert', 'bank_proof', 'gst_cert']

    document_type = serializers.ChoiceField(choices=DOCUMENT_TYPE_CHOICES)
    file = serializers.FileField()

    def validate_file(self, value): ...
```

---

### 6.3 `VendorStatusSerializer`

**Purpose:** Read-only serializer for `GET /api/v1/vendors/{vendor_id}/status/`. Computes `missing_documents` dynamically from vendor fields and serializes all `VendorCommunity` records for the vendor.

**Output fields:**
- `vendor_id` — IntegerField (source: `pk`)
- `fssai_status` — CharField
- `fssai_expiry_date` — DateField (nullable)
- `missing_documents` — SerializerMethodField
- `community_statuses` — SerializerMethodField

**`get_missing_documents(vendor)` logic:**
- Start with empty list
- Always check: `govt_id_s3_key` empty → add `"govt_id"`
- Always check: `bank_proof_s3_key` empty → add `"bank_proof"`
- If `vendor.is_food_seller == True`: `fssai_cert_s3_key` empty → add `"fssai_cert"`

**`get_community_statuses(vendor)` logic:**
- Query `vendor.community_memberships.select_related('community').all()`
- Return a list of dicts: `{"community_slug": ..., "status": ..., "rejection_reason": ...}`

**Stub:**
```python
class VendorStatusSerializer(serializers.ModelSerializer):
    """Read-only serializer for vendor application status.

    Computes missing_documents from is_food_seller + s3_key fields.
    Includes community_statuses for all VendorCommunity memberships.
    """
    missing_documents = serializers.SerializerMethodField()
    community_statuses = serializers.SerializerMethodField()

    def get_missing_documents(self, vendor): ...
    def get_community_statuses(self, vendor): ...

    class Meta:
        model = Vendor
        fields = ['vendor_id', 'fssai_status', 'fssai_expiry_date',
                  'missing_documents', 'community_statuses']
```

Note: if `Vendor.pk` is named `id` in the model, expose it as `vendor_id` using `source='pk'` on an `IntegerField`, or add `vendor_id` as a `SerializerMethodField`.

---

### 6.4 `PendingVendorSerializer`

**Purpose:** Used by the community admin pending queue (`GET /api/v1/communities/{slug}/vendors/pending/`). Extends vendor fields with presigned document URLs and an FSSAI warning flag. The serializer receives `VendorCommunity` instances (not `Vendor` directly), so fields traverse via `vendor.*`.

**Output fields:**
- `vendor_id` — from `vendor.pk`
- `display_name` — from `vendor.display_name`
- `bio` — from `vendor.bio`
- `logistics_tier` — from `vendor.logistics_tier`
- `fssai_status` — from `vendor.fssai_status`
- `fssai_business_name` — from `vendor.fssai_business_name`
- `fssai_warning` — SerializerMethodField: `True` if `vendor.fssai_status == FSSAIStatus.FAILED`
- `average_rating` — from `vendor.average_rating`
- `is_new_seller` — from `vendor.is_new_seller` (property)
- `document_urls` — SerializerMethodField

**`get_document_urls(vendor_community)` logic:**
- For each of `govt_id_s3_key`, `bank_proof_s3_key`, `fssai_cert_s3_key`, `gst_cert_s3_key` on `vendor_community.vendor`:
  - If the field value is non-empty, call `generate_document_presigned_url(s3_key)` from `apps/core/storage.py`
  - Return a dict keyed by document type name (e.g., `{"govt_id": "https://...", "fssai_cert": "https://..."}`)
  - Omit document types where the s3_key is empty

**`get_fssai_warning(vendor_community)` logic:**
- Return `vendor_community.vendor.fssai_status == FSSAIStatus.FAILED`

**Stub:**
```python
class PendingVendorSerializer(serializers.ModelSerializer):
    """Serializes VendorCommunity records for the admin pending queue.

    Adds document_urls (presigned S3 URLs for non-empty s3_keys) and
    fssai_warning flag. Presigned URL generation uses s3v4, ExpiresIn=3600.
    """
    fssai_warning = serializers.SerializerMethodField()
    document_urls = serializers.SerializerMethodField()
    # Traversal fields from vendor.*
    vendor_id = serializers.IntegerField(source='vendor.pk', read_only=True)
    display_name = serializers.CharField(source='vendor.display_name', read_only=True)
    bio = serializers.CharField(source='vendor.bio', read_only=True)
    logistics_tier = serializers.CharField(source='vendor.logistics_tier', read_only=True)
    fssai_status = serializers.CharField(source='vendor.fssai_status', read_only=True)
    fssai_business_name = serializers.CharField(source='vendor.fssai_business_name', read_only=True)
    average_rating = serializers.DecimalField(source='vendor.average_rating', max_digits=3, decimal_places=2, read_only=True)
    is_new_seller = serializers.BooleanField(source='vendor.is_new_seller', read_only=True)

    def get_fssai_warning(self, vendor_community): ...
    def get_document_urls(self, vendor_community): ...

    class Meta:
        model = VendorCommunity
        fields = [
            'vendor_id', 'display_name', 'bio', 'logistics_tier',
            'fssai_status', 'fssai_business_name', 'fssai_warning',
            'average_rating', 'is_new_seller', 'document_urls',
        ]
```

---

### 6.5 `VendorPublicProfileSerializer`

**Purpose:** Exposes only public-safe fields for `GET /api/v1/vendors/{vendor_id}/profile/`. Must never include KYB fields, S3 keys, FSSAI license numbers, Razorpay identifiers, or bank information.

**Output fields (exhaustive — all others must be excluded):**
- `vendor_id` (source: `pk`)
- `display_name`
- `bio`
- `average_rating`
- `is_new_seller`

**Stub:**
```python
class VendorPublicProfileSerializer(serializers.ModelSerializer):
    """Read-only public profile. Exposes only display-safe fields.

    Explicitly excludes: fssai_number, fssai_*, razorpay_*, *_s3_key,
    bank_account_verified, gstin, gst_cert_s3_key, govt_id_s3_key,
    bank_proof_s3_key, user.
    """
    vendor_id = serializers.IntegerField(source='pk', read_only=True)
    is_new_seller = serializers.BooleanField(read_only=True)

    class Meta:
        model = Vendor
        fields = ['vendor_id', 'display_name', 'bio', 'average_rating', 'is_new_seller']
        read_only_fields = fields
```

---

## Implementation Notes

### Imports Required

```python
from django.db import transaction
from rest_framework import serializers
from apps.vendors.models import (
    Vendor, VendorCommunity, LogisticsTier, FSSAIStatus, VendorCommunityStatus
)
from apps.vendors.services.storage import validate_document_file
from apps.core.storage import generate_document_presigned_url
# Community model from wherever it lives in the project:
from apps.communities.models import Community  # adjust app path as needed
```

### Atomic Transaction Pattern

`VendorRegistrationSerializer.create()` must use `transaction.atomic()` so that if the `VendorCommunity` insert fails (e.g., unique constraint violation from a race condition), the Vendor creation is also rolled back. Do not rely on the view's transaction context — make it explicit in the serializer.

### 409 Conflict Handling

When `VendorCommunity` already exists for a `(vendor, community)` pair, the serializer raises `ValidationError`. The view is responsible for catching this and returning HTTP 409 — the serializer should signal the conflict via a clearly named `ValidationError` code (e.g., `code='duplicate_community'`) so the view can distinguish this from a regular validation error.

### `community_slug` Resolution Timing

The `community_slug` field is `write_only=True` — it does not appear in any output. Resolve it in `validate()` (not `create()`) so that DRF's error handling can return a 404 before entering the creation block.

### `missing_fssai_number` Warning

When the document upload view processes an `fssai_cert` upload and `vendor.fssai_number` is empty or invalid, it must include a `missing_fssai_number: true` warning in the response. This is injected by the **view**, not the serializer. The `DocumentUploadSerializer` does not need to produce this field — it only validates the file and `document_type`.

### `PendingVendorSerializer` Query Optimization

The view calling `PendingVendorSerializer` must use `select_related('vendor')` on the `VendorCommunity` queryset to avoid N+1 queries during presigned URL generation and field traversal. This is enforced at the view level (section 08), not here, but document the requirement in a comment on the serializer.

### Security: Presigned URL Scope

`generate_document_presigned_url()` generates a time-limited (1-hour) read URL for a specific S3 object key. The serializer calls this at serialization time. URL generation is HMAC-based (CPU-only, no network call) and safe to run synchronously during request handling for up to 40 documents per page (10 vendors × 4 document types).

---

## Actual Implementation Notes

- **VendorRegistrationSerializer**: `is_food_seller` update moved AFTER duplicate-community check to avoid rollback inconsistency. `IntegrityError` caught at `VendorCommunity.create()` and converted to `ValidationError(code='duplicate_community')` for race-condition safety. `save()` guard added to prevent misuse with `instance=`. `to_representation` uses `vendor_community.status` (not hardcoded).
- **gst_cert**: Optional for MVP; not included in `VendorStatusSerializer.get_missing_documents()`.
- **Test file**: `apps/vendors/tests/test_serializers.py` (20 tests, direct serializer unit tests, not view integration tests).
- **test_views.py**: Kept as stub placeholder for sections 07/08.

## Checklist

- [x] Create `apps/vendors/serializers.py`
- [ ] Implement `VendorRegistrationSerializer` with atomic creation, `community_slug` resolution, `is_food_seller` assignment, `required_documents` output
- [ ] Implement `DocumentUploadSerializer` with `validate_file()` calling `validate_document_file()`
- [ ] Implement `VendorStatusSerializer` with `get_missing_documents()` and `get_community_statuses()`
- [ ] Implement `PendingVendorSerializer` with `get_document_urls()` (presigned URLs for non-empty keys) and `get_fssai_warning()`
- [ ] Implement `VendorPublicProfileSerializer` with exactly 5 fields, no sensitive data
- [ ] Write test stubs in `apps/vendors/tests/test_views.py` (see Tests First section above)
- [ ] Verify serializers can be imported without error (`python manage.py check`)