Now I have all the context I need. I can generate the section content for `section-05-admin-views`.

# Section 05: Admin Views (`CommunitySettingsView` + `InviteRegenerateView`)

## Overview

This section implements two community-management endpoints that only the community admin can call:

- `CommunitySettingsView` — `PATCH /{slug}/settings/` — update commission percentage, add buildings, deactivate the community.
- `InviteRegenerateView` — `POST /{slug}/invite/regenerate/` — rotate the invite code.

Both endpoints sit behind `IsCommunityAdmin` AND a secondary community-ownership guard to prevent an admin of community A from acting on community B.

## Dependencies

- **section-01-models-migration** must be complete: `Community`, `Building`, `ResidentProfile` models and migration.
- **section-02-serializers** must be complete: `CommunityRegistrationSerializer`, `BuildingSerializer`, and related serializers are referenced (or their patterns are reused) here.

Do not re-read those sections; assume their contracts are met.

---

## Tests First

Extract from `apps/communities/tests/test_views.py`. Write these tests before implementing the views.

### `CommunitySettingsView` tests

```python
class TestCommunitySettingsView:
    """Tests for PATCH /{slug}/settings/"""

    def test_admin_updates_commission_pct(self, api_client, community_with_buildings, admin_user):
        """Community admin PATCHes commission_pct → value saved, 200 returned."""

    def test_admin_adds_new_buildings(self, api_client, community_with_buildings, admin_user):
        """Admin sends a list of new building names → Building rows created for the community."""

    def test_admin_deactivates_community(self, api_client, community_with_buildings, admin_user):
        """Admin sets is_active=False → community.is_active becomes False."""

    def test_non_admin_gets_403(self, api_client, community_with_buildings, resident_user):
        """Non-admin user → 403 Forbidden."""

    def test_adding_duplicate_building_name_silently_ignored(
        self, api_client, community_with_buildings, admin_user
    ):
        """Adding a building name that already exists → no error, no duplicate row created."""

    def test_building_removal_not_supported(self, api_client, community_with_buildings, admin_user):
        """Any attempt to remove a building via this endpoint → 400 with clear error message."""

    def test_wrong_community_admin_gets_403(self, api_client, other_community, admin_user):
        """Admin of community A cannot update settings of community B → 403."""

    def test_unauthenticated_gets_401(self, api_client, community_with_buildings):
        """No auth token → 401."""
```

### `InviteRegenerateView` tests

```python
class TestInviteRegenerateView:
    """Tests for POST /{slug}/invite/regenerate/"""

    def test_admin_gets_new_invite_code(self, api_client, community_with_buildings, admin_user):
        """Admin calls endpoint → response contains new invite_code, DB is updated."""

    def test_new_code_is_6_char_uppercase_alphanumeric(
        self, api_client, community_with_buildings, admin_user
    ):
        """New invite_code is exactly 6 uppercase alphanumeric characters."""

    def test_old_code_no_longer_works_for_join(
        self, api_client, community_with_buildings, admin_user
    ):
        """After regeneration, using the old invite_code in POST /join/ returns 404."""

    def test_non_admin_gets_403(self, api_client, community_with_buildings, resident_user):
        """Non-admin → 403."""

    def test_wrong_community_admin_gets_403(self, api_client, other_community, admin_user):
        """Admin of community A cannot regenerate invite code of community B → 403."""

    def test_unauthenticated_gets_401(self, api_client, community_with_buildings):
        """No auth token → 401."""
```

### Django Admin smoke tests (live in `apps/communities/tests/test_views.py` or a dedicated `test_admin.py`)

```python
class TestDjangoAdminCommunitySettingsActions:
    """Smoke tests to verify admin list page loads and custom actions fire."""

    def test_mark_as_reviewed_action(self, admin_client, community):
        """'Mark as reviewed' admin action sets is_reviewed=True on selected communities."""

    def test_approve_selected_residents_action(self, admin_client, pending_resident_profile):
        """'Approve selected' admin action on ResidentProfile sets status=APPROVED."""
```

---

## Implementation

### File to create / modify

`apps/communities/views.py` — add the two new view classes alongside the views from sections 03 and 04.

### Permissions guard helper

Both views share the same pattern for preventing cross-community access. A helper should be defined once (either as a mixin or a standalone function) and reused:

```python
def get_community_or_403(slug, request):
    """
    Look up Community by slug. Raise PermissionDenied if the requesting user's
    JWT community_id does not match the community's pk.

    Returns the Community instance on success.
    Raises Http404 if no community matches the slug.
    Raises PermissionDenied if community_id in JWT != community.pk.
    """
```

The JWT community_id is read from `request.auth.payload['community_id']`. This guard is in addition to (not a replacement for) the `IsCommunityAdmin` permission class declared on the view.

### `CommunitySettingsView`

**File:** `apps/communities/views.py`

**URL:** `PATCH /{slug}/settings/`

**Permission classes:** `[IsAuthenticated, IsCommunityAdmin]`

