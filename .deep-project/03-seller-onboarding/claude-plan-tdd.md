# TDD Plan: 03-Seller Onboarding

## Testing Stack (Existing Project)

- Framework: pytest-django
- Factories: factory_boy (`apps/vendors/tests/factories.py`)
- Mocking: `unittest.mock.patch`
- Time travel: `freezegun`
- Task testing: call function directly (no `CELERY_TASK_ALWAYS_EAGER`); mock `.delay()` in view tests
- DB access: `@pytest.mark.django_db` on test functions/classes
- Auth: `APIClient.force_authenticate(user=user)` or Bearer token

---

## Section 1: App Scaffold and Models

### 1.3 Vendor Model

**Write these tests first (`test_models.py`):**

```
# Test: is_new_seller returns True when completed_delivery_count < 5
# Test: is_new_seller returns True when average_rating < 4.5 (even with ≥5 deliveries)
# Test: is_new_seller returns False only when count >= 5 AND rating >= 4.5
# Test: fssai_number field rejects non-14-digit strings (model full_clean validation)
# Test: fssai_number field rejects strings with non-digit characters
# Test: fssai_number field accepts valid 14-digit string
# Test: Vendor.user is OneToOne — creating second Vendor for same user raises IntegrityError
```

**Factories:**

```python
# VendorFactory:
#   user = SubFactory(UserFactory)
#   display_name = Faker('company')
#   logistics_tier = LogisticsTier.TIER_B
#   is_food_seller = False
#   fssai_status = FSSAIStatus.NOT_APPLICABLE
#   razorpay_onboarding_step = ''
```

### 1.4 VendorCommunity Model

```
# Test: (vendor, community) unique constraint raises IntegrityError on duplicate
# Test: VendorCommunity with status=approved can be queried by (community, status) index (no exception, not a perf test)
```

**Factories:**

```python
# VendorCommunityFactory:
#   vendor = SubFactory(VendorFactory)
#   community = SubFactory(CommunityFactory)
#   status = VendorCommunityStatus.PENDING_REVIEW
#   delist_threshold = 2
#   missed_window_count = 0
```

---

## Section 2: Permissions and Custom Exceptions

### 2.1 IsVendorOwner

```
# Test: IsVendorOwner.has_object_permission returns True when request.user == vendor.user
# Test: IsVendorOwner.has_object_permission returns False when request.user != vendor.user
# Test: Document upload endpoint returns 403 when authenticated user does not own the vendor
```

### 2.2 Custom Exceptions

```
# Test: ExternalAPIError serializes to {"error": ..., "detail": ...} via custom exception handler
# Test: TransientAPIError is a subclass of ExternalAPIError
# Test: FSSAIVerificationError returns HTTP 400
# Test: RazorpayError returns HTTP 402
```

---

## Section 3: FSSAI Service

```
# Test: verify_fssai returns normalized dict with status/business_name/expiry_date/authorized_categories
# Test: verify_fssai raises FSSAIVerificationError on HTTP 400 (mock requests.post)
# Test: verify_fssai raises FSSAIVerificationError on HTTP 404
# Test: verify_fssai raises TransientAPIError on HTTP 500
# Test: verify_fssai raises TransientAPIError on HTTP 429
# Test: verify_fssai raises TransientAPIError on requests.Timeout
# Test: check_expiry calls the cheaper /fssai-expiry-check endpoint (assert correct URL in mock)
# Test: check_expiry returns normalized dict with status and expiry_date
```

---

## Section 4: Razorpay Service

```
# Test: create_linked_account calls POST /v2/accounts with type='route' and reference_id=str(vendor.pk)
# Test: create_linked_account raises RazorpayError on HTTP 400
# Test: create_linked_account raises TransientAPIError on HTTP 500
# Test: add_stakeholder calls the correct URL with account_id
# Test: submit_for_review sends PATCH to the correct URL
```

---

## Section 5: S3 Document Upload Logic

### 5.1 File Validation

```
# Test: validate_file raises ValidationError for file > 5MB
# Test: validate_file raises ValidationError for .exe extension
# Test: validate_file raises ValidationError for file with PDF extension but JPEG magic bytes
# Test: validate_file raises ValidationError for file with JPEG extension but PDF magic bytes
# Test: validate_file accepts valid PDF (correct extension + %PDF magic bytes)
# Test: validate_file accepts valid JPEG (correct extension + FF D8 FF magic bytes)
# Test: validate_file accepts valid PNG (correct extension + 89 50 4E 47 magic bytes)
```

