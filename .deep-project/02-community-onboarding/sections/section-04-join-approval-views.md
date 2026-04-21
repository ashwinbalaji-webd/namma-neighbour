Now I have all the context needed. Let me generate the section content.

# section-04-join-approval-views

## Overview

This section implements four views in `apps/communities/views.py`:

- `JoinCommunityView` — authenticated residents join a community using an invite code; creates a PENDING `ResidentProfile`, increments the counter, and reissues the JWT
- `ResidentListView` — community admin retrieves a paginated, filterable list of resident profiles
- `ResidentApproveView` — community admin approves a PENDING resident profile
- `ResidentRejectView` — community admin rejects a PENDING resident profile (record is preserved)

**Dependencies (must be complete before starting this section):**

- `section-01-models-migration`: `Community`, `Building`, `Flat`, `ResidentProfile` models must exist with all fields
- `section-02-serializers`: `JoinCommunitySerializer`, `ResidentProfileSerializer`, `ResidentApprovalSerializer` must exist

This section is **parallelizable** with `section-03-community-views` and `section-05-admin-views`.

---

## Tests First

These tests live in `apps/communities/tests/test_views.py`. Write them before implementing the views. All tests use `pytest-django`, `factory_boy`, `APIClient`, and `simplejwt.AccessToken`.

### JoinCommunityView tests

```python
class TestJoinCommunityView:
    """POST /api/v1/communities/join/"""

    def test_valid_join_creates_pending_resident_profile(self, api_client, community_with_buildings, user):
        """Valid invite code → ResidentProfile created with status=PENDING, HTTP 201."""

    def test_resident_count_incremented_after_join(self, api_client, community_with_buildings, user):
        """resident_count goes from N to N+1 atomically after a successful join."""

    def test_response_includes_tokens(self, api_client, community_with_buildings, user):
        """Response body includes tokens.access and tokens.refresh."""

    def test_jwt_has_community_id_and_resident_role(self, api_client, community_with_buildings, user):
        """After join, decoded access token contains community_id and 'resident' in roles."""

    def test_user_active_community_set_to_joined_community(self, api_client, community_with_buildings, user):
        """request.user.active_community is the joined community after success."""

    def test_invalid_invite_code_returns_404(self, api_client, user):
        """Non-existent invite code → 404 (not 400) to prevent enumeration."""

    def test_second_join_by_same_user_returns_400(self, api_client, community_with_buildings, user):
        """User already has a ResidentProfile → 400."""

    def test_two_users_join_same_flat_both_succeed(self, api_client, community_with_buildings, user_a, user_b):
        """No unique constraint on Flat → both get 201 independently."""

    def test_flat_get_or_create_does_not_duplicate(self, api_client, community_with_buildings, user_a, user_b):
        """Two users joining the same flat number create only one Flat row."""

    def test_unauthenticated_join_returns_401(self, api_client, community_with_buildings):
        """No auth header → 401."""
```

### ResidentListView tests

```python
class TestResidentListView:
    """GET /api/v1/communities/{slug}/residents/"""

    def test_admin_can_list_residents(self, api_client, community_admin, community_with_residents):
        """Community admin → 200, paginated list of residents."""

    def test_status_filter_pending_only(self, api_client, community_admin, community_with_mixed_residents):
        """?status=PENDING returns only PENDING residents."""

    def test_non_admin_resident_gets_403(self, api_client, approved_resident, community):
        """Resident without admin role → 403."""

    def test_admin_of_other_community_gets_403(self, api_client, other_community_admin, community):
        """Admin whose JWT community_id differs from slug community → 403."""

    def test_pagination_default_page_size_20(self, api_client, community_admin, community_with_25_residents):
        """First page contains 20 results; next page link exists."""
```

### ResidentApproveView and ResidentRejectView tests