```python
class CommunitySettingsView(APIView):
    """
    PATCH /{slug}/settings/

    Allowed updates:
    - commission_pct (Decimal)
    - buildings (list[str]) — adds new buildings; duplicates silently ignored
    - is_active (bool) — deactivation only (set to False)

    Building removal is intentionally NOT supported. Any payload key that
    implies removal must return 400 with a descriptive error.

    Uses bulk_create(ignore_conflicts=True) for new buildings.
    """
    permission_classes = [IsAuthenticated, IsCommunityAdmin]

    def patch(self, request, slug):
        ...
```

Key implementation notes:

- Call `get_community_or_403(slug, request)` at the top of `patch()` before processing the payload.
- Extract `buildings` from `request.data` with `.pop('buildings', None)`. If present and non-empty, call `Building.objects.bulk_create([Building(community=community, name=n) for n in buildings], ignore_conflicts=True)`. This silently absorbs duplicate-name collisions.
- If the payload contains a key that semantically maps to building removal (e.g., `remove_buildings`), return `Response({"error": "Building removal is not supported"}, status=400)` immediately.
- `commission_pct` and `is_active` are updated directly on the `Community` instance with `save(update_fields=[...])` — never call bare `save()` (it would recalculate `invite_code`/`slug` side effects if any are coded on `save()`).
- Return the updated community fields in the response (200). You may reuse `CommunityDetailSerializer` extended with admin fields, or return a simple dict — be consistent with what the frontend needs.

### `InviteRegenerateView`

**File:** `apps/communities/views.py`

**URL:** `POST /{slug}/invite/regenerate/`

**Permission classes:** `[IsAuthenticated, IsCommunityAdmin]`

```python
class InviteRegenerateView(APIView):
    """
    POST /{slug}/invite/regenerate/

    Generates a new 6-character uppercase alphanumeric invite code,
    persists it, and returns it in the response.

    The old code immediately becomes invalid for new joins.
    """
    permission_classes = [IsAuthenticated, IsCommunityAdmin]

    def post(self, request, slug):
        ...
```

Key implementation notes:

- Call `get_community_or_403(slug, request)` first.
- Generate the new code using the same logic as the `Community` model's auto-generation (import and reuse the utility function from `models.py` rather than copy-pasting). The code must be 6 characters, uppercase, alphanumeric, and unique across all communities. Handle collision by retrying in a loop.
- Update with `Community.objects.filter(pk=community.pk).update(invite_code=new_code)` — use a targeted update to avoid triggering full-model save side effects.
- Return `{"invite_code": new_code}` with HTTP 200.

---

## Serializer notes

No new serializers are needed for these two views. The existing pieces from section 02 are sufficient:

- `CommunitySettingsView` can return a trimmed dict or a lightly extended serializer.
- `InviteRegenerateView` returns a one-field dict `{"invite_code": "..."}`.

If a `CommunitySettingsSerializer` is added to `apps/communities/serializers.py` for validation of the PATCH payload (recommended), it should:
- Declare `commission_pct` as optional `DecimalField(max_digits=5, decimal_places=2)`
- Declare `buildings` as optional `ListField(child=CharField(max_length=50), required=False)`
- Declare `is_active` as optional `BooleanField(required=False)`
- In `validate`, reject any `remove_buildings` key explicitly

---

## Actual Implementation Notes

### Files Created/Modified
- `apps/communities/views.py` — added `CommunitySettingsView`, `InviteRegenerateView`; updated imports to include `_generate_invite_code`, `CommunitySettingsSerializer`
- `apps/communities/serializers.py` — added `CommunitySettingsSerializer` with `min_value=0, max_value=100` on `commission_pct` and `validate()` that rejects `remove_buildings`
- `apps/communities/urls.py` — added `<slug>/settings/` and `<slug>/invite/regenerate/` URL patterns
- `apps/communities/tests/test_views.py` — added `TestCommunitySettingsView` (8 tests), `TestInviteRegenerateView` (6 tests), `TestDjangoAdminCommunitySettingsActions` (2 xfail smoke tests)
- `apps/communities/tests/conftest.py` — added `admin_user`, `resident_user`, `other_community`, `pending_resident_profile` fixtures

### Deviations from Plan
- `remove_buildings` rejection is in `CommunitySettingsSerializer.validate()` (not view-level early return as plan showed) — cleaner, serializer is the canonical guard
- `is_active` allows both True and False (plan said deactivation-only) — user confirmed allow both directions
- `commission_pct` has `min_value=0, max_value=100` added (plan didn't specify) — user requested
- Response includes `buildings` list (plan didn't specify) — added for frontend confirmation

### Test Results
87 passed, 2 xfailed (Django admin smoke tests pending section 07 admin registration).

## Checklist

- [x] `get_community_or_403` helper defined and shared between both views (not duplicated)
- [x] `CommunitySettingsView.patch()` calls the helper, handles `buildings` via `bulk_create(ignore_conflicts=True)`, and uses `save(update_fields=[...])` for scalar field updates
- [x] `InviteRegenerateView.post()` calls the helper, reuses invite-code generation logic from `models.py`, updates with a targeted queryset `.update()` call
- [x] Both views declare `permission_classes = [IsAuthenticated, IsCommunityAdmin]`
- [x] All test stubs written before implementation
- [x] Tests cover: admin success, non-admin 403, wrong-community 403, unauthenticated 401, duplicate building ignored, old invite code invalidated