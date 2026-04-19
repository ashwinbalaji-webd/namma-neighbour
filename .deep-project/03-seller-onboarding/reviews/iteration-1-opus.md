# Opus Review

**Model:** claude-opus-4
**Generated:** 2026-04-01T04:52:36Z

---

# Review: 03-Seller Onboarding Implementation Plan

**File reviewed:** `/var/www/html/MadGirlfriend/namma-neighbour/.deep-project/03-seller-onboarding/claude-plan.md`

---

## 1. Inconsistent `is_new_seller` Logic Between Spec and Plan

The original spec at `/var/www/html/MadGirlfriend/namma-neighbour/.deep-project/03-seller-onboarding/spec.md` (line 81) defines `is_new_seller` as:

```python
return self.completed_delivery_count < 5 or self.average_rating < Decimal('4.5')
```

The PRD at `/var/www/html/MadGirlfriend/namma-neighbour/requirements.md` (line 32) says: "New sellers are marked 'New' until they complete 5 deliveries with a >4.5 star rating."

The plan (line 98) simplifies this to `completed_delivery_count < 5` only, dropping the rating condition entirely. This is a divergence from both the original spec and the PRD. The plan should explicitly state that this simplification is intentional and why, or it should implement the composite condition. As written, a vendor with 5 deliveries and a 2.0 rating would lose their "New Seller" badge, which contradicts the product intent of that badge as a trust signal.

---

## 2. `category_hint` Is Not Persisted Anywhere

Section 6.1 (line 277) accepts `category_hint` in the registration payload. Section 6.3 (line 312) then says the submit endpoint checks whether FSSAI documents are required "if `category_hint` implied food (check via `fssai_number` being set or `fssai_status != not_applicable`)."

The problem: `category_hint` is never stored on the `Vendor` or `VendorCommunity` model. The plan proposes a heuristic proxy (checking `fssai_number` or `fssai_status`) that is fragile. Consider a food vendor who registers with `category_hint=food`, receives the "you need FSSAI" response, but does not immediately set their `fssai_number`. At submission time, `fssai_number` is empty and `fssai_status` is `not_applicable`, so the heuristic would conclude FSSAI is not required -- defeating the purpose.

The fix is simple: persist `category_hint` (or a derived `is_food_seller` boolean) on the `Vendor` model. This was noted in the spec's `VendorRegistrationSerializer` description but the model table in Section 1.3 does not include it.

---

## 3. Missing `UserRole` Creation for Vendors

The community onboarding plan (split 02) creates a `UserRole(role='community_admin')` when a community is registered, and a `UserRole(role='resident')` when a resident joins. The seller onboarding plan never mentions creating a `UserRole(role='vendor', community=community)` record. Without this, the existing `IsVendorOfCommunity` permission class (which checks `'vendor' in request.auth.payload['roles']`) will never pass. The vendor JWT will lack the `vendor` role claim.

This is a critical omission. Either the registration endpoint (Section 6.1) or the approval endpoint (Section 7.2) must create the `UserRole` record. Based on the architecture, the logical place is the approval endpoint -- a vendor should gain the `vendor` role only after community admin approval.

---

## 4. `TransientAPIError` vs `ExternalAPIError` Naming Confusion

Section 2.2 (line 148) defines `ExternalAPIError` (503). Section 3.1 (line 161) references `TransientAPIError` for retriable failures. Section 8.1 (line 408) uses `TransientAPIError` in the `autoretry_for` tuple. But `TransientAPIError` is never defined in Section 2.2. The spec at `/var/www/html/MadGirlfriend/namma-neighbour/.deep-project/03-seller-onboarding/claude-spec.md` uses both `PermanentAPIError` and `TransientAPIError`.

The plan needs to clearly define: is `ExternalAPIError` the same as `TransientAPIError`? Are they parent-child classes? The research notes (lines 343-346) distinguish them as `PermanentAPIError` and `TransientAPIError`. The plan should settle on a consistent hierarchy. My recommendation: `ExternalAPIError` as a base, with `TransientAPIError(ExternalAPIError)` for retriable and keeping `RazorpayError` / `FSSAIVerificationError` as permanent/non-retriable.

---

## 5. `fssai_status` State Machine Has an Undeclared `in_progress` State

Section 8.1 (lines 413-421) describes using an `in_progress` state as a claim guard for the `verify_fssai` task. The note at line 421 says this is "not exposed as a choice on the model but is used as a guard value." This is contradictory -- you cannot `filter(fssai_status='in_progress').update()` if `in_progress` is not a valid choice value. Django `CharField(choices=...)` does not enforce choices at the database level, so the write would succeed, but it creates a data integrity issue: the field contains a value not declared in `FSSAIStatus`, which will break admin displays, serializers with `ChoiceField`, and any code that switches on the enum values.

Either add `in_progress` as a formal `FSSAIStatus` choice, or use `pending` as the guard as the alternative suggests on line 421. Using `pending` as the guard is simpler and avoids this issue.

---

## 6. No FSSAI Number Format Validation

