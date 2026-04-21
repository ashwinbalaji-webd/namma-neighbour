Now I have all the context needed. Let me generate the section content.

# Section 06: URL Configuration and Permissions Wiring

## Overview

This section wires all community views into their URL patterns and ensures the permission guard helper is in place. It depends on sections 03, 04, and 05 (all views must exist before URLs can be wired). Section 08 (tests) depends on this section being complete.

**Files to create or modify:**
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/communities/urls.py` — create
- `/var/www/html/MadGirlfriend/namma-neighbour/config/urls.py` — modify to include community URLs
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/communities/views.py` — add `get_community_or_403` helper

---

## Dependencies

- **section-03-community-views**: `CommunityRegisterView`, `CommunityDetailView`, `BuildingListView`
- **section-04-join-approval-views**: `JoinCommunityView`, `ResidentListView`, `ResidentApproveView`, `ResidentRejectView`
- **section-05-admin-views**: `CommunitySettingsView`, `InviteRegenerateView`
- `apps/core/permissions.py`: `IsCommunityAdmin` (from split 01)

---

## Tests First

These tests come from `claude-plan-tdd.md` Section 4 (URL Configuration) and Section 5 (Permissions).

### URL Resolution Tests

File: `apps/communities/tests/test_views.py` (or a dedicated `test_urls.py`)

```python
class TestURLResolution:
    """All URL patterns resolve to the correct view class and support reverse lookup."""

    def test_register_url_resolves(self):
        """reverse('communities:register') resolves to CommunityRegisterView."""

    def test_join_url_resolves(self):
        """reverse('communities:join') resolves to JoinCommunityView."""

    def test_community_detail_url_resolves(self):
        """reverse('communities:detail', kwargs={'slug': 'test-slug'}) resolves correctly."""

    def test_buildings_url_resolves(self):
        """reverse('communities:buildings', kwargs={'slug': 'test-slug'}) resolves correctly."""

    def test_settings_url_resolves(self):
        """reverse('communities:settings', kwargs={'slug': 'test-slug'}) resolves correctly."""

    def test_invite_regenerate_url_resolves(self):
        """reverse('communities:invite-regenerate', kwargs={'slug': 'test-slug'}) resolves."""

    def test_residents_list_url_resolves(self):
        """reverse('communities:resident-list', kwargs={'slug': 'test-slug'}) resolves."""

    def test_resident_approve_url_resolves(self):
        """reverse('communities:resident-approve', kwargs={'slug': 'test-slug', 'pk': 1}) resolves."""

    def test_resident_reject_url_resolves(self):
        """reverse('communities:resident-reject', kwargs={'slug': 'test-slug', 'pk': 1}) resolves."""
```

### Permission Guard Tests

These tests verify the cross-community admin guard (`get_community_or_403`).

```python
class TestCommunityAdminGuard:
    """Community admin of community A cannot act on community B's endpoints."""

    def test_admin_can_access_own_community_residents(self, api_client, community_admin_token):
        """Admin of community A gets 200 on GET /{slug_A}/residents/."""

    def test_admin_blocked_from_other_community_residents(self, api_client, community_admin_token, other_community):
        """Admin of community A gets 403 on GET /{slug_B}/residents/."""

    def test_admin_blocked_from_other_community_approve(self, api_client, community_admin_token, other_community, other_resident):
        """Admin of community A gets 403 on POST /{slug_B}/residents/{id}/approve/."""

    def test_admin_blocked_from_other_community_settings(self, api_client, community_admin_token, other_community):
        """Admin of community A gets 403 on PATCH /{slug_B}/settings/."""

    def test_admin_blocked_from_other_community_invite_regenerate(self, api_client, community_admin_token, other_community):
        """Admin of community A gets 403 on POST /{slug_B}/invite/regenerate/."""
```

### `IsCommunityAdmin` Permission Class Tests

```python
class TestIsCommunityAdminPermission:
    """Unit tests for the IsCommunityAdmin permission class from apps/core/permissions.py."""

    def test_allows_admin_with_correct_community_in_jwt(self):
        """JWT with roles=['community_admin'] and correct community_id passes."""

    def test_blocks_user_without_community_admin_role(self):
        """JWT with roles=['resident'] is rejected with 403."""

    def test_blocks_unauthenticated_request(self):
        """Request with no JWT is rejected with 401."""

    def test_blocks_admin_with_mismatched_community_id(self):
        """JWT with community_admin role but community_id != community.id → 403."""
```

### AnonRateThrottle Tests

```python
class TestPublicEndpointThrottling:
    """AnonRateThrottle is applied to public endpoints."""

    def test_community_detail_has_anon_throttle(self):
        """GET /{slug}/ view has AnonRateThrottle in its throttle_classes."""

    def test_buildings_list_has_no_auth_requirement(self):
        """GET /{slug}/buildings/ is accessible without authentication."""
```

---

## Implementation Details

### `apps/communities/urls.py`

Create this file from scratch. It should import all view classes from `apps.communities.views` and wire them to their URL patterns.

The complete URL pattern table:

| URL Pattern | View Class | Name |
|---|---|---|
| `register/` | `CommunityRegisterView` | `register` |
| `join/` | `JoinCommunityView` | `join` |
| `<slug:slug>/` | `CommunityDetailView` | `detail` |
| `<slug:slug>/buildings/` | `BuildingListView` | `buildings` |
| `<slug:slug>/settings/` | `CommunitySettingsView` | `settings` |
| `<slug:slug>/invite/regenerate/` | `InviteRegenerateView` | `invite-regenerate` |
| `<slug:slug>/residents/` | `ResidentListView` | `resident-list` |
| `<slug:slug>/residents/<int:pk>/approve/` | `ResidentApproveView` | `resident-approve` |
| `<slug:slug>/residents/<int:pk>/reject/` | `ResidentRejectView` | `resident-reject` |

Use Django's `path()` with `<slug:slug>` for the slug parameter (not `<str:slug>`) — this rejects strings with slashes and other characters that are not valid URL slugs.

The `app_name` variable must be set to `'communities'` at the top of `urls.py` to enable the namespace.

Stub signature:

```python
# apps/communities/urls.py
from django.urls import path
from . import views

app_name = 'communities'

urlpatterns = [
    # ... path() entries for each view
]
```

### `config/urls.py`

Add the include statement. The communities URLs must be mounted at `api/v1/communities/`. Pass the namespace via the `include()` call as the second element of the tuple, or rely on `app_name` in `urls.py` (both approaches work; the `app_name` in `urls.py` approach is preferred to avoid duplication).

```python
path('api/v1/communities/', include('apps.communities.urls')),
```

If `config/urls.py` already has an `api/v1/` prefix block, add the communities include inside it. Do not create a duplicate `api/v1/` mount.

### `get_community_or_403` Helper in Views

This helper must be available to all slug-based admin views (`ResidentListView`, `ResidentApproveView`, `ResidentRejectView`, `CommunitySettingsView`, `InviteRegenerateView`). It should be defined as a module-level function (not a mixin method) in `apps/communities/views.py` so any view can call it without inheritance.

```python
def get_community_or_403(slug: str, request) -> "Community":
    """
    Look up Community by slug. If the requesting user's JWT community_id does not
    match the community's pk, raise PermissionDenied (403).

    Returns the Community instance on success.
    Raises Http404 if no community with that slug exists.
    Raises PermissionDenied if the JWT community_id does not match.
    """
```

The check logic:
1. Fetch community by `slug` — raise `Http404` if not found.
2. Read `community_id` from `request.auth.payload['community_id']`.
3. If `community.id != community_id`, raise `PermissionDenied`.
4. Return the community.

This must be called at the start of every admin endpoint handler, before any data access. Views that already have `IsCommunityAdmin` in `permission_classes` still need this secondary guard — `IsCommunityAdmin` only checks that the JWT role is `community_admin`; it does not verify which community the slug belongs to.

### `AnonRateThrottle` Configuration

`CommunityDetailView` must declare `throttle_classes = [AnonRateThrottle]`. Import from `rest_framework.throttling`.

The default throttle rate for `AnonRateThrottle` is configured in Django settings under `REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['anon']`. Confirm this key exists in `config/settings/base.py` (or equivalent). If missing, add a sensible default:

```python
REST_FRAMEWORK = {
    ...
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
    },
}
```

Do not set `throttle_classes` on `BuildingListView` — this endpoint is purely read-only metadata and need not be throttled for anonymous users at the MVP stage.

---

## Actual Implementation Notes

### Files Modified
- `apps/communities/tests/test_views.py` — added TestURLResolution (9), TestCommunityAdminGuard (6), TestIsCommunityAdminPermission (3), TestPublicEndpointThrottling (2) = 20 new tests
- `apps/communities/tests/conftest.py` — added `community_admin_token`, `other_resident` fixtures
- `apps/communities/views.py` — added `IsAuthenticated` to ResidentListView, ResidentApproveView, ResidentRejectView for consistent 401 on unauthenticated

### Deviations from Plan
- All URL patterns, config/urls.py include, get_community_or_403, and AnonRateThrottle were already wired in sections 03-05. Section 06 added only tests and auth consistency fix.
- `test_blocks_admin_with_mismatched_community_id` placed in TestCommunityAdminGuard (not TestIsCommunityAdminPermission) because the check lives in get_community_or_403, not IsCommunityAdmin itself.
- Added `IsAuthenticated` to 3 older resident views for consistent 401 behavior.

### Test Results
107 passed, 2 xfailed (Django admin smoke tests pending section 07).

## Verification Checklist

After completing this section, confirm:

1. [x] `uv run python manage.py check` passes with no errors
2. [x] `django.urls.reverse('communities:register')` returns `/api/v1/communities/register/`
3. [x] `django.urls.reverse('communities:resident-approve', kwargs={'slug': 'x', 'pk': 1})` returns `/api/v1/communities/x/residents/1/approve/`
4. [x] All URL resolution tests pass
5. [x] No circular imports