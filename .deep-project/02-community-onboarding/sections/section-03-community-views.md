Now I have all the context needed. Let me generate the section content for `section-03-community-views`.

# Section 03: Community Views

## Overview

This section implements the community registration flow and the two public read endpoints:

- `CommunityRegisterView` — `POST /api/v1/communities/register/`
- `CommunityDetailView` — `GET /api/v1/communities/{slug}/`
- `BuildingListView` — `GET /api/v1/communities/{slug}/buildings/`

All view code lives in `/var/www/html/MadGirlfriend/namma-neighbour/apps/communities/views.py`. This section covers only these three views; the remaining views (`JoinCommunityView`, `ResidentListView`, `ResidentApproveView`, `ResidentRejectView`, `CommunitySettingsView`, `InviteRegenerateView`) are in sections 04 and 05.

## Dependencies

- **section-01-models-migration** must be complete: `Community`, `Building`, `Flat`, `ResidentProfile` models and their migration must exist.
- **section-02-serializers** must be complete: `CommunityRegistrationSerializer`, `CommunityDetailSerializer`, and `BuildingSerializer` must be importable from `apps.communities.serializers`.

The following from split 01 are used directly:
- `apps.users.models.UserRole` — for creating the `community_admin` role entry
- `apps.users.serializers.CustomTokenObtainPairSerializer` — for JWT reissuance after community assignment
- `apps.core.permissions.IsCommunityAdmin`, `IsResidentOfCommunity` (not needed in this section, but the module is used)

## Tests First

These tests belong in `apps/communities/tests/test_views.py`. Write them before implementing the views.

### CommunityRegisterView Tests

```python
class TestCommunityRegisterView:
    """POST /api/v1/communities/register/"""

    def test_authenticated_user_registers_community_returns_201_with_invite_code(self, api_client, user):
        """Valid payload: community created, invite_code present in response."""

    def test_buildings_are_created_matching_input_list(self, api_client, user):
        """Number of Building rows equals the length of the buildings input list."""

    def test_user_role_community_admin_created(self, api_client, user):
        """UserRole(role='community_admin', community=<new>, user=<registering>) exists after registration."""

    def test_user_active_community_set_to_new_community(self, api_client, user):
        """request.user.active_community == newly created Community after registration."""

    def test_response_includes_tokens_access_and_refresh(self, api_client, user):
        """Response body contains tokens.access and tokens.refresh keys."""

    def test_jwt_payload_has_community_id_matching_new_community(self, api_client, user):
        """Decoded AccessToken payload['community_id'] == community.id."""

    def test_unauthenticated_request_returns_401(self, api_client):
        """No auth header → 401."""

    def test_slug_collision_still_succeeds_with_suffix(self, api_client, user_a, user_b, existing_community):
        """Two registrations with same name+city produce different slugs (e.g., foo-bar and foo-bar-2)."""
```

JWT claim inspection pattern to use in tests:

```python
from rest_framework_simplejwt.tokens import AccessToken

payload = AccessToken(response.data['tokens']['access']).payload
assert payload['community_id'] == community.id
assert 'community_admin' in payload['roles']
```

### CommunityDetailView Tests

```python
class TestCommunityDetailView:
    """GET /api/v1/communities/{slug}/"""

    def test_returns_name_city_slug_is_active(self, api_client, community):
        """Response contains exactly the public fields."""

    def test_does_not_return_sensitive_fields(self, api_client, community):
        """resident_count, commission_pct, invite_code, admin_user NOT in response."""

    def test_nonexistent_slug_returns_404(self, api_client):
        """GET with a slug that does not exist → 404."""

    def test_no_auth_required(self, api_client, community):
        """Unauthenticated request succeeds (200)."""
```

### BuildingListView Tests

```python
class TestBuildingListView:
    """GET /api/v1/communities/{slug}/buildings/"""

    def test_returns_list_of_building_id_and_name(self, api_client, community_with_buildings):
        """Each entry has 'id' and 'name' keys."""

    def test_no_auth_required(self, api_client, community_with_buildings):
        """Unauthenticated request succeeds (200)."""
```

## Implementation

### Files Created / Modified

- **`apps/communities/views.py`** — three view classes (replaces stub)
- **`apps/communities/urls.py`** — added register/detail/buildings URL patterns with `app_name = "communities"`
- **`apps/communities/serializers.py`** — added slug generation with IntegrityError retry in `create()`
- **`config/urls.py`** — included `apps.communities.urls` at `api/v1/communities/`
- **`config/settings/base.py`** — added `DEFAULT_THROTTLE_RATES: {anon: 60/minute}`
- **`apps/communities/tests/conftest.py`** — created with `api_client`, `user`, `community`, `community_with_buildings`, `existing_community` fixtures
- **`apps/communities/tests/test_views.py`** — 14 tests covering all three views

### CommunityRegisterView

**Route:** `POST /register/`
**Permission:** `IsAuthenticated`

The view orchestrates a multi-step atomic operation:

1. Instantiate and call `CommunityRegistrationSerializer(data=request.data, context={'request': request})`. The serializer's `create()` wraps Community + Building creation in `transaction.atomic()` with IntegrityError retry for slug/invite_code uniqueness. `admin_user` is taken from `self.context['request'].user` inside the serializer (section 02 design; view calls `serializer.save()` with no kwargs).

