Now I have all the context I need. Let me generate the section content.

# Section 14: Integration Tests (Multi-Community Scenarios)

## Overview

This is the final section of split 03 (Seller Onboarding). It adds a dedicated integration test file that exercises multi-community scenarios end-to-end — scenarios that cannot be adequately tested within individual unit/view test files because they span the interaction between multiple `VendorCommunity` records, `UserRole` creation, `vendor_count` counters on `Community`, and Razorpay onboarding de-duplication.

These tests are black-box from a Django request perspective: they call views via `APIClient` (or call business logic directly), assert on database state, and mock only the parts that call external APIs (Razorpay, FSSAI, S3).

**This section has no implementation logic of its own.** It only introduces the test file. All application code being tested is implemented in earlier sections.

---

## Dependencies

All other sections must be complete before implementing this section:

| Section | What it provides |
|---------|-----------------|
| section-01-app-scaffold-models | `Vendor`, `VendorCommunity`, `LogisticsTier`, `VendorCommunityStatus` models and factories |
| section-02-permissions-exceptions | `IsVendorOwner`, `IsCommunityAdmin`, custom exception types |
| section-03-fssai-service | `SurepassFSSAIClient` (mocked in these tests) |
| section-04-razorpay-service | `RazorpayClient` (mocked in these tests) |
| section-05-s3-document-upload | File validation, S3 upload helpers (mocked in these tests) |
| section-06-serializers | All vendor serializers |
| section-07-api-views-registration | Vendor-side endpoints |
| section-08-api-views-admin-workflow | Admin approve/reject endpoints, `VendorApproveView` |
| section-09-celery-tasks | `create_razorpay_linked_account` (`.delay` mocked) |
| section-10-razorpay-webhook | Webhook view (not directly tested here) |
| section-11-django-admin | Django admin registration (not directly tested here) |
| section-12-url-configuration | All URL patterns wired into `config/urls.py` |
| section-13-env-settings | Settings for SUREPASS_TOKEN, RAZORPAY_WEBHOOK_SECRET |

The `Community` model and `UserRole` model come from split 01 and split 02 respectively. The `CommunityFactory` lives in `apps/communities/tests/factories.py`. The `UserFactory` and `UserRoleFactory` live in `apps/users/tests/factories.py`.

---

## File Created

**`namma_neighbor/apps/vendors/tests/test_integration.py`**

This is the only deliverable for this section.

## Deviations from Plan

1. **File path corrected**: Plan listed path without `namma_neighbor/` prefix; actual path is `namma_neighbor/apps/vendors/tests/test_integration.py`.
2. **No class-level shared state**: Tests implemented as a class `TestMultiCommunityVendorScenarios` with standalone per-test setup rather than fixtures, matching `test_views.py` patterns.
3. **Patch target**: Used `apps.vendors.views.create_razorpay_linked_account` (established project pattern) rather than `apps.vendors.tasks.create_razorpay_linked_account.delay` as suggested in plan.
4. **Code review additions**: All `_approve()`/`_reject()` calls assert `response.status_code == 200`; delay assertion uses `assert_called_once_with(vendor.pk)`.

## Final Test Count

5 tests, all passing.

---

## Tests

All five scenarios from the TDD plan must be implemented. Each test is marked `@pytest.mark.django_db`. Celery tasks are never called via `.delay()` in these tests — mock `.delay()` using `unittest.mock.patch`.

### Test 1: Vendor approved in community A, pending in community B — records are independent

Scenario: One vendor submits to two communities. Community A admin approves. Community B review is still pending. Assert that the two `VendorCommunity` records are completely independent — approving in A does not change the status of the B record.

```python
# Test: Vendor approved in community A, pending in community B simultaneously —
# both VendorCommunity records are independent
def test_vendor_approved_in_community_a_does_not_affect_community_b_status():
    """
    Vendor registered in both community A and community B.
    Admin of A approves vendor.
    VendorCommunity for B must remain status=pending_review.
    VendorCommunity for A must have status=approved.
    """
```

Setup steps:
1. Create one vendor `User` and a corresponding `Vendor` with required documents uploaded (set `govt_id_s3_key` and `bank_proof_s3_key` directly on the instance).
2. Create two communities (`community_a`, `community_b`) each with a separate admin user.
3. Create two `VendorCommunity` records: both `status=pending_review`.
4. POST to `/api/v1/vendors/{vendor_id}/approve/` as admin of community A, passing `community_slug=community_a.slug`.
5. Assert `VendorCommunity.objects.get(vendor=vendor, community=community_a).status == 'approved'`.
6. Assert `VendorCommunity.objects.get(vendor=vendor, community=community_b).status == 'pending_review'`.

Mock `create_razorpay_linked_account.delay` to suppress the Celery enqueue.

### Test 2: Vendor rejected in community A can still be approved in community B

Scenario: Admin of community A rejects the vendor. Admin of community B independently approves the same vendor. The rejection in A must not block the approval in B.

