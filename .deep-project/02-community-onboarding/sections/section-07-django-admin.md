Now I have all the context needed. Let me generate the section content.

# Section 07: Django Admin

## Overview

This section configures the Django admin interface for the `Community` and `ResidentProfile` models. It depends only on **section-01-models-migration** (the models must exist), and it runs in parallel with sections 02–05. The file to create is `/var/www/html/MadGirlfriend/namma-neighbour/apps/communities/admin.py`.

## Dependencies

- **section-01-models-migration** must be complete: `Community`, `Building`, `Flat`, and `ResidentProfile` models must exist and be migrated.
- No dependency on serializers or views.

## Tests

Tests for this section are smoke tests that run through the Django admin machinery. They live in `apps/communities/tests/test_views.py` (or a dedicated `test_admin.py` if preferred — the test command is `uv run pytest apps/communities/`).

Required test cases (from `claude-plan-tdd.md`, Section 6):

- `Community` list page loads with custom display columns (smoke test via `admin_client.get(...)`)
- "Mark as reviewed" action sets `is_reviewed=True` on selected communities
- "Approve selected" action on `ResidentProfile` sets `status=APPROVED`
- `BuildingInline` renders on Community change page (smoke test)

### Test Stubs

```python
# apps/communities/tests/test_admin.py

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from apps.communities.admin import CommunityAdmin, ResidentProfileAdmin
from apps.communities.models import Community, ResidentProfile

@pytest.mark.django_db
class TestCommunityAdmin:
    def test_list_page_loads(self, admin_client, community_with_buildings):
        """Smoke test: community changelist loads without error."""
        ...

    def test_mark_as_reviewed_action(self, admin_client, community_with_buildings):
        """Selecting 'Mark as reviewed' sets is_reviewed=True on target communities."""
        ...

    def test_building_inline_renders(self, admin_client, community_with_buildings):
        """Community change page renders BuildingInline rows."""
        ...

    def test_deactivate_action(self, admin_client, community_with_buildings):
        """Selecting 'Deactivate selected communities' sets is_active=False."""
        ...

    def test_regenerate_invite_codes_action(self, admin_client, community_with_buildings):
        """Regenerate invite codes action assigns a new 6-char uppercase code."""
        ...


@pytest.mark.django_db
class TestResidentProfileAdmin:
    def test_approve_selected_action(self, admin_client, community_with_buildings):
        """'Approve selected' sets status=APPROVED on chosen ResidentProfile rows."""
        ...

    def test_reject_selected_action(self, admin_client, community_with_buildings):
        """'Reject selected' sets status=REJECTED; records are not deleted."""
        ...
```

The `admin_client` fixture is provided by `pytest-django`. The `community_with_buildings` and `approved_resident` fixtures will be defined in `apps/communities/tests/conftest.py` (see section-08-tests).

## Implementation

### File to Create

`/var/www/html/MadGirlfriend/namma-neighbour/apps/communities/admin.py`

### Community Admin

Register `Community` with a custom `ModelAdmin`. The admin must include:

**List display columns:** `name`, `city`, `pincode`, `admin_user`, `resident_count`, `vendor_count`, `is_active`, `is_reviewed`

**List filters (sidebar):** `is_active`, `is_reviewed`, `city`

**Search fields:** `name`, `city`, `pincode`, `admin_user__phone` (assuming the `User` model uses a `phone` field)

**Inline:** `BuildingInline` — a `TabularInline` for the `Building` model. Fields to show: `name`. Allow adding new buildings inline but do not allow deletion (deletion must be handled carefully — see section-05-admin-views for the removal constraint). Set `extra = 1`.

**Custom admin actions** (all defined as methods on the `ModelAdmin` class and added to `actions = [...]`):

1. `deactivate_communities` — sets `is_active=False` on selected queryset via `.update(is_active=False)`. Short description: `"Deactivate selected communities"`.
2. `mark_as_reviewed` — sets `is_reviewed=True` on selected queryset via `.update(is_reviewed=True)`. Short description: `"Mark as reviewed"`.
3. `regenerate_invite_codes` — iterates over selected communities and calls the invite code generation logic (same logic as in `Community.save()` — generate a new 6-char uppercase alphanumeric string and save). Short description: `"Regenerate invite codes"`. Each community must get a unique code; handle collision with retry logic consistent with the model's own generation.

**Read-only fields on change form:** `invite_code`, `slug`, `resident_count`, `vendor_count`, `created_at`, `updated_at` (these should not be directly editable in the admin form).

**Fieldsets** (optional but recommended for clarity):

- "Community Info": `name`, `slug`, `city`, `pincode`, `address`
- "Admin": `admin_user`, `is_active`, `is_reviewed`
- "Invite": `invite_code`
- "Metrics": `resident_count`, `vendor_count`, `commission_pct`

### ResidentProfile Admin

Register `ResidentProfile` with a custom `ModelAdmin`. The admin must include:

**List display columns:** `user` (shows phone number — relies on `User.__str__`), `community`, `flat`, `user_type`, `status`, `joined_at`

**List filters (sidebar):** `status`, `community`, `user_type`

**Search fields:** `user__phone`, `community__name`, `flat__flat_number`

**Read-only fields:** `joined_at`, `user` — these must never be editable from the admin panel.

**Custom admin actions:**

1. `approve_selected` — sets `status='APPROVED'` on selected queryset via `.update(status='APPROVED')`. Short description: `"Approve selected residents"`.
2. `reject_selected` — sets `status='REJECTED'` on selected queryset via `.update(status='REJECTED')`. Short description: `"Reject selected residents"`. Records are **not deleted** — only the status field changes.