2. After the community is saved, create the `UserRole` entry:
   ```python
   UserRole.objects.create(
       user=request.user,
       role='community_admin',
       community=community
   )
   ```

3. Set `request.user.active_community = community` and call `request.user.save()`. **This must happen before JWT generation**, because `CustomTokenObtainPairSerializer.get_token(user)` reads `user.active_community` at call time.

4. Generate fresh tokens:
   ```python
   refresh = CustomTokenObtainPairSerializer.get_token(request.user)
   tokens = {
       'access': str(refresh.access_token),
       'refresh': str(refresh),
   }
   ```

5. Return HTTP 201 with community serializer data merged with the tokens dict.

**Slug and invite_code generation** live at the model/serializer level (see section 01 and 02 for the collision-safe generation logic). This view does not handle slug/invite_code directly.

### CommunityDetailView

**Route:** `GET /{slug}/`
**Permission:** `AllowAny`
**Throttle:** `AnonRateThrottle`

Straightforward lookup:

1. Look up `Community` with `get_object_or_404(Community, slug=slug)`.
2. Serialize with `CommunityDetailSerializer`.
3. Return HTTP 200.

No authentication required. The `CommunityDetailSerializer` deliberately omits sensitive fields (`resident_count`, `commission_pct`, `invite_code`, `admin_user`). The view does not need to filter them explicitly.

Apply `AnonRateThrottle` via the `throttle_classes` attribute on the view class.

### BuildingListView

**Route:** `GET /{slug}/buildings/`
**Permission:** `AllowAny`

1. Look up `Community` by slug with `get_object_or_404`.
2. Query `Building.objects.filter(community=community)`.
3. Serialize with `BuildingSerializer(queryset, many=True)`.
4. Return HTTP 200 with the list.

No pagination needed on this endpoint (building lists are bounded by community size; communities are not expected to have hundreds of buildings).

### View Class Structure (stubs)

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import AnonRateThrottle
from django.shortcuts import get_object_or_404

from apps.communities.models import Community, Building
from apps.communities.serializers import (
    CommunityRegistrationSerializer,
    CommunityDetailSerializer,
    BuildingSerializer,
)
from apps.users.models import UserRole
from apps.users.serializers import CustomTokenObtainPairSerializer


class CommunityRegisterView(APIView):
    """
    POST /api/v1/communities/register/
    Authenticated user registers a new community.
    Returns community data + fresh JWT tokens.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ...


class CommunityDetailView(APIView):
    """
    GET /api/v1/communities/{slug}/
    Public. Returns non-sensitive community details.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def get(self, request, slug):
        ...


class BuildingListView(APIView):
    """
    GET /api/v1/communities/{slug}/buildings/
    Public. Returns buildings for a community (used during join flow).
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        ...
```

## Key Design Details

**JWT reissuance is mandatory on registration.** The old access token (from login) has no `community_id` or `community_admin` role claim. The client must replace both tokens on receipt of the registration response. Return both `access` and `refresh` in the response body under a `tokens` key:

```json
{
  "id": 1,
  "name": "Prestige Shantiniketan",
  "slug": "prestige-shantiniketan-bengaluru",
  "invite_code": "XK92AB",
  "buildings": [...],
  "tokens": {
    "access": "...",
    "refresh": "..."
  }
}
```

**UserRole creation must be inside or immediately after the atomic block.** If UserRole creation fails after the Community was committed, the community exists but the registering user has no admin role — this would be a silent data inconsistency. Consider wrapping the entire registration sequence (Community + Building + UserRole + active_community save) in a single `transaction.atomic()` at the view layer, even though the serializer already has its own inner `atomic()`. Django's `transaction.atomic()` is re-entrant (uses savepoints) so nesting is safe.

**`admin_user` injection:** The serializer's `create()` method receives `admin_user` via `serializer.save(admin_user=request.user)`. The serializer must accept this as a keyword argument in its `create(self, validated_data)` method — it will be present as an extra kwarg passed through from `save()`. See section 02 (serializers) for the serializer signature.

**Slug collision handling** is performed in the serializer or a model-level utility (see section 01). The view does not need to handle it. If the serializer raises a `ValidationError` for any field, DRF's exception handler (from `apps/core/exceptions.py`) normalizes it to `{"error": "...", "detail": "..."}`.

**`AnonRateThrottle` on `CommunityDetailView`:** Configured in Django settings under `REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']`. If this key is not yet set in settings, add `'anon': '60/minute'` to the throttle rates dict. Do not use the global `DEFAULT_THROTTLE_CLASSES` — apply only to this view via `throttle_classes`.

## Error Handling

All errors follow the normalized format from `apps/core/exceptions.py`. The views do not need custom exception handling beyond:

- `get_object_or_404` raises `Http404` which DRF converts to 404 automatically.
- Serializer validation errors raised as `serializers.ValidationError` are caught by DRF and normalized to 400 by the custom exception handler.

Do not return raw `Response({"message": "..."}, status=400)` — let the exception handler manage error shape.

## What This Section Does NOT Cover

- `JoinCommunityView`, `ResidentListView`, `ResidentApproveView`, `ResidentRejectView` → section 04
- `CommunitySettingsView`, `InviteRegenerateView` → section 05
- URL wiring (`urls.py`, `config/urls.py`) → section 06
- Test factories and conftest fixtures → section 08 (but stubs are included above for reference)