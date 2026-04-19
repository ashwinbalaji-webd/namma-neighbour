# TDD Plan: 02-Community Onboarding

_Mirrors sections from `claude-plan.md`. Testing stack: pytest-django, factory_boy, APIClient, freezegun, simplejwt AccessToken._

---

## Section 1: Models

### 1.1 Community

- Test: `invite_code` is auto-generated uppercase on save when blank
- Test: `invite_code` uniqueness — collision causes retry/regeneration, not an IntegrityError surfaced to caller
- Test: `slug` is derived from `slugify(name + '-' + city)` on registration
- Test: Duplicate slug → numeric suffix appended (e.g., `prestige-bengaluru-2`)
- Test: `is_reviewed` defaults to `False` on creation
- Test: `resident_count` starts at 0; direct `F()` update increments correctly

### 1.2 Building

- Test: `unique_together(community, name)` raises IntegrityError on duplicate
- Test: Building belongs to correct community after creation

### 1.3 Flat

- Test: `unique_together(building, flat_number)` — duplicate raises IntegrityError
- Test: Floor inference: `flat_number="304"` → `floor=3`
- Test: Floor inference: `flat_number="1205"` → `floor=12`
- Test: Floor inference fails gracefully for non-numeric patterns (e.g., `"A4"`) → `floor=None`

### 1.4 ResidentProfile

- Test: `OneToOneField(User)` — second ResidentProfile for same user raises IntegrityError
- Test: Two ResidentProfiles with same flat → both succeed (no DB constraint violated)
- Test: `status` defaults to `PENDING`
- Test: `user_type` rejects values outside the four choices
- Test: REJECTED record persists after explicit status update (not deleted)

---

## Section 2: Serializers

### CommunityRegistrationSerializer

- Test: Valid payload → validated_data contains community fields + buildings list
- Test: `pincode` not 6 digits → validation error
- Test: Empty `buildings` list → validation error
- Test: Duplicate building names within the list → validation error

### JoinCommunitySerializer

- Test: Valid invite_code (case-insensitive input, e.g., `"abc123"`) → resolves community
- Test: Non-existent invite_code → raises `NotFound` (404)
- Test: building_id not in the resolved community → validation error
- Test: User already has ResidentProfile → validation error (400)
- Test: Inactive community invite_code → validation error

### ResidentProfileSerializer

- Test: Output includes `flat` (nested), `user_type`, `status`, `joined_at`
- Test: Does not expose user's phone or other PII beyond what is needed

---

## Section 3: Views

### CommunityRegisterView (`POST /register/`)

- Test: Authenticated user registers → 201, community created, `invite_code` in response
- Test: `buildings` created (count matches input list)
- Test: `UserRole(role='community_admin', community=...)` created for registering user
- Test: `user.active_community` set to new community
- Test: Response includes `tokens.access` and `tokens.refresh`
- Test: JWT payload has `community_id` matching new community
- Test: Unauthenticated request → 401
- Test: Duplicate community name + city (slug collision) → still succeeds with suffix slug

### CommunityDetailView (`GET /{slug}/`)

- Test: Returns `name`, `city`, `slug`, `is_active`
- Test: Does NOT return `resident_count`, `commission_pct`, `invite_code`, `admin_user`
- Test: Non-existent slug → 404
- Test: No auth required

### BuildingListView (`GET /{slug}/buildings/`)

- Test: Returns list of building `id` + `name` for the community
- Test: No auth required

### JoinCommunityView (`POST /join/`)

- Test: Valid payload → ResidentProfile created with `status=PENDING`
- Test: `resident_count` incremented by 1 after join
- Test: Response includes `tokens.access` + `tokens.refresh`
- Test: JWT has `community_id` + `resident` in roles after join
- Test: `user.active_community` set to joined community
- Test: Invalid invite_code → 404
- Test: Same user joins twice → 400
- Test: Two different users join same flat → both succeed (201 each)
- Test: Flat `get_or_create` — joining same flat twice creates only one Flat row
- Test: Unauthenticated → 401

### ResidentListView (`GET /{slug}/residents/`)

- Test: Community admin can list residents (200, paginated)
- Test: `?status=PENDING` filter returns only pending residents
- Test: Resident (non-admin) → 403
- Test: Admin of community A cannot list residents of community B → 403
- Test: Pagination works (PAGE_SIZE=20)

### ResidentApproveView / ResidentRejectView

- Test: Admin approves PENDING → status becomes APPROVED (200)
- Test: Admin rejects PENDING → status becomes REJECTED (200), record still exists in DB
- Test: Approving non-existent profile → 404
- Test: Resident attempts approve endpoint → 403
- Test: Admin of wrong community → 403

### CommunitySettingsView (`PATCH /{slug}/settings/`)

- Test: Admin updates `commission_pct` → value saved
- Test: Admin adds new building names → Building rows created
- Test: Admin deactivates community → `is_active=False`
- Test: Non-admin → 403
- Test: Adding duplicate building name → silently ignored (ignore_conflicts)

### InviteRegenerateView (`POST /{slug}/invite/regenerate/`)

- Test: Admin calls → new `invite_code` returned, old code no longer works for join
- Test: New code is uppercase alphanumeric, 6 chars
- Test: Non-admin → 403

---

## Section 4: URL Configuration

- Test: All URL patterns resolve to correct view classes (use `django.urls.reverse`)
- Test: `namespace='communities'` works for `reverse('communities:register')`, etc.

---

## Section 5: Permissions

- Test: `IsCommunityAdmin` allows admin of correct community
- Test: `IsCommunityAdmin` blocks admin of different community (community_id mismatch in JWT)
- Test: `IsCommunityAdmin` blocks unauthenticated
- Test: `IsResidentOfCommunity` allows approved resident
- Test: `IsResidentOfCommunity` blocks non-resident

---

## Section 6: Django Admin

- Test: `Community` list page loads with custom display columns (smoke test)
- Test: "Mark as reviewed" action sets `is_reviewed=True` on selected communities
- Test: "Approve selected" action on ResidentProfile sets status=APPROVED
- Test: `BuildingInline` renders on Community change page (smoke test)

---

## Section 7: Migration

- Test: `python manage.py migrate` runs without errors from a clean state
- Test: Existing `Community` rows from split 01 are preserved after migration (no data loss)

---

## Section 8: Integration / Edge Cases

- Test: Full flow — register community → join as resident → admin approves → check JWT has correct claims at each step
- Test: Concurrent join attempts for same user (use `threading` or verify F() at DB level)
- Test: `resident_count` is correct after 3 sequential joins
- Test: REJECTED user tries to join again → 400 (ResidentProfile exists with REJECTED status)
- Test: Community with `is_active=False` → join attempt returns 400
