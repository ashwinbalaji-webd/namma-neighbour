Now I have all the context needed. Let me generate the section content.

# Section 08: Tests

## Overview

This section covers the complete test suite for the 02-Community Onboarding split. It depends on all prior sections being complete:

- **section-01-models-migration**: Models and migration must exist
- **section-02-serializers**: Serializers must exist
- **section-03-community-views**: Register, detail, and building list views must exist
- **section-04-join-approval-views**: Join, resident list, approve/reject views must exist
- **section-05-admin-views**: Settings and invite regenerate views must exist
- **section-06-urls-permissions**: URL routing and permissions must be wired
- **section-07-django-admin**: Django admin registrations must exist

Test command (from project config): `uv run pytest apps/communities/`

---

## Files to Create

```
apps/communities/tests/
├── __init__.py
├── factories.py
├── conftest.py
├── test_models.py
└── test_views.py
```

---

## Dependencies and Imports

The testing stack uses:

- `pytest-django` — Django test runner integration
- `factory_boy` — Model factories
- `rest_framework.test.APIClient` — DRF API test client
- `freezegun` — Time freezing (for `joined_at` assertions)
- `rest_framework_simplejwt.tokens.AccessToken` — JWT payload inspection

---

## 1. Factories (`apps/communities/tests/factories.py`)

Update `CommunityFactory` from the split-01 stub. Add `BuildingFactory`, `FlatFactory`, and `ResidentProfileFactory`.

**Key factory design notes:**

- `CommunityFactory.invite_code`: Use `factory.LazyAttribute` to generate a 6-char uppercase alphanumeric string (e.g., `random.choices(string.ascii_uppercase + string.digits, k=6)`).
- `CommunityFactory.slug`: Use `factory.LazyAttribute` derived from `slugify(name + '-' + city)`.
- `ResidentProfileFactory` defaults `status='APPROVED'` so fixtures represent fully onboarded residents by default. Pass `status='PENDING'` explicitly when testing the approval flow.
- `BuildingFactory.community`: `factory.SubFactory(CommunityFactory)`.
- `FlatFactory.building`: `factory.SubFactory(BuildingFactory)`.
- `ResidentProfileFactory.community`: points to the same community as its flat's building.

### Stub signatures

```python
class CommunityFactory(factory.django.DjangoModelFactory):
    """Factory for Community. invite_code is auto-generated uppercase."""
    class Meta:
        model = 'communities.Community'

class BuildingFactory(factory.django.DjangoModelFactory):
    """Factory for Building linked to a CommunityFactory."""
    class Meta:
        model = 'communities.Building'

class FlatFactory(factory.django.DjangoModelFactory):
    """Factory for Flat linked to a BuildingFactory."""
    class Meta:
        model = 'communities.Flat'

class ResidentProfileFactory(factory.django.DjangoModelFactory):
    """Factory for ResidentProfile. Default status=APPROVED."""
    class Meta:
        model = 'communities.ResidentProfile'
```

---

## 2. Fixtures (`apps/communities/tests/conftest.py`)

Shared pytest fixtures used across test modules:

- `api_client` — an unauthenticated `APIClient` instance.
- `auth_client(user)` — helper that returns an `APIClient` with the given user's JWT in the `Authorization` header.
- `community_with_buildings` — a `Community` with 2-3 `Building` rows and a designated `admin_user` (a `User` with `UserRole(role='community_admin', community=...)`).
- `approved_resident` — a `ResidentProfile(status='APPROVED')` linked to `community_with_buildings`, with the user's `active_community` set.
- `pending_resident` — same as above but `status='PENDING'`.

All fixtures should be function-scoped (default pytest-django scope) to avoid state leakage between tests.

---

## 3. Model Tests (`apps/communities/tests/test_models.py`)

### 3.1 Community

```python
def test_invite_code_auto_generated_uppercase_on_save():
    """invite_code is set on first save and is uppercase alphanumeric."""

def test_invite_code_collision_retries():
    """If first generated code collides with existing, a new code is generated without surfacing IntegrityError."""

def test_slug_derived_from_name_and_city():
    """slug = slugify(name + '-' + city) on registration."""

def test_slug_collision_appends_numeric_suffix():
    """Second community with same name+city gets slug ending in -2."""

def test_is_reviewed_defaults_false():
    """is_reviewed is False on creation without explicit value."""

def test_resident_count_f_expression_increment():
    """F() update increments resident_count atomically; value in DB is correct after update."""
```

