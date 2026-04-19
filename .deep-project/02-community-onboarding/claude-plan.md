# Implementation Plan: 02-Community Onboarding

## Overview

This split builds the community scoping layer for the NammaNeighbor hyperlocal marketplace. It enables a gated community's society admin to register their community on the platform and residents to join it. Every downstream feature (listings, orders, disputes) is scoped to a community — this split establishes that foundation.

The implementation lives entirely in `apps/communities/`. It extends the stub `Community` model left by split 01 and introduces three new models (`Building`, `Flat`, `ResidentProfile`), a set of REST endpoints, an admin approval workflow for resident onboarding, and Django admin customizations.

**Key architectural decision (from stakeholder interview):** The original spec assumed one resident per flat. After review, the platform adopts a _family-sharing_ model — multiple residents can share one flat, each declaring their relationship type. All join requests enter a `PENDING` state and require explicit community admin approval before residents gain full platform access.

---

## Project Context

### Existing Codebase Anchors

Split 01 established:

- `apps/users/models.py`: `User` model (phone-based, no username), `UserRole` model (`unique_together(user, role, community)`), `User.active_community` FK → `Community`
- `apps/users/serializers.py`: `CustomTokenObtainPairSerializer.get_token(user)` — reads `user.active_community` to scope JWT claims (`phone`, `community_id`, `roles[]`)
- `apps/core/permissions.py`: `IsCommunityAdmin`, `IsResidentOfCommunity`, `IsVendorOfCommunity`, `IsPlatformAdmin`
- `apps/communities/models.py`: A minimal `Community` stub (only `name`, `is_active`, timestamps) — **this split replaces it entirely**
- `apps/core/exceptions.py`: Custom exception handler normalizing all DRF errors to `{"error": "...", "detail": "..."}`

### URL Root

All endpoints live under `/api/v1/communities/`. The `config/urls.py` must include `apps.communities.urls` at `api/v1/communities/`.

### JWT Reissuance Pattern

After any role or community change, the response body must include fresh tokens:
```json
{
  "tokens": { "access": "...", "refresh": "..." }
}
```
This is done by calling `CustomTokenObtainPairSerializer.get_token(user)` after updating `user.active_community`. The token reads active community at call time — the community assignment must happen before token generation.

---

## File Structure

```
apps/communities/
├── __init__.py
├── admin.py
├── apps.py
├── models.py
├── serializers.py
├── views.py
├── urls.py
├── permissions.py          # (already in apps/core/permissions.py — import from there)
├── migrations/
│   └── 0001_initial.py
└── tests/
    ├── __init__.py
    ├── factories.py
    ├── conftest.py
    ├── test_models.py
    └── test_views.py
```

---

## Section 1: Models

### 1.1 Replacing the Community Stub

The existing `Community` stub has only `name`, `is_active`, and timestamps. The migration strategy must preserve these columns and add the new ones. Split 01 already has FKs pointing at `communities.Community` — the migration must not drop the table.

The full `Community` model adds: `slug`, `city`, `pincode`, `address`, `admin_user`, `commission_pct`, `invite_code`, `resident_count`, `vendor_count`, and the new `is_reviewed` flag.

**`invite_code`** is always stored uppercase. Six characters, alphanumeric. Auto-generated on `Community.save()` when blank using `secrets.token_urlsafe` or `random.choices(string.ascii_uppercase + string.digits, k=6)`. Must be unique — retry on collision. Stored uppercase; lookups use `exact` (not `iexact`) since the value is pre-normalized.

**`slug`** is derived from `slugify(name + '-' + city)` at registration time. If a slug collision occurs, append a numeric suffix (e.g., `-2`). Never auto-update slug after creation (slugs are part of URLs).

**`is_reviewed`** defaults to `False`. Platform admins review new communities via Django admin. There is no API gate on `is_reviewed` — communities are immediately active (`is_active=True`) on creation. This is a soft-launch model: flag for review, deactivate retroactively if fraudulent.

**Counter fields** (`resident_count`, `vendor_count`) are denormalized for performance. They are **never** updated via `model.save()`. All increments use Django's `F()` expression: `Community.objects.filter(pk=pk).update(resident_count=F('resident_count') + 1)`. This translates to a single atomic SQL `UPDATE` with no Python-level race condition.

### 1.2 Building Model

