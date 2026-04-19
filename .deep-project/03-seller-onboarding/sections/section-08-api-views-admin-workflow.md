I now have all the context I need. Let me produce the complete section content.

# Section 08: API Views — Community Admin Workflow

## Overview

This section implements the four community-admin-facing API views in `apps/vendors/views.py`. These are the views that community admins use to review vendor applications, approve or reject them, and that residents use to view vendor public profiles.

This section depends on:
- **section-01**: `Vendor`, `VendorCommunity`, `FSSAIStatus`, `VendorCommunityStatus` models, `LogisticsTier`
- **section-02**: `IsCommunityAdmin`, `IsResidentOfCommunity` from `apps/core/permissions.py` (pre-existing from split 01), `IsVendorOwner` (added in section 02)
- **section-05**: `generate_document_presigned_url()` from `apps/vendors/services/storage.py`
- **section-06**: `PendingVendorSerializer`, `VendorPublicProfileSerializer` from `apps/vendors/serializers.py`
- **section-07**: The same `apps/vendors/views.py` file this section extends — both sections share the same module

The Celery task `create_razorpay_linked_account` (section-09) is only referenced via `.delay()`. Its `.delay` is mocked in view tests.

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `apps/vendors/views.py` | Extend — add the four admin views to the existing module |
| `apps/vendors/tests/test_views.py` | Extend — append admin workflow test cases |

All absolute paths in this document are rooted at `/var/www/html/MadGirlfriend/namma-neighbour/`.

---

## Background: Existing Permissions

`apps/core/permissions.py` (from split 01 `section-02-core-app`) already contains JWT-role-based permission classes. The ones used in this section:

- **`IsCommunityAdmin`** — checks that `request.user` holds the `community_admin` role for the community resolved from the JWT's active community context. **Important:** the community in the JWT must match the `community_slug` passed in the request body (see cross-check logic below).
- **`IsResidentOfCommunity`** — checks that `request.user` holds the `resident` role in the active community from the JWT.

`IsVendorOwner` (added in section-02 of this split) is an object-level permission; it is **not** used by admin views. Admin views use `IsCommunityAdmin`.

---

## Tests First

File: `/var/www/html/MadGirlfriend/namma-neighbour/apps/vendors/tests/test_views.py`

Append these test classes/functions to the existing file created in section-07. All tests use `pytest.mark.django_db`, `APIClient`, and factories from `apps/vendors/tests/factories.py`. Mock `create_razorpay_linked_account.delay` with `unittest.mock.patch` — never call the Celery task directly from view tests.

### Fixtures Needed

```python
# Reuse fixtures from section-07 where possible. Additional fixtures:
# - admin_user: a User with IsCommunityAdmin role for the test community (set via UserRole or JWT claims)
# - admin_client: APIClient.force_authenticate(user=admin_user)
# - resident_user: a User with IsResidentOfCommunity role for the test community
# - resident_client: APIClient.force_authenticate(user=resident_user)
# - pending_vendor_community: a VendorCommunity with status=PENDING_REVIEW in the test community
```

### 7.1 GET /api/v1/communities/{slug}/vendors/pending/

```python
# Test: Returns only vendors with status=pending_review in the admin's community
#   - Create two VendorCommunity records in the same community, status=pending_review
#   - Create one VendorCommunity with status=approved (should NOT appear)
#   - GET /communities/{slug}/vendors/pending/ as admin
#   - Assert 200; response['results'] has exactly 2 entries

# Test: Does not return vendors from other communities
#   - Create a VendorCommunity for a different community, status=pending_review
#   - Assert that entry is absent from the response

# Test: Response includes presigned URL for each uploaded document (non-empty s3_key)
#   - Set vendor.govt_id_s3_key to a non-empty value
#   - Assert response entry contains document_urls['govt_id'] as a non-empty string
#   - Assert document type with empty s3_key is NOT present in document_urls

# Test: Response includes fssai_warning=True when vendor.fssai_status='failed'
#   - Create a vendor with fssai_status=FSSAIStatus.FAILED
#   - Assert response entry has fssai_warning=True
#   - Assert vendor with fssai_status='verified' has fssai_warning=False

# Test: Response is paginated (page_size=10; 11th vendor not in first page)
#   - Create 11 VendorCommunity records in pending_review
#   - Assert response['count'] == 11 but len(response['results']) == 10
#   - Assert response['next'] is not None

# Test: Returns 403 when user is not a community admin
#   - Authenticate as a regular resident user
#   - GET /communities/{slug}/vendors/pending/
#   - Assert 403
```

