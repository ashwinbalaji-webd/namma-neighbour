Now I have all the context I need. Let me produce the section content.

# Section 11: Django Admin

## Overview

This section implements the Django admin interface for the `Vendor` and `VendorCommunity` models. It provides operators and support staff a read-friendly list view with filtering, search, and inline access to community approval records. This section depends only on **section-01-app-scaffold-models** and can be implemented in parallel with all other sections except section-01.

## Dependencies

- **section-01-app-scaffold-models** must be complete: `Vendor`, `VendorCommunity`, `FSSAIStatus`, `VendorCommunityStatus`, and `LogisticsTier` must exist in `apps/vendors/models.py`.
- No dependency on views, serializers, tasks, or services.

## Files to Create

- `/var/www/html/MadGirlfriend/namma-neighbour/apps/vendors/admin.py` — primary deliverable
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/vendors/tests/test_admin.py` — smoke tests

## Tests

Tests live in `apps/vendors/tests/test_admin.py`. Use `pytest-django`'s built-in `admin_client` fixture (a Django test client already logged in as a superuser). Use `VendorFactory` and `VendorCommunityFactory` from `apps/vendors/tests/factories.py` (defined in section-01).

Required test cases (from the TDD plan, Section 10):

```python
# apps/vendors/tests/test_admin.py

import pytest

@pytest.mark.django_db
class TestVendorAdmin:
    def test_vendor_admin_is_registered(self):
        """VendorAdmin is registered in the default admin site."""
        ...

    def test_vendor_community_list_display_renders(self, admin_client, vendor_community):
        """VendorCommunity changelist page renders without error."""
        ...

    def test_vendor_search_by_fssai_number(self, admin_client, vendor):
        """Search for a vendor by fssai_number returns the correct result."""
        ...
```

### Test Implementation Notes

- `test_vendor_admin_is_registered`: import `django.contrib.admin` and assert `admin.site._registry` contains the `Vendor` model class.
- `test_vendor_community_list_display_renders`: use `admin_client.get('/admin/vendors/vendorcommunity/')` and assert `response.status_code == 200`.
- `test_vendor_search_by_fssai_number`: create a vendor with a known `fssai_number` (e.g. `'12345678901234'`), then hit `admin_client.get('/admin/vendors/vendor/?q=12345678901234')` and assert the vendor's `display_name` appears in the response content.

Fixtures `vendor` and `vendor_community` should be defined in `apps/vendors/tests/conftest.py` using the factories from section-01 (or defined inline in this test file if conftest is not yet in place).

## Implementation

### `apps/vendors/admin.py`

#### VendorCommunityInline

Register `VendorCommunity` as a `TabularInline` on `VendorAdmin` so operators can see all community approval states for a given vendor on the vendor change page.

- `model = VendorCommunity`
- `fields`: `community`, `status`, `approved_by`, `approved_at`, `missed_window_count`, `delist_threshold`
- `readonly_fields`: `approved_by`, `approved_at`
- `extra = 0` (do not show blank add rows by default)
- `can_delete = False` (community memberships should not be deleted from admin; use the reject/suspend flow instead)

#### VendorAdmin

Register `Vendor` with `@admin.register(Vendor)` (or `admin.site.register(Vendor, VendorAdmin)`).

**`list_display`:** `display_name`, `user`, `fssai_status`, `razorpay_account_status`, `bank_account_verified`, `average_rating`, `is_new_seller`

Note: `is_new_seller` is a property on the model, not a database field. Django admin can call properties as list_display items directly.

**`list_filter`:** `fssai_status`, `razorpay_account_status`

**`search_fields`:** `display_name`, `user__phone`, `fssai_number`, `gstin`

The `user__phone` lookup assumes the related `User` model has a `phone` field (established in split 01-foundation).

**`readonly_fields`:** `fssai_verified_at`, `razorpay_account_id`, `razorpay_onboarding_step`, `created_at`, `updated_at`

These fields are populated by automated processes (Celery tasks, webhooks) and must not be editable from the admin form.

**`inlines`:** `[VendorCommunityInline]`

#### VendorCommunityAdmin (standalone)

Also register `VendorCommunity` as a standalone admin class so operators can filter the full approval queue across all vendors and communities in one list view.

**`list_display`:** `vendor`, `community`, `status`, `approved_by`, `approved_at`, `missed_window_count`, `delist_threshold`

**`list_filter`:** `status`, `community`

**`readonly_fields`:** `approved_by`, `approved_at`

No custom actions are needed for MVP; the approval workflow is handled through the API endpoints.

### Code Skeleton

```python
# apps/vendors/admin.py

