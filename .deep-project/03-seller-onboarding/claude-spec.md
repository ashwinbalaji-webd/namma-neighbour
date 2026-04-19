# Complete Specification: 03-Seller Onboarding

## Purpose

Enable vendors to self-register on NammaNeighbor with full KYB (Know Your Business) verification — including FSSAI/GST checks, Razorpay Linked Account creation, and community admin approval workflow. This is the supply-side trust gate. A vendor operates across one or more communities, with a single global profile and per-community approvals.

---

## Dependencies

- **01-foundation** — User model, S3 (DocumentStorage / MediaStorage), Celery queues, JWT, TimestampedModel, custom exception handler
- **02-community-onboarding** — Community model (vendor must belong to at least one community)

---

## Architecture: Multi-Community Vendor Model

A single `Vendor` record is created per user. Vendor-community relationships are managed via a `VendorCommunity` join table. Each community admin independently approves/rejects the vendor for their community.

- **One Vendor profile** → global bio, display name, KYB documents, Razorpay account
- **Many VendorCommunity records** → per-community status, approval metadata, delist tracking
- **JWT scope** → `active_community` only (same as residents). Vendor switches community context by refreshing JWT.
- **Notifications** → global (vendor receives order notifications regardless of which community JWT is active — post-MVP concern, noted for notification engine)

---

## Data Models

### Vendor

```
Vendor
  user                    OneToOneField(User)
  display_name            CharField(max_length=150)
  bio                     TextField(blank=True)
  logistics_tier          CharField(choices=LogisticsTier) — tier_a (self-delivery) | tier_b (NammaNeighbor pickup)

  # KYB Documents (S3 keys, not FileField)
  govt_id_s3_key          CharField(max_length=500, blank=True)
  bank_proof_s3_key       CharField(max_length=500, blank=True)

  # FSSAI
  fssai_number            CharField(max_length=14, blank=True)
  fssai_status            CharField(choices=FSSAIStatus) — not_applicable | pending | verified | expired | failed
  fssai_cert_s3_key       CharField(max_length=500, blank=True)
  fssai_verified_at       DateTimeField(null=True)
  fssai_expiry_date       DateField(null=True)
  fssai_business_name     CharField(max_length=200, blank=True)
  fssai_authorized_categories  JSONField(default=list, blank=True)  ← stored for future product-category matching

  # GST (optional for MVP)
  gstin                   CharField(max_length=15, blank=True)
  gst_cert_s3_key         CharField(max_length=500, blank=True)

  # Razorpay Linked Account (vendor-level, created once on first community approval)
  razorpay_account_id     CharField(max_length=100, blank=True)
  razorpay_account_status CharField(max_length=20, blank=True)  — pending | under_review | activated | rejected
  bank_account_verified   BooleanField(default=False)

  # Performance (aggregated across all communities)
  completed_delivery_count     PositiveIntegerField(default=0)
  average_rating               DecimalField(max_digits=3, decimal_places=2, default=0.00)

  # Derived
  is_new_seller → True if completed_delivery_count < 5
```

**Note:** `missed_drop_window_count` and `delist_threshold` move to `VendorCommunity` (per-community tracking).

### VendorCommunity

```
VendorCommunity
  vendor              ForeignKey(Vendor, on_delete=CASCADE, related_name='community_memberships')
  community           ForeignKey(Community, on_delete=PROTECT, related_name='vendor_memberships')
  status              CharField(choices=VendorCommunityStatus) — pending_review | approved | rejected | suspended
  approved_by         ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)
  approved_at         DateTimeField(null=True, blank=True)
  rejection_reason    TextField(blank=True)
  delist_threshold    PositiveIntegerField(default=2)   ← admin-configurable per community
  missed_window_count PositiveIntegerField(default=0)   ← per-community miss tracking

  unique_together: (vendor, community)
```

### Choice Enums

- `LogisticsTier`: `tier_a` (self-delivery), `tier_b` (NammaNeighbor pickup)
- `FSSAIStatus`: `not_applicable`, `pending`, `verified`, `expired`, `failed`
- `VendorCommunityStatus`: `pending_review`, `approved`, `rejected`, `suspended`

---

## API Endpoints

### 1. POST /api/v1/vendors/register/
**Auth:** Any authenticated user  
**Purpose:** Create a new Vendor in draft state and register them for a community

Payload:
```json
{
  "display_name": "Radha's Organic Kitchen",
  "bio": "Home-cooked South Indian meals",
  "logistics_tier": "tier_b",
  "community_slug": "prestige-oasis",
  "category_hint": "food"
}
```

Behavior:
- Creates `Vendor` (if first registration) and `VendorCommunity` with `status=pending_review` (starts in pending so the vendor can upload docs)
- Returns `vendor_id`, `vendor_community_id`, and list of required documents based on `category_hint`
- If vendor already exists (re-registering for another community): creates only a new `VendorCommunity` record
- If vendor already has a `VendorCommunity` for this community: 409 Conflict