### 7.2 POST /api/v1/vendors/{vendor_id}/approve/

```python
# Test: Transitions VendorCommunity.status → 'approved'
#   - POST with {community_slug: ..., override_fssai_warning: false}
#   - Assert VendorCommunity.status == VendorCommunityStatus.APPROVED

# Test: Sets approved_by and approved_at
#   - After approval, assert vc.approved_by == admin_user
#   - Assert vc.approved_at is not None

# Test: Increments community.vendor_count by 1
#   - Record community.vendor_count before; assert it is count+1 after approval

# Test: Creates UserRole(role='vendor', community=community) for vendor.user
#   - Assert UserRole.objects.filter(user=vendor.user, role='vendor', community=community).exists() == True

# Test: UserRole not duplicated if vendor approved in same community twice (idempotent)
#   - Approve the vendor; approve again (reset status to pending_review first)
#   - Assert UserRole.objects.filter(user=vendor.user, role='vendor', community=community).count() == 1

# Test: Enqueues create_razorpay_linked_account.delay on first approval (razorpay_onboarding_step='')
#   - vendor.razorpay_onboarding_step = ''
#   - POST approve
#   - Assert create_razorpay_linked_account.delay.call_count == 1

# Test: Does NOT enqueue create_razorpay_linked_account when already onboarded (razorpay_onboarding_step='submitted')
#   - vendor.razorpay_onboarding_step = 'submitted'
#   - POST approve
#   - Assert create_razorpay_linked_account.delay not called

# Test: Returns 400 when fssai_status='failed' and override_fssai_warning=False
#   - vendor.fssai_status = FSSAIStatus.FAILED
#   - POST with {override_fssai_warning: false}
#   - Assert 400

# Test: Proceeds when fssai_status='failed' and override_fssai_warning=True
#   - vendor.fssai_status = FSSAIStatus.FAILED
#   - POST with {override_fssai_warning: true}
#   - Assert 200 and VendorCommunity.status == approved

# Test: Returns 403 when admin tries to approve vendor for a community they don't admin (community_slug mismatch)
#   - Create another community for which the admin has no role
#   - POST with that community's slug
#   - Assert 403

# Test: Returns 404 when VendorCommunity not found in pending_review
#   - Set VendorCommunity.status = approved (already approved; not pending)
#   - POST approve
#   - Assert 404
```

### 7.3 POST /api/v1/vendors/{vendor_id}/reject/

```python
# Test: Transitions VendorCommunity.status → 'rejected'
#   - POST with {community_slug: ..., reason: "FSSAI expired"}
#   - Assert VendorCommunity.status == VendorCommunityStatus.REJECTED

# Test: Stores rejection_reason
#   - Assert VendorCommunity.rejection_reason == "FSSAI expired"

# Test: Decrements community.vendor_count when vendor was previously approved
#   - Set VendorCommunity.status = approved; increment vendor_count manually
#   - POST reject
#   - Assert community.vendor_count decremented by 1

# Test: Does NOT decrement vendor_count when vendor was in pending_review (not yet counted)
#   - VendorCommunity.status = pending_review (the default)
#   - Record community.vendor_count; POST reject
#   - Assert vendor_count unchanged

# Test: Returns 403 when admin tries to reject for community they don't admin
#   - Use a community_slug that the admin does not manage
#   - Assert 403

# Test: Vendor can re-submit after rejection (status returns to pending_review on next submit)
#   - After rejection, use VendorSubmitView (section-07) to re-submit
#   - Assert VendorCommunity.status == pending_review
```

### 7.4 GET /api/v1/vendors/{vendor_id}/profile/

```python
# Test: Returns display_name, bio, average_rating, is_new_seller
#   - GET /vendors/{vendor_id}/profile/ as an authenticated resident
#   - Assert response contains exactly: vendor_id, display_name, bio, average_rating, is_new_seller

# Test: Does NOT return fssai_number, razorpay_account_id, *_s3_key fields
#   - Assert none of these keys appear in the response body:
#     fssai_number, razorpay_account_id, govt_id_s3_key, bank_proof_s3_key,
#     fssai_cert_s3_key, gst_cert_s3_key, bank_account_verified

# Test: Returns 403 when user is not a resident of the community
#   - Authenticate as a user with no community role
#   - GET /vendors/{vendor_id}/profile/
#   - Assert 403
```