```python
class TestResidentApproveView:
    """POST /api/v1/communities/{slug}/residents/{id}/approve/"""

    def test_admin_approves_pending_resident(self, api_client, community_admin, pending_resident):
        """PENDING → APPROVED, HTTP 200."""

    def test_approving_nonexistent_profile_returns_404(self, api_client, community_admin, community):
        """Profile id not in community → 404."""

    def test_resident_cannot_approve(self, api_client, approved_resident, pending_resident, community):
        """Resident role → 403."""

    def test_admin_of_wrong_community_cannot_approve(self, api_client, other_community_admin, pending_resident, community):
        """JWT community_id does not match slug community → 403."""


class TestResidentRejectView:
    """POST /api/v1/communities/{slug}/residents/{id}/reject/"""

    def test_admin_rejects_pending_resident(self, api_client, community_admin, pending_resident):
        """PENDING → REJECTED, HTTP 200."""

    def test_rejected_record_still_exists_in_db(self, api_client, community_admin, pending_resident):
        """After rejection, ResidentProfile row remains in DB with status=REJECTED."""

    def test_rejected_user_cannot_rejoin(self, api_client, community_with_buildings, rejected_resident_user):
        """User whose profile is REJECTED → 400 on join attempt (existing profile found)."""

    def test_resident_cannot_reject(self, api_client, approved_resident, pending_resident, community):
        """Resident role → 403."""

    def test_admin_of_wrong_community_cannot_reject(self, api_client, other_community_admin, pending_resident, community):
        """JWT community_id does not match slug community → 403."""
```

### JWT claim inspection helper

Use this pattern in any test that inspects token contents:

```python
from rest_framework_simplejwt.tokens import AccessToken

payload = AccessToken(response.data["tokens"]["access"]).payload
assert payload["community_id"] == community.id
assert "resident" in payload["roles"]
```

---

## Implementation

### Files Modified

- `apps/communities/views.py` — added JoinCommunityView, ResidentListView, ResidentApproveView, ResidentRejectView, get_community_or_403 helper
- `apps/communities/urls.py` — added join/, residents/, residents/<pk>/approve/, residents/<pk>/reject/ URL patterns
- `apps/communities/tests/conftest.py` — added community_admin, approved_resident, pending_resident, community_with_residents, community_with_mixed_residents, community_with_25_residents, other_community_admin, rejected_resident_user fixtures
- `apps/communities/tests/test_views.py` — 25 tests covering all four views (73 total)