### 2. POST /api/v1/vendors/{vendor_id}/documents/
**Auth:** IsVendorOwner  
**Purpose:** Upload KYB document

Payload: `multipart/form-data`  
Fields: `document_type` (`govt_id` | `fssai_cert` | `bank_proof` | `gst_cert`), `file`

Behavior:
- **3-layer file validation**: size (≤10MB) → extension (PDF/JPG/JPEG/PNG) → magic bytes
- Uploads to S3: `documents/vendors/{vendor_id}/{document_type}/{uuid4}.{ext}`
- Updates corresponding `*_s3_key` field on Vendor model
- If `document_type == fssai_cert` AND vendor has `fssai_number`: triggers `verify_fssai.delay(vendor_id)`

### 3. POST /api/v1/vendors/{vendor_id}/submit/
**Auth:** IsVendorOwner  
**Purpose:** Submit vendor application to a community for admin review

Payload: `{"community_slug": "prestige-oasis"}`

Behavior:
- Validates required documents uploaded: `govt_id` + `bank_proof` always; `fssai_cert` if `category_hint=food`
- Validates `fssai_status` is not `failed` (blocks submit if FSSAI failed)
- Transitions `VendorCommunity.status`: any non-approved state → `pending_review`
- Notifies community admin (push notification + SMS)

### 4. GET /api/v1/vendors/{vendor_id}/status/
**Auth:** IsVendorOwner  
**Purpose:** Get vendor application status across all communities

Returns current `VendorCommunity` statuses, missing required documents, FSSAI verification result.

### 5. GET /api/v1/communities/{slug}/vendors/pending/
**Auth:** IsCommunityAdmin  
**Purpose:** Admin approval queue

Lists all `VendorCommunity` records with `status=pending_review` for the community. Includes presigned S3 URLs (TTL=3600s, signature_version=s3v4) for document review. Includes FSSAI warning if `fssai_status=failed`.

### 6. POST /api/v1/vendors/{vendor_id}/approve/
**Auth:** IsCommunityAdmin  
**Purpose:** Approve vendor for a community

Payload: `{"community_slug": "prestige-oasis"}`

Behavior:
- Validates it's a pending_review record in the admin's community
- Transitions `VendorCommunity.status` → `approved`; sets `approved_by`, `approved_at`
- If this is the vendor's **first approval** across all communities: triggers `create_razorpay_linked_account.delay(vendor_id)`
- Increments `community.vendor_count`
- Notifies vendor via SMS
- **Override flag**: If `fssai_status=failed`, admin must pass `{"override_fssai_warning": true}` to proceed (logged in admin action)

### 7. POST /api/v1/vendors/{vendor_id}/reject/
**Auth:** IsCommunityAdmin  
**Purpose:** Reject vendor for a community

Payload: `{"community_slug": "prestige-oasis", "reason": "FSSAI certificate expired"}`

Behavior:
- Transitions `VendorCommunity.status` → `rejected`; stores `rejection_reason`
- Vendor can update documents and re-submit (does NOT create a new record)
- Notifies vendor via SMS with the rejection reason

### 8. GET /api/v1/vendors/{vendor_id}/profile/
**Auth:** IsResidentOfCommunity  
**Purpose:** Public vendor profile

Returns: `display_name`, `bio`, `average_rating`, `is_new_seller` badge, product categories. Does **not** expose KYB documents, bank details, or Razorpay data.

---

## Permissions

- `IsVendorOwner`: object-level — `obj.user_id == request.user.id`
- `IsCommunityAdmin`: from existing `apps/core/permissions.py`
- `IsResidentOfCommunity`: from existing `apps/core/permissions.py`

---

## Celery Tasks

### `verify_fssai(vendor_id)`

Queue: `kyc`  
Retries: `autoretry_for=(Timeout, ConnectionError, TransientAPIError)`, `max_retries=5`, `retry_backoff=True`, `retry_jitter=True`

Flow:
1. Guard clause: if `fssai_status in ('verified', 'failed')` → return early (never re-call paid API)
2. Call `SurepassFSSAIClient.verify_fssai(vendor.fssai_number)` → POST to `/fssai/fssai-full-details`
3. On `status=active`: atomic update — `fssai_status=verified`, `fssai_verified_at=now()`, `fssai_expiry_date`, `fssai_business_name`, `fssai_authorized_categories`
4. On `status=expired|cancelled|suspended`: atomic update — `fssai_status=failed`
5. On 400/404: permanent failure (do not retry) — set `fssai_status=failed`
6. On 5xx/timeout: transient failure → autoretry; after max retries, set `fssai_status=pending` (manual ops review fallback)

### `create_razorpay_linked_account(vendor_id)`

Queue: `payments`  
Retries: `autoretry_for=(Timeout, ConnectionError, TransientAPIError)`, `max_retries=3`