---

## Implementation

File: `/var/www/html/MadGirlfriend/namma-neighbour/apps/vendors/views.py`

Append the four admin views to the end of the existing module. Do not create a separate file.

### Additional Imports (append to existing imports in `views.py`)

```python
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.vendors.serializers import PendingVendorSerializer, VendorPublicProfileSerializer
from apps.vendors.tasks import create_razorpay_linked_account
# UserRole model — adjust import path to match split 01 foundation
from apps.users.models import UserRole
```

Import `create_razorpay_linked_account` at the top of the module (not inside the method) unless it causes circular imports, in which case import it lazily inside the method body.

---

### CommunityPendingVendorsView

`GET /api/v1/communities/{slug}/vendors/pending/`

Permission: `IsCommunityAdmin` — the authenticated user must be an admin of the community identified by `slug`.

```python
class CommunityPendingVendorsView(generics.ListAPIView):
    """
    Returns a paginated list of VendorCommunity records with status=pending_review
    for a given community. Used by community admins to review vendor applications.

    Each entry includes presigned S3 document URLs (TTL=3600s) and an fssai_warning
    flag. Presigned URL generation is CPU-bound (HMAC, no network) and safe for
    synchronous request handling at page_size=10.

    Pagination: page_size=10 (PageNumberPagination).

    Returns:
        200: paginated list of PendingVendorSerializer responses
        403: not a community admin
        404: community not found
    """
    serializer_class = PendingVendorSerializer
    permission_classes = [IsAuthenticated, IsCommunityAdmin]
    pagination_class = ...  # set page_size=10; use PageNumberPagination
```

Logic for `get_queryset()`:
1. Resolve `self.kwargs['slug']` to a `Community` object; raise `Http404` if not found.
2. Return `VendorCommunity.objects.filter(community=community, status=VendorCommunityStatus.PENDING_REVIEW).select_related('vendor')`.
   - `select_related('vendor')` is critical — avoids N+1 during presigned URL generation in `PendingVendorSerializer`.

The `IsCommunityAdmin` permission class checks the JWT's active community role. The URL `slug` must match the admin's active community — if the JWT active community differs from `slug`, the permission check should return 403. Confirm how `IsCommunityAdmin` resolves the community in the existing split 01 implementation; if it uses the URL slug directly, no extra check is needed. If it relies solely on the JWT, add an explicit `slug` cross-check in the view's `get()` method.

---

### VendorApproveView

`POST /api/v1/vendors/{vendor_id}/approve/`

Permission: `IsCommunityAdmin`

Request body:
```json
{
  "community_slug": "prestige-oasis",
  "override_fssai_warning": false
}
```

```python
class VendorApproveView(APIView):
    """
    Approves a vendor's application for a specific community.

    Business logic:
    1. Resolve community_slug → Community; 404 if not found.
    2. Cross-check: verify request.user is admin of the resolved community (not just any community).
       Return 403 if the community_slug resolves to a community the user does not admin.
    3. Retrieve VendorCommunity for (vendor, community) where status=pending_review. 404 otherwise.
    4. FSSAI guard: if vendor.fssai_status == 'failed' and override_fssai_warning != True, return 400.
    5. Atomic update:
       a. VendorCommunity.status → approved; set approved_by=request.user, approved_at=now()
       b. community.vendor_count incremented atomically (F() expression)
       c. UserRole.objects.get_or_create(user=vendor.user, role='vendor', community=community)
       d. If vendor.razorpay_onboarding_step == '': enqueue create_razorpay_linked_account.delay(vendor.pk)

    Returns:
        200: {status: 'approved'}
        400: FSSAI guard triggered (fssai_status='failed', no override)
        403: not admin of this community
        404: community not found, or VendorCommunity not in pending_review
    """
    permission_classes = [IsAuthenticated, IsCommunityAdmin]
```

Key implementation notes:

**Community cross-check:** The `IsCommunityAdmin` permission class alone is not sufficient — it only verifies the user is an admin of _their active community_ (from JWT). The view must additionally verify that `community_slug` in the request body resolves to the same community. Without this cross-check, a community admin could approve a vendor into a different community by passing a different `community_slug`. Implementation: after resolving `community_slug` to a `Community` instance, check that `request.user` holds the `community_admin` role for _that specific community_. If not, return 403.

