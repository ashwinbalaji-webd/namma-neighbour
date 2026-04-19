# Implementation Plan: 03-Seller Onboarding

## Overview

This plan describes the implementation of vendor onboarding for the NammaNeighbor hyperlocal marketplace. Vendors are home sellers (home bakers, organic farmers, artisans) who list products available for delivery within one or more residential communities. Before they can sell, they must pass a KYB (Know Your Business) verification process: upload identity and bank documents, optionally verify an FSSAI food license via a third-party API, and receive approval from a community admin. Once approved, a Razorpay Linked Account is created so payouts can be split from customer payments.

The key design decisions driving this plan:
- A vendor has **one global profile** (single `Vendor` model) but can be active in **multiple communities** — each community approval is independent
- FSSAI verification is automated via the Surepass API but has a manual ops fallback for API failures
- Razorpay Linked Account is created once (on first community approval) and reused across all communities
- File uploads use 3-layer validation (size → extension → magic bytes) before reaching S3
- Celery tasks use guard clauses and atomic DB updates to be safe for concurrent execution and retries
- `UserRole(role='vendor', community=community)` is created on community approval, not on registration — vendors gain vendor JWT claims only after admin approval

---

## Section 1: App Scaffold and Models

### 1.1 App Creation

Create a new Django app at `apps/vendors/`. Register it in `INSTALLED_APPS` as `apps.vendors`. The app follows the established project convention:

```
apps/vendors/
├── __init__.py
├── apps.py
├── models.py
├── serializers.py
├── views.py
├── urls.py
├── admin.py
├── tasks.py
├── services/
│   ├── __init__.py
│   ├── fssai.py
│   └── razorpay.py
└── tests/
    ├── __init__.py
    ├── factories.py
    ├── conftest.py
    ├── test_models.py
    ├── test_views.py
    ├── test_tasks.py
    └── test_services.py
```

Register URL namespace `vendors` in the main router.

### 1.2 Choice Enumerations

Three `TextChoices` enumerations belong in `models.py`:

**LogisticsTier** — how a vendor delivers goods:
- `tier_a` ("Self-delivery, own bike/van") — vendor delivers to community gate
- `tier_b` ("NammaNeighbor pickup required") — vendor has goods ready 2 hours before drop window; platform runner collects

**FSSAIStatus** — the lifecycle of FSSAI license verification:
- `not_applicable` — vendor did not register as food seller
- `pending` — verification requested but not yet completed (also used as the Celery task claim guard)
- `verified` — Surepass confirmed license active
- `expired` — license found but past expiry date
- `failed` — license invalid, not found, or API confirmed cancelled/suspended

**VendorCommunityStatus** — per-community approval state:
- `pending_review` — submitted for admin review
- `approved` — community admin accepted the vendor
- `rejected` — admin rejected; vendor can correct and resubmit
- `suspended` — auto-delisted due to missed drop windows, or manually suspended by admin

### 1.3 Vendor Model

The `Vendor` model inherits `TimestampedModel` from `apps.core.models`. It stores the global vendor profile and all KYB/compliance data. All S3-stored documents are represented as `CharField(max_length=500)` holding S3 object keys, **not** FileField — presigned URLs are generated on-demand.

Fields:

| Field | Type | Notes |
|-------|------|-------|
| `user` | OneToOneField(User, CASCADE) | `related_name='vendor_profile'` |
| `display_name` | CharField(max_length=150) | Shown to residents |
| `bio` | TextField(blank=True) | Global bio |
| `logistics_tier` | CharField(choices=LogisticsTier) | Required at registration |
| `is_food_seller` | BooleanField(default=False) | Set True when `category_hint=food` at registration. Drives FSSAI document requirement. |
| `govt_id_s3_key` | CharField(max_length=500, blank=True) | S3 key for uploaded govt ID |
| `bank_proof_s3_key` | CharField(max_length=500, blank=True) | S3 key for bank proof |
| `fssai_number` | CharField(max_length=14, blank=True, validators=[RegexValidator(r'^\d{14}$')]) | 14-digit FSSAI license number. Validated at model and serializer level. |
| `fssai_status` | CharField(choices=FSSAIStatus, default=not_applicable) | |
| `fssai_cert_s3_key` | CharField(max_length=500, blank=True) | S3 key for uploaded FSSAI cert PDF |
| `fssai_verified_at` | DateTimeField(null=True) | Timestamp of last successful API verification |
| `fssai_expiry_date` | DateField(null=True) | From API response |
| `fssai_business_name` | CharField(max_length=200, blank=True) | From API response |
| `fssai_authorized_categories` | JSONField(default=list) | From API response; stored for future product-category matching |
| `fssai_expiry_warning_sent` | BooleanField(default=False) | Set True after sending the 30-day expiry warning. Reset to False when `fssai_status` changes to `verified`. Prevents repeated daily API calls for the same vendor. |
| `gstin` | CharField(max_length=15, blank=True) | Optional for MVP |
| `gst_cert_s3_key` | CharField(max_length=500, blank=True) | Optional for MVP |
| `razorpay_account_id` | CharField(max_length=100, blank=True) | From Razorpay response |
| `razorpay_account_status` | CharField(max_length=20, blank=True) | `pending` / `under_review` / `activated` / `rejected` |
| `razorpay_onboarding_step` | CharField(max_length=20, blank=True) | Tracks Razorpay sub-steps: `''` (not started), `'account_created'`, `'stakeholder_added'`, `'submitted'`. Enables safe retry at any step. |
| `bank_account_verified` | BooleanField(default=False) | Set True by `account.activated` webhook |
| `completed_delivery_count` | PositiveIntegerField(default=0) | Updated by Order management (split 05) |
| `average_rating` | DecimalField(max_digits=3, decimal_places=2, default=0.00) | Aggregated |

**Property `is_new_seller`:** Returns `True` when `completed_delivery_count < 5 OR average_rating < Decimal('4.5')`. Both conditions must be satisfied (≥5 deliveries AND ≥4.5 rating) before the "New Seller" badge is removed. This matches the PRD intent: the badge signals that we don't yet have enough data to trust the seller.

**DB indexes:** Add `db_index=True` on `fssai_expiry_date` — the `recheck_fssai_expiry` cron queries on this column daily.

### 1.4 VendorCommunity Model

The join table between vendors and communities. Each row represents one vendor's relationship with one community and tracks per-community approval state and penalty tracking.

Fields:

| Field | Type | Notes |
|-------|------|-------|
| `vendor` | ForeignKey(Vendor, CASCADE) | `related_name='community_memberships'` |
| `community` | ForeignKey(Community, PROTECT) | `related_name='vendor_memberships'` |
| `status` | CharField(choices=VendorCommunityStatus) | |
| `approved_by` | ForeignKey(User, null=True, SET_NULL) | Community admin who approved |
| `approved_at` | DateTimeField(null=True) | |
| `rejection_reason` | TextField(blank=True) | Shown to vendor on rejection |
| `delist_threshold` | PositiveIntegerField(default=2) | Admin can raise/lower per community |
| `missed_window_count` | PositiveIntegerField(default=0) | Incremented by split 05 Order management |

**Unique constraint:** `(vendor, community)` — one relationship record per pair.

**DB indexes:**
- Composite index on `(community_id, status)` — used by the admin pending queue query and auto-delist cron
- These can be expressed as `class Meta: indexes = [models.Index(fields=['community', 'status'])]`

### 1.5 Migration

Create a migration for both models. The migration depends on the `communities` app migration (Community model) and `users` app migration (User model).

---

## Section 2: Permissions and Custom Exceptions

### 2.1 IsVendorOwner Permission

Add `IsVendorOwner` to `apps/core/permissions.py`. This is an object-level permission: the request user must be the owner of the Vendor being accessed.

```python
class IsVendorOwner(BasePermission):
    """Object-level: request.user must be the vendor's user."""

    def has_object_permission(self, request, view, obj) -> bool:
        """Return True if obj.user_id matches request.user.id."""
```

The `obj` parameter will be a `Vendor` instance. Views using this permission must call `self.check_object_permissions(request, vendor)` explicitly after fetching the Vendor by `vendor_id`. Use a `get_vendor_or_404` helper in views that fetches the vendor and immediately calls `check_object_permissions` to prevent accidentally forgetting the check.

### 2.2 Custom Exceptions

Add to `apps/core/exceptions.py`. The exception hierarchy:

```
ExternalAPIError (HTTP 503)          ← base for all third-party API failures
├── TransientAPIError (HTTP 503)     ← retriable: 5xx, timeout, connection error
└── PermanentAPIError (HTTP 503)     ← non-retriable: 400/404 from third-party

RazorpayError(PermanentAPIError, HTTP 402)      ← Razorpay business logic error
FSSAIVerificationError(PermanentAPIError, HTTP 400)  ← FSSAI permanent failure
```

