I now have all the context needed to generate the section content for `section-06-community-switching`.

# Section 06: Community Switching

## Overview

This section implements the `POST /api/v1/auth/switch-community/` endpoint, which allows an authenticated user to change their active community and receive a freshly-issued JWT pair with roles scoped to the new community.

**Dependencies (must be complete before starting this section):**

- `section-01-project-skeleton`: Django project skeleton, settings, URL routing, DRF config
- `section-02-core-app`: `TimestampedModel`, permission classes, custom exception handler
- `section-03-user-models`: `User`, `UserRole`, and `PhoneOTP` models
- `section-04-otp-send`: `send-otp/` view and Celery task infrastructure
- `section-05-otp-verify-jwt`: `verify-otp/` view, `CustomTokenObtainPairSerializer`, `logout/` endpoint — the serializer built here is reused in the switch-community view

---

## Background

Each user can have `UserRole` records across multiple communities. For example, a user might be a `resident` in Community A and a `vendor` in Community B. The JWT payload always carries `roles` scoped to exactly one community — the user's `active_community`. Because the JWT's `roles` claim is community-scoped, DRF permission classes such as `IsResidentOfCommunity` can safely check `'resident' in roles` without performing an additional community lookup.

When the user switches their active community, the old JWT becomes stale: its `community_id` and `roles` no longer match reality. The switch-community endpoint therefore updates `User.active_community_id` in the database, then issues a brand-new JWT pair with the correct claims for the new community. The client must discard the old tokens and store the new pair.

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `apps/users/views.py` | Add `SwitchCommunityView` |
| `apps/users/urls.py` | Register `switch-community/` path |
| `apps/users/tests/test_switch_community.py` | New test file (write tests first) |

The `CustomTokenObtainPairSerializer` from section 05 (`apps/users/serializers.py`) is reused directly — do not duplicate it.

---

## Tests First

File: `apps/users/tests/test_switch_community.py`

Testing stack: `pytest-django`, `factory_boy`. All DB tests use `@pytest.mark.django_db`. Use `APIClient` from DRF for HTTP calls. Import `UserFactory` and `CommunityFactory` from `apps/users/tests/factories.py` (established in section 03).

### Test stubs

```python
import pytest
from rest_framework.test import APIClient
from apps.users.tests.factories import UserFactory, CommunityFactory, UserRoleFactory

SWITCH_URL = "/api/v1/auth/switch-community/"


@pytest.fixture
def client():
    """Return a DRF APIClient."""
    ...


@pytest.fixture
def user_with_two_communities(db):
    """
    Create a user with:
      - role 'resident' in community_a
      - role 'community_admin' in community_b
    Active community starts as community_a.
    Returns (user, community_a, community_b).
    """
    ...


class TestSwitchCommunitySuccess:
    def test_returns_new_jwt_pair(self, client, user_with_two_communities):
        """POST with a community the user belongs to returns access + refresh tokens."""
        ...

    def test_active_community_updated_in_db(self, client, user_with_two_communities):
        """User.active_community_id is updated to the requested community after the call."""
        ...

    def test_new_jwt_has_correct_community_id(self, client, user_with_two_communities):
        """Decode the returned access token and assert community_id matches the new community."""
        ...

    def test_new_jwt_roles_scoped_to_new_community(self, client, user_with_two_communities):
        """
        User is community_admin in community_b and resident in community_a.
        Switching to community_b → roles = ['community_admin'].
        Switching to community_a → roles = ['resident'].
        """
        ...

    def test_old_roles_not_present_in_new_jwt(self, client, user_with_two_communities):
        """
        After switching to community_b, 'resident' role (from community_a) must NOT
        appear in the JWT roles claim.
        """
        ...


class TestSwitchCommunityFailure:
    def test_unauthenticated_returns_401(self, client):
        """Request without JWT returns 401."""
        ...

    def test_community_user_not_member_of_returns_403(self, client, user_with_two_communities):
        """POST with a community_id for which no UserRole exists returns 403."""
        ...

    def test_nonexistent_community_returns_403(self, client, user_with_two_communities):
        """POST with a community_id that does not exist in the database returns 403."""
        ...

    def test_missing_community_id_returns_400(self, client, user_with_two_communities):
        """POST without community_id in request body returns 400."""
        ...
```

### Notes on test setup