**Atomic approval block:** Wrap steps 5a through 5c in `transaction.atomic()`. The `vendor_count` increment must use `Community.objects.filter(pk=community.pk).update(vendor_count=F('vendor_count') + 1)` rather than `community.vendor_count += 1; community.save()` to avoid lost updates.

**UserRole idempotency:** Use `get_or_create` — never `create`. If the vendor was already approved in this community (and the record was reset to `pending_review` for some administrative reason), the role should not be duplicated.

**First-approval Razorpay check:** Read `vendor.razorpay_onboarding_step` _inside_ the atomic block after the `VendorCommunity` update, so it reflects any concurrent update. Enqueue `create_razorpay_linked_account.delay(vendor.pk)` only if `razorpay_onboarding_step == ''` (never started). This ensures the Razorpay Linked Account is created exactly once, even when the vendor is approved in multiple communities back-to-back.

**SMS notification:** Add a comment `# TODO: enqueue SMS notification to vendor (split 05)` where the vendor notification would go.

---

### VendorRejectView

`POST /api/v1/vendors/{vendor_id}/reject/`

Permission: `IsCommunityAdmin`

Request body:
```json
{
  "community_slug": "prestige-oasis",
  "reason": "FSSAI certificate expired"
}
```

```python
class VendorRejectView(APIView):
    """
    Rejects a vendor's application for a specific community.

    Business logic:
    1. Resolve community_slug → Community; 404 if not found.
    2. Cross-check: verify request.user is admin of the resolved community. 403 if not.
    3. Retrieve VendorCommunity for (vendor, community). Records in pending_review OR
       approved can be rejected. 404 if the record does not exist.
    4. Capture previous_status = vc.status before updating.
    5. Atomic update: status → rejected; rejection_reason = reason.
    6. If previous_status == 'approved': decrement community.vendor_count atomically.
       (vendor_count represents current active/approved vendors, not lifetime count.)

    The vendor can update their documents and re-submit after rejection. The same
    VendorCommunity record is reused; VendorSubmitView resets status to pending_review.

    Returns:
        200: {status: 'rejected'}
        403: not admin of this community
        404: community not found, or VendorCommunity not found
    """
    permission_classes = [IsAuthenticated, IsCommunityAdmin]
```

Key implementation notes:

**`vendor_count` decrement condition:** Only decrement if the record was previously `approved` — a vendor in `pending_review` was never counted in `vendor_count`, so rejecting them must not decrement it. Capture `previous_status` before the update.

**`vendor_count` decrement method:** Use `Community.objects.filter(pk=community.pk).update(vendor_count=F('vendor_count') - 1)`. Never use `community.vendor_count -= 1; community.save()`.

**No FSSAI guard on rejection:** Unlike approval, there is no FSSAI guard — admins can always reject for any reason.

**SMS notification:** Add `# TODO: enqueue SMS notification to vendor with rejection_reason (split 05)`.

---

### VendorPublicProfileView

`GET /api/v1/vendors/{vendor_id}/profile/`

Permission: `IsResidentOfCommunity`

```python
class VendorPublicProfileView(APIView):
    """
    Returns a vendor's public-facing profile for residents to view.

    Exposes only display-safe fields: vendor_id, display_name, bio,
    average_rating, is_new_seller. No KYB, bank, S3 key, FSSAI license
    number, or Razorpay data is included.

    Returns:
        200: VendorPublicProfileSerializer response
        403: not a resident of this community
        404: vendor not found
    """
    permission_classes = [IsAuthenticated, IsResidentOfCommunity]
```

Logic steps (implement inside `get()`):
1. Fetch `Vendor` by `vendor_id`; raise `Http404` if not found.
2. Serialize with `VendorPublicProfileSerializer(vendor)`.
3. Return 200 with serializer data.

Note: this view does **not** use `IsVendorOwner` — any authenticated resident can view any vendor's public profile. The `IsResidentOfCommunity` permission check ensures only community residents have access.

---

## Response Shapes

### GET /communities/{slug}/vendors/pending/ — 200

```json
{
  "count": 3,
  "next": null,
  "previous": null,
  "results": [
    {
      "vendor_id": 42,
      "display_name": "Priya's Bakery",
      "bio": "Home baker specializing in sourdough",
      "logistics_tier": "tier_b",
      "fssai_status": "verified",
      "fssai_business_name": "Priya Enterprises",
      "fssai_warning": false,
      "average_rating": "0.00",
      "is_new_seller": true,
      "document_urls": {
        "govt_id": "https://s3.ap-south-1.amazonaws.com/...",
        "fssai_cert": "https://s3.ap-south-1.amazonaws.com/..."
      }
    }
  ]
}
```