Flow:
1. Guard clause: if `razorpay_account_id` already set → return early (idempotent)
2. `POST /v2/accounts` with `type=route`, vendor business info, `reference_id=str(vendor.pk)`
3. Store `razorpay_account_id`, set `razorpay_account_status=pending`
4. `POST /v2/accounts/{id}/stakeholders` — upload KYC info
5. `PATCH /v2/accounts/{id}` — submit for Razorpay review
6. Bank verification handled by `account.activated` webhook (do not poll)

### `recheck_fssai_expiry()`

Beat: daily at 06:00 IST (already in Beat schedule)  
Uses lighter Surepass endpoint `/fssai/fssai-expiry-check`  
- Vendors where `fssai_expiry_date` within 30 days → send SMS warning + re-run full verify
- Vendors where `fssai_expiry_date` < today → set `fssai_status=expired`

### `auto_delist_missed_windows()`

Beat: daily  
Finds `VendorCommunity` records where `missed_window_count >= delist_threshold`  
Transitions `VendorCommunity.status → suspended`  
Notifies vendor via SMS  
Notifies community admin

---

## Razorpay Webhook: `account.activated`

Endpoint: `POST /api/v1/webhooks/razorpay/`  
Verification: HMAC-SHA256 of raw request body using `RAZORPAY_WEBHOOK_SECRET`

On `account.activated` event:
- Atomic update: `razorpay_account_status=activated`, `bank_account_verified=True`
- Notifies vendor

---

## FSSAI Service: `apps/vendors/services/fssai.py`

`SurepassFSSAIClient`:
- `verify_fssai(license_number)` → POST to `/fssai/fssai-full-details`, returns normalized dict
- `check_expiry(license_number)` → POST to `/fssai/fssai-expiry-check` (cheaper, used for cron)

Response normalization:
```python
{
  "status": "active"|"expired"|"cancelled"|"suspended",
  "business_name": str,
  "expiry_date": date,
  "authorized_categories": list[str],
}
```

Error handling:
- 400/404 → raise `PermanentAPIError` (not retried)
- 429/5xx → raise `TransientAPIError` (retried by Celery)
- Timeout → retry

---

## S3 Document Storage

Key pattern: `documents/vendors/{vendor_id}/{document_type}/{uuid4}.{ext}`

File validation (3 layers in order):
1. Size: ≤ 10MB
2. Extension: `.pdf`, `.jpg`, `.jpeg`, `.png`
3. Magic bytes: `%PDF`, `FF D8 FF` (JPEG), `89 50 4E 47` (PNG)

Presigned URL generation:
- `signature_version="s3v4"` (required for ap-south-1)
- `ExpiresIn=3600`

---

## Django Admin

Registered models:
- `Vendor`: list_display = [display_name, status (via VendorCommunity), fssai_status, razorpay_account_status, average_rating], filters = [fssai_status, razorpay_account_status], actions = [approve, reject, suspend, reinstate]
- `VendorCommunity`: list_display = [vendor, community, status, approved_by, approved_at, missed_window_count, delist_threshold]

---

## Custom Exceptions (apps/core/exceptions.py additions)

- `ExternalAPIError(503)` — base for third-party API failures
- `RazorpayError(402)` — Razorpay-specific
- `FSSAIVerificationError(400)` — FSSAI permanent failure

---

## Environment Variables

```
SUREPASS_TOKEN
RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
```

---

## Acceptance Criteria

1. Vendor submits registration → application appears in community admin approval queue
2. FSSAI verification Celery task runs within 60s of document upload and updates `fssai_status`
3. First community approval triggers Razorpay Linked Account creation (only once, idempotent)
4. Vendor with no `approved` VendorCommunity record cannot create product listings (enforced in split 04)
5. `is_new_seller` returns True for vendor with < 5 completed deliveries
6. `auto_delist_missed_windows` cron correctly suspends VendorCommunity records at or above `delist_threshold`
7. Document presigned URLs expire after 1 hour
8. Rejecting a vendor stores rejection reason on VendorCommunity, vendor can re-submit same record
9. `recheck_fssai_expiry` sends SMS warning 30 days before FSSAI expiry
10. Approving vendor with `fssai_status=FAILED` requires `override_fssai_warning=true` (warning shown in admin UI)
11. File upload rejects non-PDF/JPG/PNG at magic-byte level
12. `account.activated` webhook sets `bank_account_verified=True`
13. Multi-community: vendor can be approved in community A and pending in community B simultaneously
14. Razorpay account is vendor-level (not per-community) — created once on first approval

---

## Out of Scope for MVP

- `VendorCommunityProfile` (community-specific bio overrides)
- Tiered penalty system (probation status, reliability badges)
- 90-day miss reset clock
- Product-to-FSSAI-category matching (field stored, matching logic deferred)
- IDfy as alternative KYC provider (Surepass for MVP)