**Important:** Do not provide a "Delete selected" action for `ResidentProfile`. Override `has_delete_permission` to return `False` to enforce the "REJECTED records are never deleted" invariant at the admin layer.

### Building Admin (optional inline only)

`Building` is accessed only via the `BuildingInline` on `Community`. You do not need a standalone `Building` registration unless desired for debugging. If registered standalone, keep it minimal.

### Code Skeleton

```python
# apps/communities/admin.py

import secrets
import string
from django.contrib import admin
from .models import Community, Building, Flat, ResidentProfile


class BuildingInline(admin.TabularInline):
    """Inline for viewing/adding buildings on the Community change page."""
    model = Building
    fields = ('name',)
    extra = 1
    # do not allow deletion via inline to protect the removal constraint


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    """Admin for Community model with custom actions and BuildingInline."""
    list_display = (...)
    list_filter = (...)
    search_fields = (...)
    readonly_fields = (...)
    inlines = [BuildingInline]
    actions = ['deactivate_communities', 'mark_as_reviewed', 'regenerate_invite_codes']

    def deactivate_communities(self, request, queryset):
        """Set is_active=False on all selected communities."""
        ...
    deactivate_communities.short_description = "Deactivate selected communities"

    def mark_as_reviewed(self, request, queryset):
        """Set is_reviewed=True on all selected communities."""
        ...
    mark_as_reviewed.short_description = "Mark as reviewed"

    def regenerate_invite_codes(self, request, queryset):
        """Generate new unique 6-char uppercase invite codes for selected communities."""
        ...
    regenerate_invite_codes.short_description = "Regenerate invite codes"


@admin.register(ResidentProfile)
class ResidentProfileAdmin(admin.ModelAdmin):
    """Admin for ResidentProfile; approval/rejection actions, no deletion allowed."""
    list_display = (...)
    list_filter = (...)
    search_fields = (...)
    readonly_fields = ('joined_at', 'user')
    actions = ['approve_selected', 'reject_selected']

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of ResidentProfile records from admin."""
        return False

    def approve_selected(self, request, queryset):
        """Set status=APPROVED on selected resident profiles."""
        ...
    approve_selected.short_description = "Approve selected residents"

    def reject_selected(self, request, queryset):
        """Set status=REJECTED on selected resident profiles."""
        ...
    reject_selected.short_description = "Reject selected residents"
```

### Invite Code Regeneration Logic

The `regenerate_invite_codes` action must produce a unique code for each community. Since admin actions operate on a queryset and uniqueness across the table is required, the implementation must:

1. For each community in the queryset, generate a candidate 6-char uppercase alphanumeric string using `random.choices(string.ascii_uppercase + string.digits, k=6)`.
2. Check for collision with `Community.objects.filter(invite_code=candidate).exclude(pk=community.pk).exists()`.
3. Retry up to a reasonable limit (e.g., 10 attempts) before raising an admin error message.
4. Save the new `invite_code` directly on the model instance.

Do not call `Community.save()` blindly — to avoid triggering unrelated `save()` side effects, use `Community.objects.filter(pk=community.pk).update(invite_code=new_code)`.

## Admin Registration in apps.py

Ensure `apps/communities/apps.py` has the correct `default_auto_field` and that the app label is `communities`. The `admin.py` is auto-discovered by Django; no manual import is needed as long as `INSTALLED_APPS` contains `'apps.communities'`.

## Implementation Notes (actual build)

### Files created/modified
- `namma_neighbor/apps/communities/admin.py` — full implementation
- `namma_neighbor/apps/communities/tests/test_admin.py` — 7 tests (all pass)

### Deviations from plan
- `joined_at` field does not exist on `ResidentProfile`; used `created_at` (from `TimestampedModel`) instead. Plan spec had a bug.
- `regenerate_invite_codes` uses `_generate_invite_code()` from models (crypto-secure via `secrets.choice`) instead of `random.choices` as the plan's prose suggested. The plan's skeleton correctly imported `secrets`; prose section was wrong.
- Invite code regeneration wraps `.update()` in `try/except IntegrityError` (TOCTOU-safe) rather than a Python-side exists-check + update.
- `admin_client` test fixture defined locally in `test_admin.py` (not from pytest-django) because the custom User model uses `phone` as `USERNAME_FIELD` — pytest-django's built-in would fail trying `create_superuser(username=...)`.
- `ResidentProfileAdmin.readonly_fields` includes `updated_at` (added during review — also provided by `TimestampedModel`).

## Summary Checklist

- [x] `BuildingInline` (TabularInline) with `model = Building`, `fields = ('name',)`, `extra = 1`
- [x] `CommunityAdmin` registered with `@admin.register(Community)`
  - [x] `list_display` includes all 8 columns
  - [x] `list_filter` on `is_active`, `is_reviewed`, `city`
  - [x] `readonly_fields` includes `invite_code`, `slug`, counter fields, timestamps
  - [x] `inlines = [BuildingInline]`
  - [x] `deactivate_communities` action (`.update(is_active=False)`)
  - [x] `mark_as_reviewed` action (`.update(is_reviewed=True)`)
  - [x] `regenerate_invite_codes` action (crypto-secure, collision-safe via IntegrityError retry)
- [x] `ResidentProfileAdmin` registered with `@admin.register(ResidentProfile)`
  - [x] `list_display` includes 6 columns (uses `created_at` not `joined_at`)
  - [x] `list_filter` on `status`, `community`, `user_type`
  - [x] `readonly_fields = ('created_at', 'updated_at', 'user')`
  - [x] `has_delete_permission` returns `False`
  - [x] `approve_selected` action (`.update(status='APPROVED')`)
  - [x] `reject_selected` action (`.update(status='REJECTED')`)
- [x] Test file `apps/communities/tests/test_admin.py` with 7 fully-implemented tests