### POST /approve/ — 200

```json
{
  "status": "approved"
}
```

### POST /reject/ — 200

```json
{
  "status": "rejected"
}
```

### GET /profile/ — 200

```json
{
  "vendor_id": 42,
  "display_name": "Priya's Bakery",
  "bio": "Home baker specializing in sourdough",
  "average_rating": "4.80",
  "is_new_seller": false
}
```

---

## Key Design Decisions

**Community cross-check in approve/reject views:** The `IsCommunityAdmin` DRF permission class (from split 01) checks the JWT's active community role. However, the `community_slug` in the request body could differ from the JWT's active community if a malicious or misconfigured client sends a mismatched slug. The views must explicitly verify that the resolved `Community` matches the community for which the user actually holds admin rights. Fail with 403 if there is a mismatch.

**`vendor_count` uses `F()` expressions:** Both increment (approve) and decrement (reject of previously-approved vendor) must use Django `F()` expressions via `.update()` at the database level. This prevents lost updates under concurrent requests. Never read `community.vendor_count`, modify it in Python, and write it back.

**`UserRole.get_or_create` on approval:** Creating a `UserRole(role='vendor')` is idempotent by design. The vendor should not hold duplicate roles in the same community. `get_or_create` on `(user, role, community)` ensures this invariant regardless of how many times the approval endpoint is called.

**`select_related('vendor')` is mandatory on the pending queue:** `PendingVendorSerializer` accesses `vendor_community.vendor.*` for every field and generates presigned URLs per document. Without `select_related`, each serialized record triggers additional DB queries. The view must pass a `select_related('vendor')` queryset to the serializer — this is enforced at the view level.

**Razorpay task is enqueued at first approval only:** The `create_razorpay_linked_account` task creates a Razorpay Linked Account, which is a global (not per-community) resource. If a vendor is approved in community A and later in community B, the task must not be enqueued again on the second approval. The check `vendor.razorpay_onboarding_step == ''` (never started) ensures this. The task itself also has a terminal state guard (`step == 'submitted'` → return immediately), but the view-level check prevents unnecessary task enqueuing.

**Wrap approval steps in `transaction.atomic()`:** The status transition, `vendor_count` increment, and `UserRole` creation must all succeed together or none should persist. If `UserRole` creation fails after the status was updated, the vendor would be approved with no `vendor` JWT role — a broken state. `transaction.atomic()` prevents this.

---

## Dependencies Summary

| Dependency | What it provides |
|------------|-----------------|
| section-01 | `Vendor`, `VendorCommunity`, `FSSAIStatus`, `VendorCommunityStatus` models |
| section-02 | `IsCommunityAdmin`, `IsResidentOfCommunity` (already in `apps/core/permissions.py` from split 01); `IsVendorOwner` added in section 02 of this split |
| section-05 | `generate_document_presigned_url()` (used indirectly via `PendingVendorSerializer`) |
| section-06 | `PendingVendorSerializer`, `VendorPublicProfileSerializer` from `apps/vendors/serializers.py` |
| section-07 | Same `apps/vendors/views.py` file — this section appends to it; section-07 must be implemented first |
| section-09 | `create_razorpay_linked_account` Celery task — only `.delay` is called; a stub is sufficient |
| section-12 | URL wiring — not needed to run this section's tests if using hard-coded URL paths in `APIClient.post(...)` calls |

---

## Checklist

- [ ] Write all test stubs in `apps/vendors/tests/test_views.py` (admin workflow section) before implementing views
- [ ] Append `CommunityPendingVendorsView` to `apps/vendors/views.py` with `select_related('vendor')` queryset and `page_size=10` pagination
- [ ] Append `VendorApproveView` with: community cross-check, FSSAI guard, `transaction.atomic()` block, `F()` increment, `UserRole.get_or_create`, conditional `create_razorpay_linked_account.delay`
- [ ] Append `VendorRejectView` with: community cross-check, `previous_status` capture, `F()` decrement only if was approved
- [ ] Append `VendorPublicProfileView` using `IsResidentOfCommunity` and `VendorPublicProfileSerializer`
- [ ] Mock `create_razorpay_linked_account.delay` in all approve view tests using `unittest.mock.patch`
- [ ] Verify `uv run pytest apps/vendors/tests/test_views.py` passes for the admin workflow test class