### 3.2 Building

```python
def test_building_unique_together_community_name():
    """Creating two buildings with the same community+name raises IntegrityError."""

def test_building_belongs_to_community():
    """Building.community FK points to the correct community after creation."""
```

### 3.3 Flat

```python
def test_flat_unique_together_building_flat_number():
    """Duplicate building+flat_number raises IntegrityError."""

def test_floor_inference_three_digit():
    """flat_number='304' infers floor=3."""

def test_floor_inference_four_digit():
    """flat_number='1205' infers floor=12."""

def test_floor_inference_non_numeric_returns_none():
    """flat_number='A4' results in floor=None without error."""
```

### 3.4 ResidentProfile

```python
def test_one_to_one_user_raises_on_duplicate():
    """Creating a second ResidentProfile for the same user raises IntegrityError."""

def test_two_profiles_same_flat_both_succeed():
    """Two distinct users can have ResidentProfiles pointing to the same Flat."""

def test_status_defaults_to_pending():
    """status is PENDING on creation without explicit value."""

def test_invalid_user_type_raises():
    """user_type value outside the four choices raises a validation error."""

def test_rejected_record_persists():
    """Updating status to REJECTED does not delete the record; it remains queryable."""
```

---

## 4. View Tests (`apps/communities/tests/test_views.py`)

### 4.1 CommunityRegisterView (`POST /api/v1/communities/register/`)

```python
def test_register_authenticated_returns_201_with_invite_code():
    """Authenticated user registers; response is 201 and contains invite_code."""

def test_register_creates_buildings_matching_input():
    """Number of Building rows created equals the length of the buildings list in payload."""

def test_register_creates_community_admin_role():
    """UserRole(role='community_admin', community=...) is created for the registering user."""

def test_register_sets_active_community_on_user():
    """user.active_community is set to the new community after registration."""

def test_register_response_includes_tokens():
    """Response body contains tokens.access and tokens.refresh."""

def test_register_jwt_payload_has_community_id():
    """Decoded access token has community_id matching the new community's pk."""

def test_register_unauthenticated_returns_401():
    """Unauthenticated request returns 401."""

def test_register_slug_collision_succeeds_with_suffix():
    """Registering a second community with same name+city succeeds; slug ends with -2."""

def test_register_missing_buildings_returns_400():
    """Payload without buildings field (or empty list) returns 400."""
```

### 4.2 CommunityDetailView (`GET /api/v1/communities/{slug}/`)

```python
def test_detail_returns_name_city_slug_is_active():
    """Response contains name, city, slug, is_active fields."""

def test_detail_excludes_sensitive_fields():
    """Response does NOT contain resident_count, commission_pct, invite_code, or admin_user."""

def test_detail_nonexistent_slug_returns_404():
    """Requesting a slug that does not exist returns 404."""

def test_detail_no_auth_required():
    """Unauthenticated request succeeds (200)."""
```

### 4.3 BuildingListView (`GET /api/v1/communities/{slug}/buildings/`)

```python
def test_buildings_returns_list_of_id_and_name():
    """Response is a list of objects each containing id and name."""

def test_buildings_no_auth_required():
    """Unauthenticated request returns 200."""
```

### 4.4 JoinCommunityView (`POST /api/v1/communities/join/`)

```python
def test_join_valid_payload_creates_pending_profile():
    """Valid invite_code + building_id + flat_number creates ResidentProfile with status=PENDING."""

def test_join_increments_resident_count():
    """resident_count on Community is incremented by 1 after a successful join."""

def test_join_response_includes_tokens():
    """Response contains tokens.access and tokens.refresh."""

def test_join_jwt_has_community_id_and_resident_role():
    """Decoded access token has community_id and 'resident' in roles."""

def test_join_sets_active_community_on_user():
    """user.active_community is set to the joined community."""

def test_join_invalid_invite_code_returns_404():
    """Non-existent invite_code returns 404 (not 400)."""

def test_join_same_user_twice_returns_400():
    """Second join attempt by same user returns 400."""

def test_join_two_users_same_flat_both_succeed():
    """Two distinct users joining the same flat_number both receive 201."""

def test_join_same_flat_twice_only_one_flat_row():
    """Two users joining the same flat_number results in exactly one Flat row (get_or_create)."""

def test_join_unauthenticated_returns_401():
    """Unauthenticated request returns 401."""

def test_join_inactive_community_returns_400():
    """Joining a community with is_active=False returns 400."""
```

