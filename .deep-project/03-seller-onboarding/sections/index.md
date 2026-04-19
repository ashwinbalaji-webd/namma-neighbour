<!-- PROJECT_CONFIG
runtime: python-uv
test_command: uv run pytest
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-app-scaffold-models
section-02-permissions-exceptions
section-03-fssai-service
section-04-razorpay-service
section-05-s3-document-upload
section-06-serializers
section-07-api-views-registration
section-08-api-views-admin-workflow
section-09-celery-tasks
section-10-razorpay-webhook
section-11-django-admin
section-12-url-configuration
section-13-env-settings
section-14-integration-tests
END_MANIFEST -->

# Implementation Sections Index: 03-Seller Onboarding

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable |
|---------|------------|--------|----------------|
| section-01-app-scaffold-models | - | all | No (foundation) |
| section-02-permissions-exceptions | 01 | 03, 04, 06, 07, 08 | Yes |
| section-03-fssai-service | 01, 02 | 09 | Yes |
| section-04-razorpay-service | 01, 02 | 09, 10 | Yes |
| section-05-s3-document-upload | 01 | 06, 07 | Yes |
| section-06-serializers | 01, 02, 05 | 07, 08 | No |
| section-07-api-views-registration | 01, 02, 05, 06 | 12 | Yes |
| section-08-api-views-admin-workflow | 01, 02, 05, 06 | 12 | Yes |
| section-09-celery-tasks | 01, 02, 03, 04 | 12 | No |
| section-10-razorpay-webhook | 01, 04 | 12 | Yes |
| section-11-django-admin | 01 | 12 | Yes |
| section-12-url-configuration | 07, 08, 09, 10 | 14 | No |
| section-13-env-settings | 01 | 09 | Yes |
| section-14-integration-tests | all | - | No |

## Execution Order

1. **section-01-app-scaffold-models** — foundation (no dependencies)
2. **section-02-permissions-exceptions, section-05-s3-document-upload, section-11-django-admin, section-13-env-settings** (parallel after 01)
3. **section-03-fssai-service, section-04-razorpay-service** (parallel after 01+02)
4. **section-06-serializers** (after 01, 02, 05)
5. **section-07-api-views-registration, section-08-api-views-admin-workflow, section-09-celery-tasks, section-10-razorpay-webhook** (parallel after deps)
6. **section-12-url-configuration** (after 07, 08, 09, 10)
7. **section-14-integration-tests** (after all)

## Section Summaries

### section-01-app-scaffold-models
Create `apps/vendors/` app, register in INSTALLED_APPS. Define `LogisticsTier`, `FSSAIStatus`, `VendorCommunityStatus` TextChoices. Implement `Vendor` model (TimestampedModel, all KYB/FSSAI/Razorpay fields, `is_new_seller` property) and `VendorCommunity` model (join table with per-community approval state and penalty tracking, unique constraint on vendor+community, composite DB index). Write and run migration.

**Tests:** `is_new_seller` logic, `fssai_number` regex validation, `VendorCommunity` unique constraint, factories.

### section-02-permissions-exceptions
Add `IsVendorOwner` object-level permission to `apps/core/permissions.py`. Add custom exception hierarchy to `apps/core/exceptions.py`: `ExternalAPIError` (503) → `TransientAPIError` (503, retriable) / `PermanentAPIError` (503, non-retriable) → `RazorpayError` (402) / `FSSAIVerificationError` (400). Register custom exception handler.

**Tests:** `IsVendorOwner` allows/denies correctly; each exception class returns correct HTTP status.

### section-03-fssai-service
Implement `SurepassFSSAIClient` in `apps/vendors/services/fssai.py`. Two methods: `verify_fssai()` (full details, calls `/fssai/fssai-full-details`) and `check_expiry()` (cheap daily cron endpoint). Error translation: 400/404 → `FSSAIVerificationError`, 429/5xx/timeout → `TransientAPIError`. Normalize response to `{status, business_name, expiry_date, authorized_categories}`.

**Tests:** successful verification, all HTTP error cases, timeout, normalized response shape.

### section-04-razorpay-service
Implement `RazorpayClient` in `apps/vendors/services/razorpay.py`. Three methods: `create_linked_account(vendor)` (POST /v2/accounts, type=route, reference_id=str(vendor.pk)), `add_stakeholder(account_id, vendor)` (POST /v2/accounts/{id}/stakeholders), `submit_for_review(account_id)` (PATCH /v2/accounts/{id}). Error translation: 400/409 → `RazorpayError`, 429/5xx/timeout → `TransientAPIError`. HTTP Basic Auth using `RAZORPAY_KEY_ID` + `RAZORPAY_KEY_SECRET`.

**Tests:** correct URL/method for each call, error translation cases.

### section-05-s3-document-upload
Implement 3-layer file validation (size ≤5MB → extension allowlist → magic bytes via `filetype`/`python-magic`) as `validate_document_file()` in `apps/vendors/services/storage.py`. S3 upload generates key `documents/vendors/{vendor_id}/{document_type}/{uuid4}.{ext}`, uploads via `DocumentStorage` from `apps/core/storage.py`, updates vendor `*_s3_key` field. Add `generate_document_presigned_url(s3_key)` helper (boto3 directly, `s3v4`, `ExpiresIn=3600`, `region_name=ap-south-1`).

**Tests:** validation rejects oversized/wrong-extension/magic-byte-mismatch files; S3 key pattern; presigned URL uses correct params.