`Building` belongs to a `Community` and holds a display name ("Tower A", "Block 1"). The combination of `community + name` is unique. Buildings are created in bulk during community registration.

**Removal constraint:** A building cannot be deleted if any `Flat` within it has at least one `ResidentProfile`. The settings PATCH endpoint enforces this at the view layer with a 400 response. The model's `on_delete=CASCADE` is the fallback for admin-level hard deletes only.

### 1.3 Flat Model

`Flat` is a new model not in the original spec. It represents a physical unit within a building. Fields: `building` (FK → Building, CASCADE), `flat_number` (CharField, max 20 chars), `floor` (IntegerField, nullable).

`unique_together = ('building', 'flat_number')` — one row per physical flat.

**Floor inference:** When a flat is created via the join API, the view attempts to infer the floor from `flat_number`. If the number starts with digits that look like a floor prefix (e.g., "304" → floor 3, "1205" → floor 12), populate `floor` automatically. This is best-effort and nullable — never block join if floor inference fails.

`Flat` rows are created lazily via `get_or_create` during the join flow. They are never created standalone by residents — the join endpoint creates the Flat if it doesn't exist yet.

### 1.4 ResidentProfile Model

`ResidentProfile` links a `User` to a `Community` and optionally to a `Flat`. Key design decisions:

**OneToOneField(User):** One resident profile per user. A user can be a resident of exactly one community. Attempting to join a second community returns 400.

**Multiple per Flat:** Unlike the original spec (which enforced one resident per flat), multiple `ResidentProfile` rows can reference the same `Flat`. There is no database-level unique constraint on `flat`. The uniqueness is `user → flat` via the OneToOne on user.

**`user_type`** (CharField with choices):
- `OWNER_RESIDING` — Owner who lives in the flat
- `OWNER_NON_RESIDING` — Landlord (does not reside)
- `TENANT` — Currently renting
- `FAMILY_DEPENDENT` — Spouse, child, or parent of an owner/tenant

**`status`** (CharField with choices, default `PENDING`):
- `PENDING` — Joined but not yet approved by community admin
- `APPROVED` — Full platform access granted
- `REJECTED` — Access denied; record kept in DB

**REJECTED records are never deleted.** This prevents the same phone number from repeatedly queuing in the admin's pending list after rejection.