- Use `UserRoleFactory` (a factory_boy factory for `UserRole`) to create role records. If not already defined in `apps/users/tests/factories.py` from section 03, add it there now.
- To authenticate the `APIClient`, call `client.force_authenticate(user=user)` or obtain a JWT from `verify-otp/` and set `client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")`. The simpler `force_authenticate` is preferred in unit tests to avoid coupling to the OTP flow.
- To decode the JWT and inspect claims, use `rest_framework_simplejwt.tokens.AccessToken(token_str)` — it validates and decodes without an HTTP call.

---

## Implementation

### View: `SwitchCommunityView`

Location: `apps/users/views.py`

The view is a `APIView` subclass with `permission_classes = [IsAuthenticated]`.

**Request body** (JSON):

```json
{"community_id": 7}
```

**Logic (in order):**

1. Parse `community_id` from `request.data`. If absent or not a positive integer, return 400 with the standard error shape: `{"error": "validation_error", "detail": "community_id is required"}`.
2. Check that `UserRole.objects.filter(user=request.user, community_id=community_id).exists()`. If no matching row, return 403 with `{"error": "permission_denied", "detail": "You do not have a role in this community"}`. Note: if the community itself does not exist, the query returns no rows and the same 403 applies — do not make a separate `Community.objects.get()` call.
3. Update `request.user.active_community_id = community_id` and call `request.user.save(update_fields=['active_community_id'])`.
4. Instantiate `CustomTokenObtainPairSerializer` (imported from `apps.users.serializers`) and call its `get_token(request.user)` classmethod to obtain a `RefreshToken` instance. Extract `str(refresh)` and `str(refresh.access_token)`.
5. Return HTTP 200:

```json
{
  "access": "<new access token>",
  "refresh": "<new refresh token>",
  "community_id": 7
}
```

**Stub signature:**

```python
class SwitchCommunityView(APIView):
    """
    Switch the authenticated user's active community and re-issue JWT tokens
    with roles scoped to the new community.

    POST /api/v1/auth/switch-community/
    Body: {"community_id": <int>}
    Returns: {"access": "...", "refresh": "...", "community_id": <int>}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ...
```

### URL registration

Location: `apps/users/urls.py`

Add the path alongside the existing auth endpoints:

```python
path("switch-community/", SwitchCommunityView.as_view(), name="switch-community"),
```

The full `apps/users/urls.py` should list all five endpoints:

| Name | Path | View |
|------|------|------|
| `send-otp` | `send-otp/` | `SendOTPView` |
| `verify-otp` | `verify-otp/` | `VerifyOTPView` |
| `token-refresh` | `refresh/` | `TokenRefreshView` (simplejwt) |
| `logout` | `logout/` | `LogoutView` |
| `switch-community` | `switch-community/` | `SwitchCommunityView` |

All of these are mounted under `/api/v1/auth/` in `config/urls.py` (done in section 01).

---

## JWT Re-issuance Detail

The `CustomTokenObtainPairSerializer.get_token(user)` classmethod (implemented in section 05) already handles adding `phone`, `roles`, and `community_id` to the token payload. Because `user.active_community_id` has already been updated by the time `get_token` is called, the resulting token will automatically carry the new `community_id` and the roles scoped to that community.

The `roles` list is built by querying `UserRole.objects.filter(user=user, community_id=user.active_community_id).values_list('role', flat=True)`. After the `active_community_id` update, this query returns only the roles for the new community — the JWT correctly reflects the switch.

---

## Error Response Shape

All error responses must use the normalized shape established by the custom exception handler in section 02:

```json
{"error": "<error_code>", "detail": "<human-readable message>"}
```

In the `SwitchCommunityView`, raise or return errors in this format directly (since this view constructs responses manually, use `Response({"error": ..., "detail": ...}, status=...)` rather than raising DRF exceptions — both work, but explicit `Response` objects are clearer here).

---

## Acceptance Criteria

The section is complete when all of the following hold:

- `uv run pytest apps/users/tests/test_switch_community.py` passes with no failures
- Switching to a valid community updates `User.active_community_id` in the database
- The returned access token contains `community_id` equal to the new community's id
- The returned access token contains `roles` that includes only roles held in the new community
- Roles from other communities do not appear in the new JWT
- Unauthenticated requests receive HTTP 401
- Requests for a community the user has no `UserRole` in receive HTTP 403 (regardless of whether the community exists)
- The endpoint is registered at `POST /api/v1/auth/switch-community/` and reachable