### 4.5 ResidentListView (`GET /api/v1/communities/{slug}/residents/`)

```python
def test_resident_list_returns_200_for_community_admin():
    """Community admin gets paginated list of residents (200)."""

def test_resident_list_status_filter_pending():
    """?status=PENDING returns only residents with status=PENDING."""

def test_resident_list_returns_403_for_non_admin():
    """Resident (non-admin) receives 403."""

def test_resident_list_wrong_community_admin_returns_403():
    """Admin of community A cannot list residents of community B (403)."""

def test_resident_list_pagination_default_page_size():
    """List respects PAGE_SIZE=20 pagination."""
```

### 4.6 ResidentApproveView / ResidentRejectView

```python
def test_approve_pending_resident_sets_status_approved():
    """Admin POST to approve/ changes status from PENDING to APPROVED (200)."""

def test_reject_pending_resident_sets_status_rejected():
    """Admin POST to reject/ changes status to REJECTED (200)."""

def test_reject_preserves_db_record():
    """After rejection, ResidentProfile still exists in the database."""

def test_approve_nonexistent_profile_returns_404():
    """Approving a profile id that doesn't exist returns 404."""

def test_approve_by_resident_returns_403():
    """Non-admin resident cannot call approve endpoint (403)."""

def test_approve_wrong_community_admin_returns_403():
    """Admin of a different community cannot approve residents here (403)."""
```

### 4.7 CommunitySettingsView (`PATCH /api/v1/communities/{slug}/settings/`)

```python
def test_settings_update_commission_pct():
    """Admin PATCH updates commission_pct and it is persisted."""

def test_settings_add_new_buildings():
    """Admin PATCH with new building names creates Building rows."""

def test_settings_deactivate_community():
    """Admin PATCH with is_active=False sets community.is_active=False."""

def test_settings_non_admin_returns_403():
    """Non-admin request returns 403."""

def test_settings_duplicate_building_name_silently_ignored():
    """Adding a building name that already exists does not raise an error (ignore_conflicts)."""
```

### 4.8 InviteRegenerateView (`POST /api/v1/communities/{slug}/invite/regenerate/`)

```python
def test_invite_regenerate_returns_new_code():
    """Admin call returns a new invite_code; old code no longer accepted for join."""

def test_invite_regenerate_code_format():
    """New invite_code is exactly 6 uppercase alphanumeric characters."""

def test_invite_regenerate_non_admin_returns_403():
    """Non-admin request returns 403."""
```

### 4.9 URL Resolution

```python
def test_url_reverse_register():
    """reverse('communities:register') resolves without error."""

def test_url_reverse_join():
    """reverse('communities:join') resolves without error."""

def test_all_named_urls_resolve():
    """All named URL patterns in communities namespace resolve to correct view classes."""
```

---

## 5. Integration / Edge Case Tests (`apps/communities/tests/test_views.py`)

These are end-to-end scenario tests placed at the bottom of `test_views.py` or in a dedicated `test_integration.py` file:

```python
def test_full_flow_register_join_approve_jwt_claims():
    """
    Full integration:
    1. User A registers a community → JWT has community_admin role + community_id
    2. User B joins with invite_code → JWT has resident role + community_id, status=PENDING
    3. User A approves User B → status=APPROVED
    Assert JWT claims are correct at each step.
    """

def test_resident_count_correct_after_three_sequential_joins():
    """Three sequential joins → resident_count == 3."""

def test_rejected_user_cannot_rejoin():
    """User whose ResidentProfile is REJECTED attempts to join again → 400."""

def test_concurrent_join_no_double_count():
    """
    Use threading (two threads joining simultaneously) or direct F() SQL assertion
    to verify resident_count is not double-incremented.
    For unit testing without real concurrency: verify the view uses F() by asserting
    the UPDATE SQL uses F() semantics (check Django ORM call, not threading).
    """
```