**`joined_at`** is `auto_now_add=True`. No explicit `is_verified` field (the original spec's `is_verified=True` on creation is replaced by the `status` field).

---

## Section 2: Serializers

All serializers live in `apps/communities/serializers.py`.

### CommunityRegistrationSerializer

Handles `POST /register/`. Input fields: `name`, `city`, `pincode`, `address`, `buildings` (list of strings).

`buildings` is a `ListField(child=CharField(max_length=50), write_only=True)` — not a model field; popped before `Community.objects.create()`.

Validation:
- `pincode` must match `^[0-9]{6}$`
- `buildings` must be non-empty (at least one building required)
- `buildings` entries must be unique within the list

The `create()` method wraps everything in `transaction.atomic()`: create Community, then `Building.objects.bulk_create(...)`. The `admin_user` is injected from `request.user` in the view, not from the payload.

Output: Full community detail including `invite_code`. Never expose in the list endpoint's abbreviated view.

### CommunityDetailSerializer

For `GET /api/v1/communities/{slug}/` (public). Fields: `name`, `city`, `slug`, `is_active`. **Deliberately excludes** `resident_count`, `vendor_count`, `commission_pct`, `invite_code`, `admin_user`.

### BuildingSerializer

For `GET /{slug}/buildings/`. Fields: `id`, `name`. Used during join flow.

### FlatSerializer

Read-only. Fields: `id`, `flat_number`, `floor`, `building_id`. Returned in ResidentProfile responses.

### JoinCommunitySerializer

Handles `POST /join/`. Input: `invite_code` (CharField), `building_id` (IntegerField), `flat_number` (CharField), `user_type` (ChoiceField).

Validation:
- Look up `Community` by `invite_code.upper()` using `exact`. If not found → raise `NotFound` (404, not 400).
- Verify community `is_active=True` — inactive communities cannot accept new residents.
- Look up `Building` by `building_id` — must belong to the looked-up community.
- Check the requesting user has no existing `ResidentProfile` → raise `ValidationError` (400) if they do.

The serializer's `validate()` method returns the resolved `community` and `building` objects so the view doesn't need to re-query.

### ResidentProfileSerializer

Output serializer for `ResidentProfile`. Fields: `id`, `user_type`, `status`, `flat` (nested FlatSerializer), `joined_at`. Used in join response and resident list.

### ResidentApprovalSerializer

For approve/reject endpoints. Input: none (action is implicit from URL). Output: updated `ResidentProfile`.

---

## Section 3: Views

All views inherit from DRF's `APIView` or `GenericAPIView`. Use `apps/core/permissions.py` permission classes.

### CommunityRegisterView (`POST /register/`)

Permission: `IsAuthenticated`

Flow:
1. Validate input with `CommunityRegistrationSerializer`
2. Auto-generate `slug` and `invite_code` (handle collision)
3. Create `Community` + `Building` records atomically
4. Create `UserRole(role='community_admin', community=community)` for `request.user`
5. Set `request.user.active_community = community` and save
6. Re-issue JWT via `CustomTokenObtainPairSerializer.get_token(request.user)`
7. Return community data + new tokens

### CommunityDetailView (`GET /{slug}/`)

Permission: `AllowAny`
Throttle: `AnonRateThrottle`

Looks up `Community` by `slug`. Returns public fields only.

### BuildingListView (`GET /{slug}/buildings/`)

Permission: `AllowAny`

Returns all `Building` objects for the community.

### JoinCommunityView (`POST /join/`)

Permission: `IsAuthenticated`

Flow:
1. Validate with `JoinCommunitySerializer` (resolves community + building in serializer validation)
2. `get_or_create` Flat with `(building, flat_number)` + attempt floor inference
3. Create `ResidentProfile(status='PENDING', user_type=..., flat=..., community=...)`
4. Increment `resident_count` via `F()` expression
5. Set `request.user.active_community = community` and save
6. Re-issue JWT
7. Return `ResidentProfile` data + new tokens

### ResidentListView (`GET /{slug}/residents/`)

Permission: `IsCommunityAdmin`

Additional view-level check: `community.id == request.auth.payload['community_id']`

Paginated (default 20). Supports `?status=PENDING` filter via `django-filters` or manual queryset filtering.

### ResidentApproveView (`POST /{slug}/residents/{id}/approve/`)
### ResidentRejectView (`POST /{slug}/residents/{id}/reject/`)

Permission: `IsCommunityAdmin`

Both views look up `ResidentProfile` by `id` scoped to `community`. Update `status` field. REJECT does not delete the record. Neither re-issues JWT (status changes are server-side; the client can check status on next app load).

### CommunitySettingsView (`PATCH /{slug}/settings/`)

Permission: `IsCommunityAdmin`

Updateable fields: `commission_pct`, add buildings (list of new names), `is_active` (deactivation).
Building removal is **not supported** in this endpoint — attempting to include a building name for removal returns 400 with a clear error.
When adding buildings: create new `Building` rows with `bulk_create(ignore_conflicts=True)` (duplicate names silently ignored).

### InviteRegenerateView (`POST /{slug}/invite/regenerate/`)

Permission: `IsCommunityAdmin`

Generates a new uppercase 6-char invite code, updates `Community.invite_code`. Returns updated invite code.

---

## Section 4: URL Configuration

`apps/communities/urls.py`:

```
register/                         → CommunityRegisterView
join/                             → JoinCommunityView
<slug>/                           → CommunityDetailView
<slug>/buildings/                 → BuildingListView
<slug>/settings/                  → CommunitySettingsView
<slug>/invite/regenerate/         → InviteRegenerateView
<slug>/residents/                 → ResidentListView
<slug>/residents/<int:pk>/approve/ → ResidentApproveView
<slug>/residents/<int:pk>/reject/  → ResidentRejectView
```

Include in `config/urls.py`:
```python
path('api/v1/communities/', include('apps.communities.urls', namespace='communities'))
```

---

## Section 5: Permissions Detail

`IsCommunityAdmin` (in `apps/core/permissions.py`) checks `'community_admin' in request.auth.payload['roles']`. Because JWT roles are scoped to `active_community`, this is sufficient for most cases.

**For slug-based endpoints**, add a secondary check in the view:
```python
def get_community_or_403(self, slug, request):
    """Return community if request.user is admin of it, else raise PermissionDenied."""
```
This prevents a community admin of community A from acting on community B's endpoints (JWT claim would pass, but the community IDs wouldn't match).