The Vendor model stores `fssai_number` as `CharField(max_length=14)` (line 83). The Surepass API expects a 14-digit number. The plan never specifies input validation for this field. A regex validator (`^\d{14}$`) should be added to the model field or the serializer to prevent sending garbage to a paid API (~Rs 10-20/call). The research notes confirm the format is 14 digits.

---

## 7. Race Condition in Razorpay Linked Account Creation

Section 8.2 (line 433) has this guard:

> Guard clause: if `razorpay_account_id` is non-empty, return immediately (idempotent)

This is a read-then-act pattern. Two concurrent approval events (e.g., vendor approved in two communities nearly simultaneously) could both read `razorpay_account_id` as empty, both proceed to create accounts, and one would fail at Razorpay (duplicate `reference_id`). The task should use the same atomic `filter().update()` pattern used for FSSAI.

The `reference_id=str(vendor.pk)` provides Razorpay-side idempotency, so the second call would get a Razorpay error rather than a duplicate account. But the plan should still add an atomic claim to avoid wasting API calls and hitting error paths unnecessarily.

---

## 8. Webhook Security: Missing Replay Protection

Section 9.1 (line 469) verifies the HMAC signature but does not implement replay protection. An attacker who intercepts a valid webhook payload can replay it indefinitely. Standard mitigations:

- Check the `X-Razorpay-Event-Timestamp` header and reject events older than 5 minutes
- Store processed event IDs and reject duplicates

The plan already handles the `account.activated` event idempotently (the `filter().update()` on line 481 is safe to run twice), so replay of this specific event is not harmful. But the webhook endpoint should be designed for extensibility -- future events (like `payment.captured` in split 05) may not be idempotent. Adding replay protection now is cheap insurance.

---

## 9. Presigned URL Generation in Serializer Is a Performance Concern

Section 7.1 (line 351) states presigned URLs are "generated per-request at serialization time." For the pending vendor list endpoint, if there are 20 pending vendors each with 3 documents, that is 60 `boto3.generate_presigned_url()` calls per request. These calls are CPU-bound (HMAC computation) and do not hit the network, so they are fast individually, but at scale they add latency.

The plan should note this as a known limitation and suggest pagination (already present via DRF default). However, the endpoint is not explicitly paginated in the plan -- Section 7.1 does not mention pagination. Given that this is an admin-facing queue, it should be paginated with a reasonable page size (e.g., 10) to bound the presigned URL generation cost.

---

## 10. Missing `vendor_count` Decrement on Rejection/Suspension

Section 7.2 (line 370) increments `community.vendor_count` atomically on approval. Section 7.3 (line 387) allows rejecting a vendor who was previously `approved`. Section 8.4 (line 459) suspends vendors. Neither section decrements `vendor_count`. This means the counter will drift upward over time. Either add decrements in the reject/suspend flows, or document this as intentional (perhaps `vendor_count` means "lifetime vendors" not "active vendors").

---

## 11. No Authorization Check on Document Upload Path

Section 6.2 (line 289) says the permission is `IsVendorOwner`, but the URL pattern uses `vendor_id` from the path. The plan correctly notes that `IsVendorOwner` requires `self.check_object_permissions(request, vendor)` (Section 2.1, line 141), but this is easy to forget during implementation. The plan should be more explicit about the view implementation: fetch the `Vendor` by `vendor_id`, call `check_object_permissions`, then proceed. Consider using a mixin or `get_object()` override to make this automatic.

---

## 12. Missing Error Handling for Steps 5-6 of Razorpay Task

Section 8.2 (lines 435-436) calls `add_stakeholder` and `submit_for_review` after storing `razorpay_account_id`. If step 5 (`add_stakeholder`) or step 6 (`submit_for_review`) fails with a transient error and the task retries, the guard clause at step 2 will see a non-empty `razorpay_account_id` and return immediately, permanently leaving the account in a half-configured state (account created but no stakeholder or review submission).

The guard needs to be more nuanced. Options:
- Track the sub-step (e.g., a `razorpay_onboarding_step` field) so retries resume from where they left off
- Make `add_stakeholder` and `submit_for_review` idempotent calls that are safe to re-invoke
- Split into three chained tasks

This is a real footgun that will cause vendors to get stuck in Razorpay's `pending` state with no way to recover short of manual intervention.

---

## 13. `community_slug` in Approve/Reject Endpoints Creates a Mismatch

Section 7.2 (line 358) accepts `community_slug` in the request body. But the permission check is `IsCommunityAdmin`, which checks the JWT's `roles` claim scoped to `active_community`. If the admin's active community does not match the `community_slug` in the body, the admin could approve a vendor for a community they are not an admin of. The plan should add an explicit cross-check: the community resolved from `community_slug` must match the JWT's `community_id`.

---

## 14. Size Limit Inconsistency

Section 5.1 (line 237) sets the file size limit at 10MB. The research notes (line 249) recommend 5MB. The Razorpay stakeholder document upload has a 4MB limit for images and 2MB for PDFs (research, line 142). If vendor documents are forwarded to Razorpay's stakeholder endpoint later, files over 4MB will be rejected by Razorpay.