### section-06-serializers
All DRF serializers for the vendor app in `apps/vendors/serializers.py`:
- `VendorRegistrationSerializer` — validates fields, resolves `community_slug` to Community, sets `is_food_seller`, wraps creation in `transaction.atomic()`
- `DocumentUploadSerializer` — validates `document_type` choice + calls `validate_document_file()`, returns `missing_fssai_number` warning
- `VendorStatusSerializer` — read-only, computes `missing_documents` and `community_statuses`
- `PendingVendorSerializer` — adds `document_urls` (presigned URLs) and `fssai_warning` flag
- `VendorPublicProfileSerializer` — exposes only public fields, no KYB/bank/Razorpay data

### section-07-api-views-registration
Four vendor-side views in `apps/vendors/views.py`:
- `VendorRegistrationView` (POST /register/) — creates Vendor+VendorCommunity atomically, returns required_documents list
- `DocumentUploadView` (POST /{vendor_id}/documents/) — `IsVendorOwner`, 3-layer validation, S3 upload, triggers `verify_fssai.delay` when fssai_cert uploaded with valid fssai_number
- `VendorSubmitView` (POST /{vendor_id}/submit/) — `IsVendorOwner`, validates required docs, blocks if `fssai_status=failed`, transitions to `pending_review`
- `VendorStatusView` (GET /{vendor_id}/status/) — `IsVendorOwner`, returns status + missing docs + community_statuses

**Tests:** all happy paths plus 401/403/404/409 error cases; `verify_fssai.delay` mocked.

### section-08-api-views-admin-workflow
Four admin views in `apps/vendors/views.py`:
- `CommunityPendingVendorsView` (GET /communities/{slug}/vendors/pending/) — `IsCommunityAdmin`, paginated (page_size=10), includes presigned doc URLs + `fssai_warning`
- `VendorApproveView` (POST /{vendor_id}/approve/) — `IsCommunityAdmin`, community cross-check, FSSAI guard, atomic approval, `community.vendor_count` increment, `UserRole` creation, `create_razorpay_linked_account.delay` on first approval
- `VendorRejectView` (POST /{vendor_id}/reject/) — `IsCommunityAdmin`, community cross-check, atomic rejection, `vendor_count` decrement if was approved
- `VendorPublicProfileView` (GET /{vendor_id}/profile/) — `IsResidentOfCommunity`, public fields only

**Tests:** FSSAI guard, override_fssai_warning, vendor_count atomicity, UserRole idempotency, community cross-check 403.

### section-09-celery-tasks
Four tasks in `apps/vendors/tasks.py`:
- `verify_fssai(vendor_id)` — queue=kyc, autoretry on TransientAPIError, terminal state guard, updates fssai_status/expiry/warning fields, resets `fssai_expiry_warning_sent=False` on re-verification
- `create_razorpay_linked_account(vendor_id)` — queue=payments, atomic claim via `razorpay_onboarding_step`, step-resume logic for retries, three-step flow (create → stakeholder → submit)
- `recheck_fssai_expiry()` — beat daily, batches of 50, cost-controlled (only calls API for `fssai_expiry_warning_sent=False` vendors in 30-day window), sets `fssai_status=expired` for past-expiry via local date
- `auto_delist_missed_windows()` — beat daily, suspends VendorCommunity where `missed_window_count >= delist_threshold`, decrements `vendor_count`, enqueues SMS + admin notification

**Tests:** terminal state guards, atomic claim concurrency, step-resume for Razorpay, batch processing, freezegun for date comparisons.

### section-10-razorpay-webhook
`RazorpayWebhookView` in `apps/core/views_webhooks.py` (or `apps/vendors/views.py`). `POST /api/v1/webhooks/razorpay/` — unauthenticated. HMAC-SHA256 signature verification using `hmac.compare_digest` (constant-time). Handles `account.activated` event: atomic update of `razorpay_account_status=activated` + `bank_account_verified=True`. Always returns 200 for valid verified webhooks. Add TODO comment for replay protection (future split 05).

**Tests:** invalid/missing signature → 400, valid signature → 200, `account.activated` updates vendor, idempotent re-delivery, `hmac.compare_digest` used (not ==).

### section-11-django-admin
`VendorAdmin` in `apps/vendors/admin.py`: list_display, list_filter, search_fields, readonly_fields. `VendorCommunityAdmin` as inline on VendorAdmin and standalone registration. Both registered with `admin.site.register()`.

**Tests:** admin is registered; list_display renders without error using Django test client; search by fssai_number works.

### section-12-url-configuration
`apps/vendors/urls.py` with all 8 vendor URL patterns (register, documents, submit, status, profile, approve, reject, pending queue). `apps/core/urls_webhooks.py` with Razorpay webhook URL. Include both in `config/urls.py` at `api/v1/`. Register URL namespace `vendors`.

### section-13-env-settings
Add `SUREPASS_TOKEN` and `RAZORPAY_WEBHOOK_SECRET` to `config/settings/base.py` (read from environment). Add `recheck_fssai_expiry` and `auto_delist_missed_windows` Celery beat schedule entries with correct crontab settings (06:00 IST and 06:30 IST respectively).

### section-14-integration-tests
Multi-community scenario tests in `apps/vendors/tests/test_integration.py`. Covers: vendor approved in community A + pending in B (independent records), rejection in A doesn't affect B, Razorpay account created only once across two community approvals, `vendor_count` accuracy across approve→reject→re-approve cycle, `UserRole` created per-community on approval.

**Tests:** all 5 multi-community scenarios from the TDD plan's Section 14.