from django.contrib import admin
from .models import Vendor, VendorCommunity


class VendorCommunityInline(admin.TabularInline):
    """Inline showing all community approval records for a vendor."""
    model = VendorCommunity
    fields = ('community', 'status', 'approved_by', 'approved_at',
              'missed_window_count', 'delist_threshold')
    readonly_fields = ('approved_by', 'approved_at')
    extra = 0
    can_delete = False


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    """Admin for the Vendor model with KYB/FSSAI/Razorpay read-only fields."""
    list_display = (
        'display_name', 'user', 'fssai_status',
        'razorpay_account_status', 'bank_account_verified',
        'average_rating', 'is_new_seller',
    )
    list_filter = ('fssai_status', 'razorpay_account_status')
    search_fields = ('display_name', 'user__phone', 'fssai_number', 'gstin')
    readonly_fields = (
        'fssai_verified_at', 'razorpay_account_id',
        'razorpay_onboarding_step', 'created_at', 'updated_at',
    )
    inlines = [VendorCommunityInline]


@admin.register(VendorCommunity)
class VendorCommunityAdmin(admin.ModelAdmin):
    """Standalone admin for VendorCommunity; full cross-community approval queue."""
    list_display = (
        'vendor', 'community', 'status', 'approved_by',
        'approved_at', 'missed_window_count', 'delist_threshold',
    )
    list_filter = ('status', 'community')
    readonly_fields = ('approved_by', 'approved_at')
```

### Key Points

- `is_new_seller` is a model property. Django admin supports callables and properties in `list_display` without any extra annotation for read-only display. However, the column header defaults to the property name (`is_new_seller`). If a friendlier label is desired, wrap it in a method on `VendorAdmin` with `short_description` set, but this is optional for MVP.
- `razorpay_onboarding_step` should be `readonly_fields` because it is a guard field managed by the Celery task in section-09. Editing it manually could break the step-resume logic.
- `fssai_number` is intentionally **not** in `readonly_fields` — operators may need to correct a mistyped number before re-triggering the `verify_fssai` task.
- `VendorCommunity.can_delete = False` in the inline enforces the invariant that community membership records are never silently deleted; status transitions (`rejected`, `suspended`) are the correct removal mechanism.

## Summary Checklist

- [ ] `apps/vendors/admin.py` created
- [ ] `VendorCommunityInline` (TabularInline) with `model = VendorCommunity`, correct `fields`, `readonly_fields`, `extra = 0`, `can_delete = False`
- [ ] `VendorAdmin` registered with `@admin.register(Vendor)`
  - [ ] `list_display` includes all 7 columns (including `is_new_seller` property)
  - [ ] `list_filter` on `fssai_status`, `razorpay_account_status`
  - [ ] `search_fields` includes `display_name`, `user__phone`, `fssai_number`, `gstin`
  - [ ] `readonly_fields` includes `fssai_verified_at`, `razorpay_account_id`, `razorpay_onboarding_step`, `created_at`, `updated_at`
  - [ ] `inlines = [VendorCommunityInline]`
- [ ] `VendorCommunityAdmin` registered with `@admin.register(VendorCommunity)`
  - [ ] `list_display` includes all 7 columns
  - [ ] `list_filter` on `status`, `community`
  - [ ] `readonly_fields` includes `approved_by`, `approved_at`
- [ ] `apps/vendors/tests/test_admin.py` created with 3 test stubs
  - [ ] `test_vendor_admin_is_registered`
  - [ ] `test_vendor_community_list_display_renders`
  - [ ] `test_vendor_search_by_fssai_number`