```python
# Test: Vendor rejected in community A can still be approved in community B
def test_rejection_in_one_community_does_not_block_approval_in_another():
    """
    Vendor has VendorCommunity records in both A and B (pending_review).
    Admin A rejects vendor.
    Admin B approves vendor.
    VendorCommunity for B must have status=approved.
    """
```

Setup steps:
1. Create vendor and two communities (each with an admin).
2. Create two `VendorCommunity` records, both `pending_review`.
3. POST reject to community A.
4. POST approve to community B (with `override_fssai_warning=False` or simply ensure `fssai_status` is not `failed`).
5. Assert community B status is `approved`.
6. Assert community A status is `rejected`.

Mock `create_razorpay_linked_account.delay`.

### Test 3: Razorpay account created only once even when approved in two communities back-to-back

Scenario: Vendor is approved in community A (triggers `create_razorpay_linked_account.delay`). Vendor is then approved in community B. The Razorpay task must be enqueued only once total.

This test verifies the guard condition in `VendorApproveView`: `create_razorpay_linked_account.delay` is only enqueued if `vendor.razorpay_onboarding_step == ''`.

```python
# Test: Razorpay account created only once even when approved in two communities back-to-back
def test_razorpay_linked_account_enqueued_only_on_first_community_approval():
    """
    Vendor approved in community A → create_razorpay_linked_account.delay called once.
    Simulate the task completing by setting razorpay_onboarding_step='submitted' on the vendor.
    Vendor approved in community B → create_razorpay_linked_account.delay NOT called again.
    Total call count on mock.delay must be 1.
    """
```

Setup steps:
1. Create vendor and two communities.
2. Create two `VendorCommunity` records, both `pending_review`.
3. Patch `apps.vendors.tasks.create_razorpay_linked_account.delay`.
4. POST approve to community A. Assert `mock_delay.call_count == 1`.
5. Simulate the Razorpay task having run: `Vendor.objects.filter(pk=vendor.pk).update(razorpay_onboarding_step='submitted')`.
6. POST approve to community B. Assert `mock_delay.call_count` is still `1` (not 2).

### Test 4: vendor_count correct across approve → reject → re-approve cycle

Scenario: A vendor goes through a full lifecycle in one community: approved, then rejected, then re-approved. The `community.vendor_count` must reflect only currently-approved vendors.

```python
# Test: vendor_count correct across approve → reject → re-approve cycle
def test_vendor_count_is_accurate_across_approve_reject_reapprove_cycle():
    """
    Initial vendor_count = 0.
    After approve: vendor_count = 1.
    After reject (was approved): vendor_count = 0.
    Vendor resubmits (status → pending_review), then re-approved: vendor_count = 1.
    """
```

Setup steps:
1. Create vendor and one community (with admin). `community.vendor_count` starts at 0.
2. Create `VendorCommunity` with `status=pending_review`.
3. POST approve → assert `Community.objects.get(pk=community.pk).vendor_count == 1`.
4. POST reject (community admin rejects the now-approved vendor) → assert `vendor_count == 0`.
5. Update `VendorCommunity.status = pending_review` directly (simulating re-submission).
6. POST approve again → assert `vendor_count == 1`.

Mock `create_razorpay_linked_account.delay`. Note: on the re-approve, the vendor's `razorpay_onboarding_step` is already `'submitted'` (from the first approval sequence), so the mock should not be called a second time.

Use `Community.objects.get(pk=community.pk).vendor_count` (fresh DB read, not the cached instance) for all assertions.

### Test 5: UserRole created per-community on approval

Scenario: Vendor is approved in community A and then community B. Each approval creates a separate `UserRole(role='vendor', community=...)` record. Approving in A does not create a role for B, and vice versa.

```python
# Test: UserRole created for community A on first approval; second approval in community B
# creates a separate UserRole for B
def test_userrole_created_independently_per_community_on_approval():
    """
    After approval in A: UserRole(user=vendor.user, role='vendor', community=A) exists.
    No UserRole for community B yet.
    After approval in B: UserRole(user=vendor.user, role='vendor', community=B) exists.
    Both roles exist simultaneously; no duplicates.
    """
```

Setup steps:
1. Create vendor and two communities.
2. Create two `VendorCommunity` records.
3. POST approve to community A.
4. Assert `UserRole.objects.filter(user=vendor.user, role='vendor', community=community_a).count() == 1`.
5. Assert `UserRole.objects.filter(user=vendor.user, role='vendor', community=community_b).count() == 0`.
6. POST approve to community B.
7. Assert both roles now exist: total `UserRole.objects.filter(user=vendor.user, role='vendor').count() == 2`.
8. Assert re-approving in A (idempotency) does not create a duplicate: `UserRole.objects.filter(user=vendor.user, role='vendor', community=community_a).count() == 1`.

---

## Test File Structure