---

## Section 6: Django Admin

### Community Admin

Register `Community` with a custom `ModelAdmin`:
- List display: `name`, `city`, `pincode`, `admin_user`, `resident_count`, `vendor_count`, `is_active`, `is_reviewed`
- List filters: `is_active`, `is_reviewed`, `city`
- Custom actions: "Deactivate selected communities", "Mark as reviewed", "Regenerate invite codes"
- Inline: `BuildingInline` (TabularInline)

### ResidentProfile Admin

Register `ResidentProfile`:
- List display: `user` (phone), `community`, `flat`, `user_type`, `status`, `joined_at`
- List filters: `status`, `community`, `user_type`
- Custom actions: "Approve selected", "Reject selected"
- Read-only fields: `joined_at`, `user`

---

## Section 7: Migration Strategy

The `Community` stub from split 01 must be extended, not replaced. The migration:

1. `AddField` for all new Community fields (with defaults where required: `city=''`, `pincode=''`, `address=''`, `admin_user=None` initially nullable then made non-null after data migration, `commission_pct=7.50`, `invite_code=''`, `is_reviewed=False`, `resident_count=0`, `vendor_count=0`)
2. `CreateModel` for `Building`, `Flat`, `ResidentProfile`
3. `AddConstraint` / `AlterField` for uniqueness

If there are existing test communities from split 01, a data migration may be needed to populate required fields. In practice, test data can be cleared.

---

## Section 8: Testing Strategy

### Test File Layout

```
apps/communities/tests/
├── factories.py     # CommunityFactory, BuildingFactory, FlatFactory, ResidentProfileFactory
├── conftest.py      # Shared fixtures: api_client, community_with_buildings, approved_resident
├── test_models.py   # Model-level constraint tests
└── test_views.py    # API endpoint tests
```

### Factories

Update `CommunityFactory` (exists from split 01 as stub) with all new fields. Add `BuildingFactory`, `FlatFactory`, `ResidentProfileFactory(status='APPROVED')`.

Use `factory_boy`'s `LazyAttribute` for `invite_code` (generate uppercase random) and `slug` (derived from name + city).

### Critical Test Cases

**Registration:**
- Society admin registers → receives invite_code, JWT updated with community_admin role
- Slug collision → second community with same name gets numeric suffix
- Missing buildings list → 400

**Join:**
- Valid invite code → ResidentProfile(status=PENDING) created, JWT updated, resident_count incremented
- Invalid invite code → 404 (not 400)
- Inactive community invite code → 400
- Second join attempt by same user → 400
- Two users join same flat → both succeed (no constraint violation)

**Approval:**
- Admin approves PENDING resident → status=APPROVED
- Admin rejects PENDING resident → status=REJECTED, record preserved
- REJECTED user attempts new join → 400 (existing ResidentProfile found)
- Resident attempts admin endpoint → 403

**Counter:**
- resident_count before join = N, after join = N+1
- Concurrent joins (test with threading or explicit F() SQL check) → no double-count

**JWT claims:**
- After join: `access_token.payload['community_id'] == community.id`
- After join: `'resident' in access_token.payload['roles']`

**Admin permission guard:**
- Community admin of community A cannot approve residents in community B → 403

**Building removal:**
- Remove building with no residents → 400 (not supported in MVP settings endpoint)
- Building with residents: confirm 400

### JWT Claim Inspection in Tests

```python
from rest_framework_simplejwt.tokens import AccessToken
payload = AccessToken(response.data['tokens']['access']).payload
assert payload['community_id'] == community.id
assert 'resident' in payload['roles']
```

---

## Key Design Decisions and Rationale

| Decision | Rationale |
|----------|-----------|
| Flat as separate model | Enables clean approval flow, future analytics, family sharing |
| All joins require admin approval (MVP) | Owner-vouching deferred; admin approval is simpler to implement and audit |
| REJECTED profiles never deleted | Prevents repeat queuing from bad actors |
| 404 for invalid invite code | Avoids enumeration attacks (OWASP recommendation) |
| invite_code stored uppercase | Index-compatible lookup without functional index overhead |
| F() for resident_count | Atomic SQL counter update; no application-level race condition |
| is_reviewed soft-launch | Communities immediately active; abuse handled reactively |
| Return both access + refresh on role change | Old refresh token would regenerate stale-claims access tokens |