- **`ExternalAPIError`** — base class, HTTP 503. Signals infrastructure-level failure.
- **`TransientAPIError`** — used in `autoretry_for` tuples in Celery tasks. Raised by services when the failure is temporary (5xx response, timeout, connection refused).
- **`PermanentAPIError`** — raised by services when the failure is definitively not retriable (400 invalid input, 404 not found). Tasks catch this and do NOT re-raise it (prevents Celery retry loop).
- **`RazorpayError`** — Razorpay-specific business logic error (duplicate reference_id, invalid bank account), HTTP 402.
- **`FSSAIVerificationError`** — FSSAI permanent failure (invalid license format, license not found), HTTP 400.

---

## Section 3: FSSAI Service

### 3.1 SurepassFSSAIClient

Located at `apps/vendors/services/fssai.py`. This class wraps the Surepass FSSAI API with clean error handling and a normalized response interface.

The client reads `settings.SUREPASS_TOKEN` for the Bearer token. Error translation:
- HTTP 400, 404 → raise `FSSAIVerificationError` (permanent)
- HTTP 429, 5xx → raise `TransientAPIError` (retriable)
- `requests.Timeout`, `requests.ConnectionError` → raise `TransientAPIError`

**Key methods:**

```python
class SurepassFSSAIClient:
    BASE_URL = "https://kyc-api.surepass.io/api/v1"

    def verify_fssai(self, license_number: str) -> dict:
        """Call /fssai/fssai-full-details. Returns normalized dict:
        {
          'status': 'active'|'expired'|'cancelled'|'suspended',
          'business_name': str,
          'expiry_date': date,
          'authorized_categories': list[str],
        }
        Raises FSSAIVerificationError on permanent failures,
        TransientAPIError on transient failures.
        """

    def check_expiry(self, license_number: str) -> dict:
        """Call /fssai/fssai-expiry-check. Cheaper endpoint used by the
        daily cron. Returns normalized dict with 'status' and 'expiry_date'.
        """
```

The timeout for all requests is 10 seconds.

---

## Section 4: Razorpay Service

### 4.1 RazorpayClient

Located at `apps/vendors/services/razorpay.py`. Wraps the Razorpay Route (Linked Accounts) API.

Reads `settings.RAZORPAY_KEY_ID` and `settings.RAZORPAY_KEY_SECRET` for HTTP Basic Auth. Error translation:
- HTTP 400, 409 → raise `RazorpayError` (permanent)
- HTTP 429, 5xx → raise `TransientAPIError`
- `requests.Timeout`, `requests.ConnectionError` → raise `TransientAPIError`

**Key methods:**

```python
class RazorpayClient:

    def create_linked_account(self, vendor: Vendor) -> str:
        """POST /v2/accounts with type='route'.
        Returns the Razorpay account ID (acc_XXXXX).
        reference_id = str(vendor.pk) for idempotency.
        Raises RazorpayError on business logic errors,
        TransientAPIError on 5xx/timeout.
        """

    def add_stakeholder(self, account_id: str, vendor: Vendor) -> str:
        """POST /v2/accounts/{account_id}/stakeholders.
        Returns stakeholder_id.
        """

    def submit_for_review(self, account_id: str) -> None:
        """PATCH /v2/accounts/{account_id} to trigger Razorpay review.
        """
```

The `create_linked_account` call must include all mandatory fields: `email`, `phone`, `type=route`, `legal_business_name`, `business_type`, `contact_name`, `profile.category`, `profile.addresses.registered`, `legal_info.pan`. `reference_id=str(vendor.pk)` provides Razorpay-side idempotency.

---

## Section 5: S3 Document Upload Logic

### 5.1 File Validation

File validation is performed in the serializer's `validate_file()` method before uploading to S3. Three layers must pass in order:

1. **Size check** (fast): reject files larger than **5MB** (lowered from 10MB to stay within Razorpay's stakeholder document upload limits of 4MB images / 2MB PDFs)
2. **Extension check** (lightweight): allow only `.pdf`, `.jpg`, `.jpeg`, `.png`
3. **Magic byte check** (authoritative): read the first 2048 bytes, use the `filetype` or `python-magic` library to detect MIME type, accept only `application/pdf`, `image/jpeg`, `image/png`

If any layer fails, raise `ValidationError` with a descriptive message. Do not proceed to S3 upload.

### 5.2 S3 Upload

After validation, upload via `DocumentStorage` (already configured in `apps/core/storage.py`). The S3 key follows the pattern:

```
documents/vendors/{vendor_id}/{document_type}/{uuid4}.{ext}
```

Where `document_type` is one of: `govt_id`, `fssai_cert`, `bank_proof`, `gst_cert`.

After a successful upload, update the corresponding `*_s3_key` field on the Vendor model. If the `document_type` is `fssai_cert` and the vendor's `fssai_number` passes the regex validator (i.e., is a valid 14-digit number), enqueue `verify_fssai.delay(vendor.pk)`.

### 5.3 Presigned URL Generation

For community admin document review, generate presigned URLs using `boto3` directly (not via `DocumentStorage`). Use:
- `signature_version="s3v4"` (required for ap-south-1/Mumbai — v2 fails)
- `ExpiresIn=3600` (1 hour)
- `region_name="ap-south-1"`

Encapsulate in a `generate_document_presigned_url(s3_key: str) -> str` helper in `apps/core/storage.py`.

---

## Section 6: API Views — Vendor Registration and Document Upload

### 6.1 POST /api/v1/vendors/register/

Creates a vendor profile and their first community membership.

Request shape:
```json
{
  "display_name": "Radha's Organic Kitchen",
  "bio": "...",
  "logistics_tier": "tier_b",
  "community_slug": "prestige-oasis",
  "category_hint": "food"
}
```

Business logic:
- If the authenticated user already has a `Vendor` record, retrieve it. Otherwise create one.
- Look up `Community` by `community_slug`; 404 if not found.
- If a `VendorCommunity` record already exists for this `(vendor, community)` pair, return 409 Conflict.
- Create `VendorCommunity` with `status=pending_review`.
- If `category_hint == "food"`, set `vendor.is_food_seller = True` (this persists the food requirement for later validation at submit time).
- Compute required documents: `govt_id` + `bank_proof` always; add `fssai_cert` if `is_food_seller=True`.
- Return `vendor_id`, `vendor_community_id`, `status`, `required_documents`.
- Wrap creation in `transaction.atomic()`.

**UserRole is NOT created here** — vendors gain the `vendor` role only after community admin approval.

Serializer: `VendorRegistrationSerializer` — validates choices, resolves `community_slug`, handles the atomic creation.

### 6.2 POST /api/v1/vendors/{vendor_id}/documents/

Accepts `multipart/form-data`. Fields: `document_type`, `file`.

Business logic:
- Fetch `Vendor` by `vendor_id`; call `check_object_permissions(request, vendor)` to enforce `IsVendorOwner`
- Validate document_type is one of: `govt_id`, `fssai_cert`, `bank_proof`, `gst_cert`
- Run 3-layer file validation via `DocumentUploadSerializer.validate_file()`
- Upload to S3, store key on vendor
- If `document_type == fssai_cert` and `vendor.fssai_number` is valid (14 digits): enqueue `verify_fssai.delay(vendor.pk)`; set `fssai_status=pending`

Serializer: `DocumentUploadSerializer` — validates `document_type` choice and runs file validators.

### 6.3 POST /api/v1/vendors/{vendor_id}/submit/

Submits the vendor application to a specific community for admin review.

Request shape:
```json
{"community_slug": "prestige-oasis"}
```

Business logic:
- Fetch `Vendor` by `vendor_id`; enforce `IsVendorOwner`
- Retrieve the `VendorCommunity` record for `(vendor, community)`. 404 if not found.
- Check required documents:
  - `govt_id_s3_key` and `bank_proof_s3_key` must be non-empty (always required)
  - If `vendor.is_food_seller == True`: `fssai_cert_s3_key` must be non-empty (uses the persisted field — no fragile heuristics)
- If `fssai_status == failed`: block with 400 error ("FSSAI verification failed — please update your FSSAI certificate and license number before submitting")
- Atomic transition: `VendorCommunity.status → pending_review` via `filter().update()`
- Enqueue notification to community admins (push + SMS)

### 6.4 GET /api/v1/vendors/{vendor_id}/status/

Returns a summary of the vendor's application state across all communities.

Response shape:
```json
{
  "vendor_id": 42,
  "fssai_status": "verified",
  "fssai_expiry_date": "2026-03-31",
  "missing_documents": ["fssai_cert"],
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

## Section 7: API Views — Community Admin Workflow

### 7.1 GET /api/v1/communities/{slug}/vendors/pending/

Permission: `IsCommunityAdmin` on the community identified by `slug`.

Returns paginated list (page_size=10) of `VendorCommunity` records with `status=pending_review` for this community. For each vendor, include:
- `vendor_id`, `display_name`, `bio`, `logistics_tier`
- `fssai_status`, `fssai_business_name`, and `fssai_warning` flag (True if `fssai_status == failed`)
- Presigned S3 URLs (TTL=3600s, generated at serialization time) for each uploaded document
- `average_rating`, `is_new_seller`

Pagination bounds the presigned URL generation cost (at most 10 vendors × 4 document types = 40 URL generation calls per page). Presigned URL generation is CPU-bound (HMAC computation) and does not hit the network.

### 7.2 POST /api/v1/vendors/{vendor_id}/approve/

Permission: `IsCommunityAdmin`.

Request shape:
```json
{
  "community_slug": "prestige-oasis",
  "override_fssai_warning": false
}
```

Business logic:
- Resolve `community_slug` to a `Community` object.
- **Authorization cross-check**: verify that `request.user` is an admin of the resolved community (not just any community). This prevents a community admin from approving a vendor for a different community by passing a different `community_slug` in the body.
- Retrieve `VendorCommunity` for `(vendor, community)` where `status=pending_review`. 404 otherwise.
- **FSSAI guard**: if `vendor.fssai_status == failed` and `override_fssai_warning != True`, return 400 with warning. Forces an explicit decision.
- Atomic update: `VendorCommunity.status → approved`, set `approved_by`, `approved_at`.
- Increment `community.vendor_count` atomically (`F()` expression).
- **UserRole creation**: create `UserRole(user=vendor.user, role='vendor', community=community)` if it doesn't already exist. This gives the vendor the `vendor` role in their JWT for this community after the next token refresh.
- **First approval check**: if `vendor.razorpay_onboarding_step == ''` (never started), enqueue `create_razorpay_linked_account.delay(vendor.pk)`.
- Enqueue SMS notification to vendor.

### 7.3 POST /api/v1/vendors/{vendor_id}/reject/

Permission: `IsCommunityAdmin`.

Request shape:
```json
{
  "community_slug": "prestige-oasis",
  "reason": "FSSAI certificate expired"
}
```

Business logic:
- Resolve `community_slug` and perform the same authorization cross-check as approve.
- Retrieve `VendorCommunity` for `(vendor, community)`. Records in `pending_review` or `approved` can be rejected.
- Atomic update: `status → rejected`, store `rejection_reason`.
- If the record was previously `approved`: decrement `community.vendor_count` atomically. (`vendor_count` represents current active/approved vendor count, not lifetime.)
- Enqueue SMS notification to vendor with the rejection reason.
- The vendor can update their documents and re-submit; same `VendorCommunity` record is reused.

### 7.4 GET /api/v1/vendors/{vendor_id}/profile/

Permission: `IsResidentOfCommunity`.

Returns only public fields: `display_name`, `bio`, `average_rating`, `is_new_seller`. No KYB, bank, or Razorpay data.

---

## Section 8: Celery Tasks

### 8.1 verify_fssai(vendor_id)

Queue: `kyc`. Configuration:
- `bind=True`
- `autoretry_for=(requests.Timeout, requests.ConnectionError, TransientAPIError)`
- `max_retries=5`, `retry_backoff=True`, `retry_backoff_max=300`, `retry_jitter=True`
- `acks_late=True`

Execution flow:
1. Fetch `Vendor` by PK; if not found, return silently
2. **Terminal state guard**: if `fssai_status in (verified, failed)` → return immediately (never re-call a paid API for a terminal state)
3. **Claim via atomic update**: `Vendor.objects.filter(pk=vendor_id, fssai_status='pending').update(fssai_status='pending')` — this is a no-op write that acts as a serialization point. For stronger concurrency protection, the task logs a warning if it detects it's running while another worker is also at the API call stage. Since the terminal state guard at step 2 handles idempotency after completion, and Surepass results are deterministic for the same license number, duplicate concurrent calls are harmless beyond the API cost.
4. Call `SurepassFSSAIClient.verify_fssai(vendor.fssai_number)`
5. On success (`status=active`): atomic update — `fssai_status=verified`, `fssai_verified_at`, `fssai_expiry_date`, `fssai_business_name`, `fssai_authorized_categories`, **`fssai_expiry_warning_sent=False`** (reset the warning flag when re-verified)
6. On FSSAI-reported `expired|cancelled|suspended`: atomic update — `fssai_status=failed`
7. On `FSSAIVerificationError` (permanent, 400/404): atomic update — `fssai_status=failed`; do NOT re-raise (prevents Celery retry)
8. On `TransientAPIError` (5xx/timeout): re-raise to trigger autoretry
9. After max retries exhausted: set `fssai_status=pending` (manual ops fallback — the uploaded PDF in S3 is used for manual review)

**Note on `fssai_status=pending` as task claim guard:** `pending` is a declared `FSSAIStatus` choice that means "awaiting API verification." Using it as the guard state is semantically correct and avoids any need for an undeclared `in_progress` value.

### 8.2 create_razorpay_linked_account(vendor_id)

Queue: `payments`. Configuration:
- `bind=True`
- `autoretry_for=(requests.Timeout, requests.ConnectionError, TransientAPIError)`
- `max_retries=3`

Execution flow:
1. Fetch `Vendor` by PK
2. **Terminal state guard**: if `razorpay_onboarding_step == 'submitted'` → return immediately
3. **Atomic claim** (prevents concurrent duplicate calls): `Vendor.objects.filter(pk=vendor_id, razorpay_onboarding_step='').update(razorpay_onboarding_step='claiming')` — if 0 rows updated, another worker owns it; return
4. **Resume from last completed step**: read `razorpay_onboarding_step` to determine where to start:
   - `''` or `'claiming'`: run step 5
   - `'account_created'`: skip to step 6
   - `'stakeholder_added'`: skip to step 7
5. Call `RazorpayClient.create_linked_account(vendor)` → atomic update `razorpay_account_id=account_id`, `razorpay_account_status=pending`, `razorpay_onboarding_step='account_created'`
6. Call `RazorpayClient.add_stakeholder(account_id, vendor)` → atomic update `razorpay_onboarding_step='stakeholder_added'`
7. Call `RazorpayClient.submit_for_review(account_id)` → atomic update `razorpay_onboarding_step='submitted'`
8. Bank verification is handled asynchronously by the `account.activated` webhook

On `RazorpayError` (business logic failure): log error, set `razorpay_account_status='rejected'`; do NOT re-raise.
On `TransientAPIError`: re-raise to trigger autoretry. On next retry, the step tracker ensures we resume from the last completed step, not from the beginning.

### 8.3 recheck_fssai_expiry()

Beat schedule: daily at 06:00 IST (entry already in `config/settings/base.py`).

**Cost-controlled logic** — calls the Surepass API only when necessary:
1. First pass — flag vendors whose expiry is newly within 30 days:
   - Query: `Vendor.objects.filter(fssai_status='verified', fssai_expiry_date__lte=today+30days, fssai_expiry_warning_sent=False)`
   - For each: call `SurepassFSSAIClient.check_expiry()` (cheap endpoint)
   - If still active and ≤ 30 days to expiry: enqueue SMS warning; set `fssai_expiry_warning_sent=True`
   - If now expired: set `fssai_status=expired`
2. Second pass — handle already-past-expiry (no API call needed, use local date):
   - Query: `Vendor.objects.filter(fssai_status='verified', fssai_expiry_date__lt=today)`
   - Atomic update: `fssai_status=expired`
3. Process in batches of 50 to stay within Surepass rate limits

This approach means each vendor gets at most one warning SMS (not a daily SMS for 30 days).

### 8.4 auto_delist_missed_windows()

Beat schedule: daily. Add to `config/settings/base.py`.

Logic:
- Query `VendorCommunity.objects.filter(status='approved', missed_window_count__gte=models.F('delist_threshold'))`
- For each record: atomic update `status → suspended`
- Decrement `community.vendor_count` atomically (suspended vendors are no longer active)
- Enqueue SMS to vendor (via `sms` queue)
- Enqueue notification to community admin (via `notifications` queue)

---

## Section 9: Razorpay Webhook

### 9.1 Webhook Endpoint

Location: `apps/core/urls_webhooks.py` included in `config/urls.py` at `api/v1/webhooks/`. This is separate from the vendor-specific URL namespace so future webhook handlers (payment webhooks in split 05, etc.) can be added to the same namespace.

`POST /api/v1/webhooks/razorpay/`

This endpoint is **unauthenticated** (no JWT) but must verify the Razorpay signature before processing.

Signature verification:
- Read `X-Razorpay-Signature` from request headers
- Compute HMAC-SHA256 of the raw request body using `settings.RAZORPAY_WEBHOOK_SECRET`
- Compare using `hmac.compare_digest` (constant-time comparison prevents timing attacks)
- If mismatch: return 400 immediately

**Note:** Replay protection (timestamp checks, event ID deduplication) is not implemented for MVP. The `account.activated` handler is idempotent via `filter().update()`, so replays are harmless for this event. A code comment should note this as a future hardening item for split 05 when non-idempotent payment events are added.

Handling `account.activated` event:
- Parse `payload.account.entity.id` from the webhook JSON
- `Vendor.objects.filter(razorpay_account_id=account_id).update(razorpay_account_status='activated', bank_account_verified=True)`
- Enqueue SMS notification to vendor

Always return 200 to Razorpay for valid, verified webhooks.

---

## Section 10: Django Admin

### 10.1 VendorAdmin

Register `Vendor` in `apps/vendors/admin.py`:

- `list_display`: `display_name`, `user`, `fssai_status`, `razorpay_account_status`, `bank_account_verified`, `average_rating`, `is_new_seller`
- `list_filter`: `fssai_status`, `razorpay_account_status`
- `search_fields`: `display_name`, `user__phone`, `fssai_number`, `gstin`
- `readonly_fields`: `fssai_verified_at`, `razorpay_account_id`, `razorpay_onboarding_step`, `created_at`, `updated_at`

### 10.2 VendorCommunityAdmin

Register `VendorCommunity` as inline on VendorAdmin and/or standalone:

- `list_display`: `vendor`, `community`, `status`, `approved_by`, `approved_at`, `missed_window_count`, `delist_threshold`
- `list_filter`: `status`, `community`
- `readonly_fields`: `approved_by`, `approved_at`

---

## Section 11: URL Configuration

`apps/vendors/urls.py` (namespace `vendors`):

```
POST   vendors/register/                             → VendorRegistrationView
POST   vendors/<int:vendor_id>/documents/            → DocumentUploadView
POST   vendors/<int:vendor_id>/submit/               → VendorSubmitView
GET    vendors/<int:vendor_id>/status/               → VendorStatusView
GET    vendors/<int:vendor_id>/profile/              → VendorPublicProfileView
POST   vendors/<int:vendor_id>/approve/              → VendorApproveView
POST   vendors/<int:vendor_id>/reject/               → VendorRejectView

GET    communities/<slug:slug>/vendors/pending/      → CommunityPendingVendorsView
```

`apps/core/urls_webhooks.py` (separate namespace, included at `api/v1/webhooks/`):

```
POST   webhooks/razorpay/                            → RazorpayWebhookView
```

Include in `config/urls.py`:
```python
path('api/v1/', include('apps.vendors.urls', namespace='vendors')),
path('api/v1/', include('apps.core.urls_webhooks')),
```

---

## Section 12: Serializers

### 12.1 VendorRegistrationSerializer

Fields: `display_name`, `bio`, `logistics_tier`, `community_slug`, `category_hint`. `community_slug` is write-only and resolved to a `Community` object in `validate()`. Sets `is_food_seller=True` when `category_hint='food'`. Creation wrapped in `transaction.atomic()`.

### 12.2 DocumentUploadSerializer

Validates `document_type` (choices) and `file` (size → extension → magic bytes in `validate_file()`). Returns a `missing_fssai_number` warning in the response if `document_type=fssai_cert` but `fssai_number` is not yet set (task will not be triggered until the number is provided).

### 12.3 VendorStatusSerializer

Read-only. Computes `missing_documents` by checking which S3 keys are empty given the vendor's `is_food_seller` flag and `fssai_status`.

### 12.4 PendingVendorSerializer

Used by the admin pending queue endpoint. Adds `document_urls` field computed via `generate_document_presigned_url()`. Adds `fssai_warning` boolean (True if `fssai_status == 'failed'`).

### 12.5 VendorPublicProfileSerializer

Read-only. Exposes only: `vendor_id`, `display_name`, `bio`, `average_rating`, `is_new_seller`.

---

## Section 13: Environment Variables and Settings

New settings required:

```python
SUREPASS_TOKEN = env('SUREPASS_TOKEN', default=None)
RAZORPAY_WEBHOOK_SECRET = env('RAZORPAY_WEBHOOK_SECRET')
# RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET already set in split 01
```

Beat schedule additions in `config/settings/base.py`:

```python
'auto_delist_missed_windows': {
    'task': 'apps.vendors.tasks.auto_delist_missed_windows',
    'schedule': crontab(hour=6, minute=30, ...),  # slightly offset from recheck_fssai_expiry
},
```

---

## Section 14: Testing Strategy

Tests live in `apps/vendors/tests/`. Use pytest-django, factory_boy, and `unittest.mock`. Do NOT use `CELERY_TASK_ALWAYS_EAGER` — it's deprecated in Celery 5. Call task functions directly and mock service calls.

### Factories (`factories.py`)

```
VendorFactory         — creates Vendor with sane defaults
VendorCommunityFactory — creates VendorCommunity linked to VendorFactory + CommunityFactory
```

### test_models.py

- `is_new_seller` returns True when `completed_delivery_count < 5`
- `is_new_seller` returns True when `average_rating < 4.5` (even with 10 deliveries)
- `is_new_seller` returns False only when both conditions are satisfied
- `fssai_number` field rejects non-14-digit strings at model validation
- `VendorCommunity` unique constraint prevents duplicate (vendor, community) pairs

### test_views.py

- Registration creates `Vendor` + `VendorCommunity`; 409 on duplicate community
- Food vendor: `is_food_seller=True`; required_documents includes `fssai_cert`
- Document upload: rejects oversized file, wrong extension, mismatched magic bytes
- Document upload: accepts valid PDF, updates `govt_id_s3_key`
- Document upload for `fssai_cert` with valid `fssai_number` enqueues `verify_fssai.delay` (mock `.delay`)
- Submit: blocked when `govt_id_s3_key` missing; blocked when food seller without `fssai_cert`
- Submit: blocked when `fssai_status=failed`
- Admin approve: creates `UserRole(vendor)`, increments `vendor_count`, enqueues `create_razorpay_linked_account.delay` on first approval only
- Admin approve: blocked with 400 when `fssai_status=failed` and no override
- Admin reject: decrements `vendor_count` when vendor was previously approved
- Approve/reject: 403 when admin tries to approve vendor for a community they don't admin

### test_tasks.py

- `verify_fssai`: terminal state guard — does not call API when `fssai_status=verified`
- `verify_fssai`: terminal state guard — does not call API when `fssai_status=failed`
- `verify_fssai`: updates all fields on `status=active` response
- `verify_fssai`: sets `fssai_status=failed` on expired/cancelled/suspended response
- `verify_fssai`: sets `fssai_status=failed` on `FSSAIVerificationError` (does NOT retry)
- `verify_fssai`: re-raises `TransientAPIError` (triggers autoretry)
- `create_razorpay_linked_account`: terminal state guard when `razorpay_onboarding_step=submitted`
- `create_razorpay_linked_account`: atomic claim prevents concurrent duplicate execution
- `create_razorpay_linked_account`: resumes from `account_created` without re-calling create endpoint
- `auto_delist_missed_windows`: suspends vendors at threshold; decrements `vendor_count`
- `recheck_fssai_expiry`: only calls API for vendors with `fssai_expiry_warning_sent=False`
- `recheck_fssai_expiry`: sets `fssai_status=expired` for past-expiry via date comparison (no API)

### test_services.py

- `SurepassFSSAIClient.verify_fssai`: raises `FSSAIVerificationError` on 404
- `SurepassFSSAIClient.verify_fssai`: raises `TransientAPIError` on 500
- `SurepassFSSAIClient.verify_fssai`: normalizes response to standard dict shape
- `RazorpayWebhookView`: rejects requests with invalid HMAC signature
- `RazorpayWebhookView`: accepts valid signature and updates vendor on `account.activated`

---

## Implementation Sequence

Build in this order to respect dependencies:

1. **Models + migration** (Section 1) — everything else depends on these
2. **Custom permissions + exceptions** (Section 2) — needed by views and tasks
3. **FSSAI service** (Section 3) — needed by Celery tasks
4. **Razorpay service** (Section 4) — needed by Celery tasks
5. **S3 upload helpers** (Section 5) — needed by views
6. **Serializers** (Section 12) — needed by views
7. **Vendor registration + document views** (Section 6) — vendor-facing endpoints
8. **Admin approval views** (Section 7) — community admin endpoints
9. **Celery tasks** (Section 8) — async processing
10. **Razorpay webhook** (Section 9) — payment activation
11. **URL configuration** (Section 11) — wire everything
12. **Django Admin** (Section 10) — ops tooling
13. **Beat schedule update** (Section 13) — cron tasks
