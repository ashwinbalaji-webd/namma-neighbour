# Integration Notes: Opus Review Feedback

## Integrating

### 1. Missing `UserRole` creation (Critical)
**Integrating.** The approve endpoint must create `UserRole(user=vendor.user, role='vendor', community=community)` after transitioning `VendorCommunity.status → approved`. Without this, vendors cannot use any `IsVendorOfCommunity`-protected endpoints. The registration endpoint should NOT create the role — vendors must be community-approved first. The plan will be updated to include this in Section 7.2.

### 2. `category_hint` not persisted (High)
**Integrating.** Add an `is_food_seller` BooleanField (default=False) to the `Vendor` model. Set this True when `category_hint=food` is passed at registration. Use this field in the submit endpoint's document validation check instead of the fragile heuristic. This is simpler than storing the raw `category_hint` string and more readable in queries.

### 3. Razorpay task steps 5-6 retry failure (High)
**Integrating.** Add a `razorpay_onboarding_step` CharField to the Vendor model with values: `''` (not started), `'account_created'`, `'stakeholder_added'`, `'submitted'`. The task resumes from where it left off by checking this field. The guard clause changes: if `razorpay_onboarding_step == 'submitted'` → return. Each step atomically updates to the next step value before proceeding. This makes the task safe to retry at any step.

### 4. Exception hierarchy undefined (`TransientAPIError` vs `ExternalAPIError`) (High)
**Integrating.** Define a clear hierarchy in Section 2.2:
- `ExternalAPIError(APIException)` — base class, HTTP 503
- `TransientAPIError(ExternalAPIError)` — retriable (5xx, timeout, connection error)
- `PermanentAPIError(ExternalAPIError)` — non-retriable (400, 404 from third-party APIs)
- `RazorpayError(PermanentAPIError)` — Razorpay-specific, HTTP 402
- `FSSAIVerificationError(PermanentAPIError)` — FSSAI permanent failures, HTTP 400

Celery `autoretry_for` uses `TransientAPIError`. Services raise `PermanentAPIError` (or its subclasses) for non-retriable failures.

### 5. `community_slug` cross-check in approve/reject (Medium)
**Integrating.** The approve and reject views must verify that the `community_slug` in the request body resolves to a community where the requesting user is actually an admin. This means: resolve `Community` by slug, then check `request.user` has admin role in that community. If the JWT's `active_community` is used for the `IsCommunityAdmin` check, the community must also match.

### 6. Remove undeclared `in_progress` fssai_status guard (Medium)
**Integrating.** Use `pending` as the guard state for the `verify_fssai` task. The atomic claim is: `Vendor.objects.filter(pk=vendor_id, fssai_status='pending').update(fssai_status='pending')` — but to prevent duplicate runs, the better approach is to add a `fssai_verification_claimed_at` DateTimeField(null=True) and do a conditional update, OR simply accept that running the FSSAI task twice is safe because the guard "terminal state" check (verified/failed → return) handles the idempotency. The task logs a warning if it finds the vendor already in a terminal state. No undeclared state needed.

### 7. Restore composite `is_new_seller` logic (Medium)
**Integrating.** The property should match the spec and PRD: `completed_delivery_count < 5 or average_rating < Decimal('4.5')`. The badge means "we don't have enough data to trust this seller yet" — both conditions must be met before the badge is removed.

### 8. `vendor_count` semantics and decrement (Medium)
**Integrating with clarification.** `community.vendor_count` represents the current count of **active (approved) vendors**, not lifetime. Decrement on rejection (if previously approved), suspension, and delist. The plan will be updated to document this and add decrement logic to rejection and `auto_delist_missed_windows`.

### 9. FSSAI number format validation (Medium)
**Integrating.** Add a `RegexValidator(r'^\d{14}$', 'FSSAI license number must be 14 digits')` to the `fssai_number` field on the Vendor model. Also validate in the DocumentUploadSerializer when `document_type=fssai_cert` (the number should already be set before triggering verification).

### 10. Razorpay concurrent creation race (Medium)
**Integrating.** Given the new `razorpay_onboarding_step` field (from issue #3), the atomic claim becomes: `Vendor.objects.filter(pk=vendor_id, razorpay_onboarding_step='').update(razorpay_onboarding_step='claiming')` — if 0 rows updated, another worker owns it; return.

### 11. FSSAI recheck cost — `fssai_expiry_warning_sent` flag (Medium)
**Integrating.** Add `fssai_expiry_warning_sent` BooleanField(default=False) to the Vendor model. Reset to False when `fssai_status` changes to `verified`. The `recheck_fssai_expiry` task only calls the Surepass API for vendors where `fssai_expiry_warning_sent=False` and `fssai_expiry_date <= today+30`. After sending the warning, set `fssai_expiry_warning_sent=True`. Vendors already past expiry are handled by a local date comparison — no API call needed.

### 12. Lower file size limit to 5MB (Low)
**Integrating.** Change the upload limit from 10MB to 5MB to stay within Razorpay's stakeholder document upload limits (4MB for images, 2MB for PDFs). 5MB is still generous for document scans.

### 13. Add a tests section to the plan (Low)
**Integrating.** Add Section 14: Testing Strategy, documenting key test scenarios by area.

### 14. VendorCommunity database indexes (Low)
**Integrating.** Add to Section 1.4: composite index on `(community, status)` for the admin pending queue query; index on `(status,)` for the auto-delist daily cron.

### 15. Pagination for pending vendors list (Low)
**Integrating.** Add explicit pagination note in Section 7.1 (page_size=10 default).

### 16. Webhook URL namespace (Low)
**Integrating.** Specify that webhook URLs belong in `apps/core/urls_webhooks.py` (or `apps/webhooks/urls.py`) included in `config/urls.py` at `api/v1/webhooks/`, separate from vendor-specific routes.

---

## Not Integrating

### Webhook replay protection (Low)
**Not integrating for MVP.** The only webhook handled is `account.activated`, which is idempotent via `filter().update()`. Full replay protection (timestamp checks, event ID deduplication) is a post-MVP hardening concern. A comment in the webhook view will note this as a known gap.

### Explicit `get_object()` override for document upload (Low)
**Not integrating as a structural change.** The plan already states `IsVendorOwner` requires explicit `check_object_permissions()` call. Adding a mixin recommendation is a code-level detail that belongs in the implementation, not the plan. The implementer will follow the permission class documentation.

### Celery routing documentation (Low)
**Not integrating as a plan change.** The per-task `queue` decorator parameter overriding module-level routing is a well-known Django-Celery pattern. The plan notes each task's queue explicitly; the implementer can verify with the Celery routing config. Not worth adding noise to the plan.