The plan should either:
- Lower the limit to 5MB to stay within Razorpay's tolerance
- Apply different limits per document type
- Note that documents are resized/compressed before forwarding to Razorpay

---

## 15. No Tests Section

The plan includes a `tests/` directory in the scaffold (Section 1.1) and the research notes describe testing patterns in detail, but the plan itself has no section describing what tests to write. This split should have a dedicated testing section covering:

- Celery task idempotency (concurrent execution of `verify_fssai`)
- FSSAI service mocking
- Razorpay webhook signature verification
- File upload validation (magic bytes)
- Multi-community approval scenarios
- Guard clause behavior in tasks

---

## 16. `recheck_fssai_expiry` Calls a Paid API for All Expiring Vendors Daily

Section 8.3 (line 447) queries all vendors with FSSAI expiry within 30 days and calls `check_expiry()` for each. If there are 500 vendors expiring within the next 30 days, that is 500 API calls daily at Rs 10-20/call = Rs 5,000-10,000/day.

The plan should consider:
- Only calling the API once per vendor when they first enter the 30-day window (a `fssai_expiry_warning_sent` flag)
- Only re-calling the API at specific intervals (30 days, 7 days, 1 day before expiry)
- For vendors already past expiry: just set the status without an API call (the date is already stored locally)

---

## 17. Missing `community_slug` Validation in Submit Endpoint

Section 6.3 (line 306) says to retrieve the `VendorCommunity` record for `(vendor, community)` but does not mention that the submitting vendor must actually own that vendor record. The endpoint URL is `/api/v1/vendors/{vendor_id}/submit/` with `IsVendorOwner` permission, but the `community_slug` in the body is not validated against the vendor's community memberships beyond a 404. This is probably fine given the ownership check, but worth calling out explicitly.

---

## 18. Celery Task Routing Conflict

The foundation plan routes `apps.vendors.tasks.*` to the `kyc` queue. But Section 8.2 of this plan puts `create_razorpay_linked_account` on the `payments` queue, and Section 8.4 has the delist task which should arguably be on `default`. The task-level `queue='payments'` parameter on the decorator will override the module-level routing, but this is implicit and worth documenting. Alternatively, the routing in `CELERY_TASK_ROUTES` should be updated to exclude the Razorpay task, or the plan should note that per-task queue declarations take precedence.

---

## 19. No Database Indexes on VendorCommunity

Section 1.3 (line 100) adds an index on `fssai_expiry_date`. Section 1.4 adds a unique constraint on `(vendor, community)`. But Section 8.4 queries `VendorCommunity.objects.filter(status=approved, missed_window_count__gte=F('delist_threshold'))`. This query runs daily and scans all `approved` vendor-community records. An index on `(status,)` or a composite index on `(status, missed_window_count)` would help at scale. Similarly, Section 7.1 queries on `(community, status)` -- an index there would benefit the admin queue page.

---

## 20. Webhook Endpoint Registered in Wrong URL Namespace

Section 11 (line 529) registers the webhook at `POST webhooks/razorpay/` "separately" from the vendors namespace. But the plan does not specify which `urls.py` file this goes in or how it is included in `config/urls.py`. Given that future splits will add more webhook endpoints, the plan should define a `webhooks` URL namespace.

---

## Summary of Severity

| Issue | Severity | Section |
|-------|----------|---------|
| Missing `UserRole` creation | **Critical** -- vendors cannot access vendor endpoints | 6.1, 7.2 |
| `category_hint` not persisted | **High** -- FSSAI requirement check is broken | 1.3, 6.1, 6.3 |
| Razorpay task steps 5-6 retry failure | **High** -- vendors stuck in half-configured state | 8.2 |
| `TransientAPIError` never defined | **High** -- code will not compile as specified | 2.2 |
| `community_slug` cross-check missing | **Medium** -- authorization bypass possible | 7.2, 7.3 |
| `in_progress` undeclared state | **Medium** -- data integrity risk | 1.2, 8.1 |
| `is_new_seller` logic divergence | **Medium** -- product behavior mismatch | 1.3 |
| `vendor_count` never decremented | **Medium** -- counter drift | 7.2, 7.3, 8.4 |
| No FSSAI number validation | **Medium** -- wasted paid API calls | 1.3 |
| Razorpay concurrent creation race | **Medium** -- duplicate API calls | 8.2 |
| Daily FSSAI recheck cost | **Medium** -- operational cost concern | 8.3 |
| Size limit inconsistency (10MB vs Razorpay 4MB) | **Low** -- downstream failure | 5.1 |
| No replay protection on webhook | **Low** -- future-proofing concern | 9.1 |
| No tests section | **Low** -- plan completeness | N/A |
| Missing indexes on VendorCommunity | **Low** -- future performance | 1.4 |
| Pending vendors list not paginated | **Low** -- performance at scale | 7.1 |
| Webhook URL namespace undefined | **Low** -- plan clarity | 11 |
| Celery routing implicit override | **Low** -- maintainability | 8.2 |