**Deviations from plan:**
- Used `rest_framework.exceptions.PermissionDenied` (not Django's) for JSON responses
- `Flat.get_or_create` moved inside `transaction.atomic()` for concurrent safety
- `UserRole(role='resident')` created via `get_or_create` in JoinCommunityView (plan omitted this step but needed for JWT claims)

### File to modify

This file already exists (or will exist after section-03 is done). Add the four views to it — do not create a separate file.

### Imports required

```python
from django.db.models import F
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from apps.core.permissions import IsCommunityAdmin
from apps.communities.models import Community, Flat, ResidentProfile
from apps.communities.serializers import (
    JoinCommunitySerializer,
    ResidentProfileSerializer,
)
from apps.users.serializers import CustomTokenObtainPairSerializer
```

### JWT reissuance pattern

After any community or role assignment, tokens must be regenerated. The pattern is identical across all views that modify `user.active_community`:

1. Set `request.user.active_community = community`
2. Call `request.user.save()`
3. Call `CustomTokenObtainPairSerializer.get_token(request.user)` — reads `active_community` at call time
4. Include `tokens.access` and `tokens.refresh` in the response body

`ResidentApproveView` and `ResidentRejectView` do **not** reissue tokens — status changes are checked by the client on next load.

### Cross-community guard helper

All slug-scoped views that require `IsCommunityAdmin` must verify the admin's JWT `community_id` matches the community in the URL. Add this method to any class-based view that needs it, or as a standalone function in the views module:

```python
def get_community_or_403(slug, request):
    """
    Look up Community by slug. Raise PermissionDenied if the requesting user's
    JWT community_id does not match the community's pk.
    Returns the Community instance on success.
    """
```

### JoinCommunityView

**URL:** `POST /api/v1/communities/join/`

**Permission:** `IsAuthenticated`

**Flow:**

1. Instantiate `JoinCommunitySerializer(data=request.data, context={'request': request})` and call `.is_valid(raise_exception=True)`
2. The serializer's `validate()` returns `validated_data` including the resolved `community` and `building` objects — extract them directly (no second DB query)
3. Call `Flat.objects.get_or_create(building=building, flat_number=flat_number)` — on creation, attempt floor inference (see below)
4. Create `ResidentProfile(user=request.user, community=community, flat=flat, user_type=user_type, status='PENDING')`
5. Increment counter: `Community.objects.filter(pk=community.pk).update(resident_count=F('resident_count') + 1)` — use `F()`, never `community.resident_count += 1`
6. Set `request.user.active_community = community`, save, reissue JWT
7. Return `ResidentProfileSerializer(profile).data` plus tokens with `HTTP 201`

**Floor inference logic** (called when a new Flat is created, not when it already exists):

The logic lives in the view or as a module-level helper. Given `flat_number` as a string:
- Strip leading/trailing whitespace
- Check if the string starts with one or more digits using a regex like `^(\d+)`
- If the matched prefix represents a number with 3+ digits, treat the first `len(digits) - 2` digits as the floor (e.g., `"304"` → prefix `3`, floor `3`; `"1205"` → prefix `12`, floor `12`)
- A simpler safe heuristic: if `flat_number` matches `^\d{3,}`, take `flat_number[:-2]` as the floor digits
- If inference fails or produces an empty string, set `flat.floor = None`
- This is best-effort; never raise an exception or block the join if inference fails
- Save `flat` after setting `floor` if a new flat was created

### ResidentListView

**URL:** `GET /api/v1/communities/{slug}/residents/`

**Permission:** `IsCommunityAdmin`

**Flow:**

1. Look up `Community` by `slug`, apply `get_community_or_403` check
2. Build queryset: `ResidentProfile.objects.filter(community=community).select_related('flat', 'user')`
3. Apply optional `?status=` query parameter filter — validate the value is one of `('PENDING', 'APPROVED', 'REJECTED')`; ignore invalid values silently or return empty queryset
4. Apply DRF pagination (default page size 20 — configured via `DEFAULT_PAGINATION_CLASS` in Django settings or inline with a `PageNumberPagination` subclass)
5. Return serialized paginated results

### ResidentApproveView

**URL:** `POST /api/v1/communities/{slug}/residents/{pk}/approve/`

**Permission:** `IsCommunityAdmin`

**Flow:**

1. Apply `get_community_or_403` check using the `slug` from URL kwargs
2. Look up `ResidentProfile` scoped to the community: `ResidentProfile.objects.get(pk=pk, community=community)` — raise `Http404` if not found
3. Set `profile.status = 'APPROVED'` and call `profile.save(update_fields=['status'])`
4. Return `ResidentProfileSerializer(profile).data` with `HTTP 200`
5. Do **not** reissue JWT

### ResidentRejectView

**URL:** `POST /api/v1/communities/{slug}/residents/{pk}/reject/`

**Permission:** `IsCommunityAdmin`

**Flow:**

Same as `ResidentApproveView` except set `profile.status = 'REJECTED'`. The record is never deleted. Do **not** reissue JWT.

---

## Key Design Constraints

| Constraint | Detail |
|------------|--------|
| 404 for invalid invite code | Enforced in `JoinCommunitySerializer.validate()` — never return 400 for a missing invite code |
| F() for resident_count | Always use `Community.objects.filter(pk=...).update(resident_count=F(...)+1)` — never Python-level increment |
| REJECTED profiles never deleted | `ResidentRejectView` only sets `status='REJECTED'`; no `profile.delete()` call |
| No JWT reissue on approve/reject | Only `JoinCommunityView` reissues tokens in this section |
| Cross-community guard | `ResidentListView`, `ResidentApproveView`, `ResidentRejectView` all must verify `request.auth.payload['community_id'] == community.pk` |
| REJECTED user blocks rejoin | `JoinCommunitySerializer` checks for any existing `ResidentProfile` regardless of status — a REJECTED user gets 400, not a new profile |
| Two users, same flat | `get_or_create` on Flat is safe; no unique constraint prevents two `ResidentProfile` rows pointing at the same `Flat` |

---

## Relevant Model Reference (from section-01)

`ResidentProfile` status choices: `PENDING`, `APPROVED`, `REJECTED`

`ResidentProfile` user_type choices: `OWNER_RESIDING`, `OWNER_NON_RESIDING`, `TENANT`, `FAMILY_DEPENDENT`

`ResidentProfile` fields relevant here: `user` (OneToOne), `community` (FK), `flat` (FK, nullable), `user_type`, `status`, `joined_at` (auto_now_add)

`Flat` fields: `building` (FK), `flat_number`, `floor` (nullable IntegerField)

`Community.resident_count` is a denormalized IntegerField — never read-modify-write it in Python; use `F()` for all increments.

---

## Relevant Serializer Reference (from section-02)

`JoinCommunitySerializer.validate()` must return the resolved `community` and `building` objects in `validated_data` so the view can use them without re-querying.

`ResidentProfileSerializer` output fields: `id`, `user_type`, `status`, `flat` (nested `FlatSerializer`), `joined_at`.

`ResidentApprovalSerializer` has no input fields — the action is determined by the URL. It outputs an updated `ResidentProfile`.