```python
# apps/vendors/tests/test_integration.py
import pytest
from unittest.mock import patch
from rest_framework.test import APIClient
from django.urls import reverse

from apps.users.models import UserRole
from apps.users.tests.factories import UserFactory, UserRoleFactory
from apps.communities.tests.factories import CommunityFactory
from apps.vendors.models import Vendor, VendorCommunity, VendorCommunityStatus
from apps.vendors.tests.factories import VendorFactory, VendorCommunityFactory


@pytest.mark.django_db
class TestMultiCommunityVendorScenarios:

    def _make_community_admin(self, community):
        """Helper: create a user and give them community_admin role for the given community."""
        ...

    def _approve_vendor(self, client, vendor_id, community_slug, override_fssai=False):
        """Helper: POST to approve endpoint as the given client."""
        ...

    def _reject_vendor(self, client, vendor_id, community_slug, reason='Test rejection'):
        """Helper: POST to reject endpoint."""
        ...

    @patch('apps.vendors.tasks.create_razorpay_linked_account.delay')
    def test_vendor_approved_in_community_a_does_not_affect_community_b_status(self, mock_delay):
        ...

    @patch('apps.vendors.tasks.create_razorpay_linked_account.delay')
    def test_rejection_in_one_community_does_not_block_approval_in_another(self, mock_delay):
        ...

    @patch('apps.vendors.tasks.create_razorpay_linked_account.delay')
    def test_razorpay_linked_account_enqueued_only_on_first_community_approval(self, mock_delay):
        ...

    @patch('apps.vendors.tasks.create_razorpay_linked_account.delay')
    def test_vendor_count_is_accurate_across_approve_reject_reapprove_cycle(self, mock_delay):
        ...

    @patch('apps.vendors.tasks.create_razorpay_linked_account.delay')
    def test_userrole_created_independently_per_community_on_approval(self, mock_delay):
        ...
```

---

## Key Implementation Notes

### Approve endpoint request shape

The approve endpoint (`POST /api/v1/vendors/{vendor_id}/approve/`) expects a JSON body with at minimum:

```json
{
  "community_slug": "<slug>",
  "override_fssai_warning": false
}
```

When `vendor.fssai_status` is not `failed`, `override_fssai_warning` is not evaluated — the default `false` is fine.

### Reject endpoint request shape

```json
{
  "community_slug": "<slug>",
  "reason": "Reason for rejection"
}
```

### Authenticating the admin client

Use `APIClient.force_authenticate(user=admin_user)` to avoid token flow overhead in integration tests.

### Vendor factory defaults for integration tests

The `VendorFactory` (from `apps/vendors/tests/factories.py`, implemented in section-01) should set:
- `govt_id_s3_key = 'documents/vendors/1/govt_id/test.pdf'` (any non-blank string)
- `bank_proof_s3_key = 'documents/vendors/1/bank_proof/test.pdf'`
- `fssai_status = FSSAIStatus.NOT_APPLICABLE` (default)
- `razorpay_onboarding_step = ''` (default — Razorpay not yet started)

If the factory does not set these non-blank S3 key values, the submit endpoint will block with 400. For integration tests you can either:
1. Set them directly on the factory instance after creation, or
2. Override them in the factory call: `VendorFactory(govt_id_s3_key='docs/gov.pdf', bank_proof_s3_key='docs/bank.pdf')`

For the approval endpoint, the vendor must have already submitted (i.e., `VendorCommunity.status == pending_review`). Create the `VendorCommunity` record directly with `status=VendorCommunityStatus.PENDING_REVIEW` rather than going through the full submit flow in each test.

### IsCommunityAdmin permission

The `IsCommunityAdmin` permission (from `apps/core/permissions.py`, split 02) checks that `request.user` has a `UserRole` record with `role='community_admin'` for the community being accessed. In test setup, create this role with `UserRoleFactory(user=admin_user, role='community_admin', community=community)`.

### vendor_count assertions — always re-fetch from DB

Never assert on a stale model instance. Always use:
```python
community.refresh_from_db()
assert community.vendor_count == expected
```
or
```python
assert Community.objects.get(pk=community.pk).vendor_count == expected
```

The `Community` model uses `F()` expression updates (`Community.objects.filter(pk=pk).update(vendor_count=F('vendor_count') + 1)`), which bypass the Python instance — the cached in-memory value will not reflect the update.

---

## Running the Tests

```bash
uv run pytest apps/vendors/tests/test_integration.py -v
```

To run the full vendor test suite together:

```bash
uv run pytest apps/vendors/tests/ -v
```

---

## Acceptance Checklist

Before marking this section done, verify:

- [ ] `apps/vendors/tests/test_integration.py` exists and imports without error
- [ ] `uv run pytest apps/vendors/tests/test_integration.py --collect-only` shows exactly 5 test functions collected
- [ ] All 5 tests pass: `uv run pytest apps/vendors/tests/test_integration.py -v`
- [ ] No test calls a real external API — all service clients (FSSAI, Razorpay, S3) are mocked
- [ ] `test_razorpay_linked_account_enqueued_only_on_first_community_approval` asserts `mock_delay.call_count == 1`, not just `mock_delay.called`
- [ ] `test_vendor_count_is_accurate_across_approve_reject_reapprove_cycle` uses a fresh DB read for each `vendor_count` assertion (`.refresh_from_db()` or `Community.objects.get(pk=...)`)
- [ ] `test_userrole_created_independently_per_community_on_approval` asserts both that the correct role exists AND that no duplicate roles are created on re-approval