### 5.2 S3 Upload

```
# Test: S3 key follows pattern documents/vendors/{vendor_id}/{document_type}/{uuid}.{ext}
# Test: UUID in key is unique across two uploads of the same file (no overwrite)
# Test: After upload, vendor.*_s3_key is updated in database
```

### 5.3 Presigned URL Generation

```
# Test: generate_document_presigned_url returns a URL string
# Test: generate_document_presigned_url uses signature_version=s3v4 (inspect boto3 client call args)
# Test: generate_document_presigned_url uses ExpiresIn=3600
```

---

## Section 6: API Views — Vendor Registration and Document Upload

### 6.1 POST /api/v1/vendors/register/

```
# Test: Creates Vendor and VendorCommunity on success; returns vendor_id and vendor_community_id
# Test: Sets is_food_seller=True when category_hint='food'
# Test: required_documents includes fssai_cert when is_food_seller=True
# Test: required_documents does NOT include fssai_cert when is_food_seller=False
# Test: Returns 409 when VendorCommunity already exists for (vendor, community)
# Test: Returns 404 when community_slug does not exist
# Test: Returns 401 when not authenticated
# Test: Vendor is NOT created twice if user already has a Vendor — reuses existing
# Test: Vendor and VendorCommunity are both created (or neither) — transaction atomicity
```

### 6.2 POST /api/v1/vendors/{vendor_id}/documents/

```
# Test: Returns 403 when authenticated user does not own vendor
# Test: Rejects file > 5MB with 400
# Test: Rejects invalid file type with 400
# Test: Accepts valid PDF, updates govt_id_s3_key
# Test: Accepts valid JPEG, updates bank_proof_s3_key
# Test: Uploading fssai_cert with valid fssai_number → verify_fssai.delay called once (mock .delay)
# Test: Uploading fssai_cert without fssai_number → verify_fssai.delay NOT called; response warns
# Test: Returns 400 for invalid document_type value
```

### 6.3 POST /api/v1/vendors/{vendor_id}/submit/

```
# Test: Returns 400 when govt_id_s3_key is empty
# Test: Returns 400 when bank_proof_s3_key is empty
# Test: Returns 400 when is_food_seller=True and fssai_cert_s3_key is empty
# Test: Returns 400 when fssai_status=failed
# Test: Transitions VendorCommunity.status → pending_review on success
# Test: Returns 404 when VendorCommunity not found for given community_slug
# Test: Returns 403 when user does not own vendor
```

### 6.4 GET /api/v1/vendors/{vendor_id}/status/

```
# Test: Returns fssai_status and fssai_expiry_date
# Test: missing_documents is empty when all required docs are uploaded
# Test: missing_documents includes 'fssai_cert' when food seller missing cert
# Test: community_statuses reflects all VendorCommunity records for the vendor
# Test: Returns 403 when user does not own vendor
```

---

## Section 7: API Views — Community Admin Workflow

### 7.1 GET /api/v1/communities/{slug}/vendors/pending/

```
# Test: Returns only vendors with status=pending_review in the admin's community
# Test: Does not return vendors from other communities
# Test: Response includes presigned URL for each uploaded document (non-empty s3_key)
# Test: Response includes fssai_warning=True when vendor.fssai_status=failed
# Test: Response is paginated (page_size=10; 11th vendor not in first page)
# Test: Returns 403 when user is not a community admin
```

### 7.2 POST /api/v1/vendors/{vendor_id}/approve/

```
# Test: Transitions VendorCommunity.status → approved
# Test: Sets approved_by and approved_at
# Test: Increments community.vendor_count by 1
# Test: Creates UserRole(role='vendor', community=community) for vendor.user
# Test: UserRole not duplicated if vendor approved in same community twice (idempotent)
# Test: Enqueues create_razorpay_linked_account.delay on first approval (razorpay_onboarding_step='')
# Test: Does NOT enqueue create_razorpay_linked_account when already onboarded (razorpay_onboarding_step='submitted')
# Test: Returns 400 when fssai_status=failed and override_fssai_warning=False
# Test: Proceeds when fssai_status=failed and override_fssai_warning=True
# Test: Returns 403 when admin tries to approve vendor for a community they don't admin (community_slug mismatch)
# Test: Returns 404 when VendorCommunity not in pending_review
```

### 7.3 POST /api/v1/vendors/{vendor_id}/reject/