---

## 6. JWT Claim Inspection Pattern

Use this pattern consistently across all tests that need to inspect token payloads:

```python
from rest_framework_simplejwt.tokens import AccessToken

def _decode_access(response_data):
    """Helper: decode access token from a view response dict."""
    return AccessToken(response_data['tokens']['access']).payload
```

Example assertion:
```python
payload = _decode_access(response.data)
assert payload['community_id'] == community.id
assert 'resident' in payload['roles']
```

---

## 7. Django Admin Tests (`apps/communities/tests/test_views.py` or `test_admin.py`)

These are smoke tests using Django's test `Client` (not `APIClient`), logged in as a superuser:

```python
def test_community_list_page_loads():
    """GET /admin/communities/community/ returns 200."""

def test_mark_as_reviewed_action():
    """'Mark as reviewed' action sets is_reviewed=True on selected Community rows."""

def test_approve_residents_action():
    """'Approve selected' action sets status=APPROVED on selected ResidentProfile rows."""

def test_building_inline_renders_on_community_change():
    """GET /admin/communities/community/{id}/change/ returns 200 (BuildingInline present)."""
```

---

## Implementation Notes (actual build)

### Files created/modified
- `namma_neighbor/apps/communities/tests/factories.py` — added `BuildingFactory`, `FlatFactory`, `ResidentProfileFactory`; added `slug` to `CommunityFactory`; uses string SubFactory ref `'apps.users.tests.factories.UserFactory'` to avoid circular import
- `namma_neighbor/apps/communities/tests/conftest.py` — added `admin_client` fixture (creates Django `Client` logged in as superuser with `phone='+910000000099'`)
- `namma_neighbor/apps/communities/tests/test_views.py` — removed `xfail` from `TestDjangoAdminCommunitySettingsActions`; added `TestIntegrationFlows` class with 3 end-to-end tests

### Deviations from plan
- All model, serializer, and view test files (`test_models.py`, `test_serializers.py`, `test_views.py`) were already written in prior sections; section-08 consolidated and filled gaps
- `TestDjangoAdminCommunitySettingsActions` was already in `test_views.py` with `@pytest.mark.xfail`; after section-07 completed the admin registration, the marker was removed
- The `admin_client` fixture was added to `conftest.py` (not in a separate admin test file) to make it available to `TestDjangoAdminCommunitySettingsActions` in `test_views.py`
- `force_authenticate(user=None)` must be called before `credentials(HTTP_AUTHORIZATION=...)` in integration tests — DRF's `force_authenticate` takes precedence over `credentials()`
- Integration test `test_f_expression_no_double_count_on_sequential_joins` was renamed to `test_two_sequential_joins_result_in_count_2` because single-threaded tests cannot verify atomicity; the test still verifies correct F() increment behavior
- `ResidentProfileFactory.community` is derived via `LazyAttribute` from `flat.building.community` — do not pass `community=` explicitly to this factory

### Final test count
- 119 tests total, all passing
- `test_models.py`: 20 tests
- `test_serializers.py`: 9 tests
- `test_views.py`: 83 tests
- `test_admin.py`: 7 tests

---

## 8. Notes for the Implementer

- All tests use `pytest.mark.django_db` (or `@pytest.mark.django_db` decorator) to enable DB access.
- Do not use Django's `TestCase` class — use plain `pytest` functions with `pytest-django` fixtures.
- The `api_client` fixture should not be authenticated. Call `client.force_authenticate(user=user)` on it inside tests that need auth, or use the `auth_client` fixture from `conftest.py`.
- The `community_with_buildings` fixture must set `admin_user` on the Community and create a matching `UserRole`. The fixture should also set `admin_user.active_community = community` so that JWT reissuance in the views works correctly.
- Floor inference logic is tested at the model level (or as a unit test of the helper function) rather than through the full HTTP stack.
- Tests for the "wrong community admin" scenario require creating two distinct communities, each with their own admin user and JWT.