```
# Test: Transitions VendorCommunity.status → rejected
# Test: Stores rejection_reason
# Test: Decrements community.vendor_count when vendor was previously approved
# Test: Does NOT decrement vendor_count when vendor was in pending_review (not yet counted)
# Test: Returns 403 when admin tries to reject for community they don't admin
# Test: Vendor can re-submit after rejection (status returns to pending_review on next submit)
```

### 7.4 GET /api/v1/vendors/{vendor_id}/profile/

```
# Test: Returns display_name, bio, average_rating, is_new_seller
# Test: Does NOT return fssai_number, razorpay_account_id, *_s3_key fields
# Test: Returns 403 when user is not a resident of the community
```

---

## Section 8: Celery Tasks

### 8.1 verify_fssai

```
# Test: Returns immediately (no API call) when fssai_status=verified
# Test: Returns immediately (no API call) when fssai_status=failed
# Test: Updates fssai_status=verified, fssai_verified_at, fssai_expiry_date, fssai_business_name when API returns active
# Test: Resets fssai_expiry_warning_sent=False when re-verified after expiry
# Test: Updates fssai_status=failed when API returns expired
# Test: Updates fssai_status=failed when API returns cancelled
# Test: Updates fssai_status=failed when API returns suspended
# Test: Updates fssai_status=failed on FSSAIVerificationError; does NOT raise (no Celery retry)
# Test: Re-raises TransientAPIError (Celery will retry)
# Test: fssai_authorized_categories is populated from API response authorized_categories list
```

### 8.2 create_razorpay_linked_account

```
# Test: Returns immediately when razorpay_onboarding_step=submitted (terminal guard)
# Test: Atomic claim prevents concurrent duplicate: second concurrent call returns without calling API
# Test: When razorpay_onboarding_step='', calls create_linked_account, updates razorpay_account_id and step to 'account_created'
# Test: When razorpay_onboarding_step='account_created', skips create_linked_account, calls add_stakeholder
# Test: When razorpay_onboarding_step='stakeholder_added', skips to submit_for_review only
# Test: After submit_for_review, razorpay_onboarding_step='submitted'
# Test: RazorpayError sets razorpay_account_status=rejected; does NOT raise (no retry)
# Test: TransientAPIError re-raises; step tracker allows retry to resume from last completed step
```

### 8.3 recheck_fssai_expiry

```
# Test: Calls check_expiry only for vendors with fssai_expiry_warning_sent=False
# Test: Vendors with fssai_expiry_warning_sent=True are skipped (no API call)
# Test: Sets fssai_expiry_warning_sent=True after warning (mock SMS task enqueue)
# Test: Sets fssai_status=expired via date comparison for past-expiry vendors (no API call needed)
# Test: Uses freezegun to simulate "today" for date comparisons
# Test: Processes vendors in batches of 50 (mock check_expiry, assert call_count matches batch logic)
```

### 8.4 auto_delist_missed_windows

```
# Test: Suspends VendorCommunity when missed_window_count >= delist_threshold
# Test: Does not suspend when missed_window_count < delist_threshold
# Test: Decrements community.vendor_count for each suspended record
# Test: Enqueues SMS task for vendor notification (mock sms task)
# Test: Enqueues notification task for community admin (mock notification task)
# Test: Only processes records with status=approved (not already suspended)
```

---

## Section 9: Razorpay Webhook

```
# Test: Rejects request with missing X-Razorpay-Signature with 400
# Test: Rejects request with incorrect HMAC signature with 400
# Test: Accepts valid signature and returns 200
# Test: On account.activated event: sets razorpay_account_status=activated and bank_account_verified=True
# Test: On account.activated for unknown account_id: returns 200 without error (defensive)
# Test: account.activated is idempotent: running twice does not error
# Test: Uses hmac.compare_digest (constant-time) not == for signature comparison
```

---

## Section 10: Django Admin

```
# Test: VendorAdmin is registered in admin site
# Test: VendorCommunityAdmin list_display renders without error (use AdminClient)
# Test: Vendor search by fssai_number returns correct results
```

---

## Section 14: Integration Tests (Multi-Community Scenarios)

```
# Test: Vendor approved in community A, pending in community B simultaneously — both VendorCommunity records independent
# Test: Vendor rejected in community A can still be approved in community B
# Test: Razorpay account created only once even when approved in two communities back-to-back
# Test: vendor_count correct across approve → reject → re-approve cycle
# Test: UserRole created for community A on first approval; second approval in community B creates separate UserRole
```
