# Consolidated Spec: 02-Community Onboarding

_Combines: original spec + codebase research + interview answers_

---

## Purpose

Enable gated communities to self-register on the NammaNeighbor platform and residents to join their community. Establishes the community scoping model (Community → Building → Flat → ResidentProfile) that all downstream modules depend on.

**Dependency:** Split 01 (foundation) is complete. `User`, `UserRole`, `CustomTokenObtainPairSerializer`, and permission classes exist.

---

## 1. Data Model

### 1.1 Community

```python
class Community(TimestampedModel):
    name        = CharField(max_length=200)
    slug        = SlugField(unique=True)           # auto-generated: kebab-case(name + city)
    city        = CharField(max_length=100)
    pincode     = CharField(max_length=6)           # exactly 6 digits (India format)
    address     = TextField()
    admin_user  = ForeignKey(User, PROTECT, related_name='administered_communities')
    commission_pct = DecimalField(max_digits=5, decimal_places=2, default=Decimal('7.50'))

    # Invite
    invite_code = CharField(max_length=10, unique=True)  # stored UPPERCASE, 6-char alphanumeric
    is_active   = BooleanField(default=True)

    # Soft-launch review flag
    is_reviewed = BooleanField(default=False)  # platform admin reviews via Django admin

    # Denormalized stats (updated via F() expressions)
    resident_count = PositiveIntegerField(default=0)
    vendor_count   = PositiveIntegerField(default=0)
```

**Validation:** `pincode` must be exactly 6 digits.
**Slug:** `slugify(name + '-' + city)`, deduplicated with a numeric suffix if collision.
**Invite code:** 6-char uppercase alphanumeric, randomly generated, stored uppercase, looked up with `exact` (not `iexact`).

### 1.2 Building

```python
class Building(TimestampedModel):
    community = ForeignKey(Community, CASCADE, related_name='buildings')
    name      = CharField(max_length=50)   # "Tower A", "Block 1"

    class Meta:
        unique_together = ('community', 'name')
```

**Removal constraint:** Blocked (400) if any `Flat` in this building has a `ResidentProfile`.

### 1.3 Flat _(new model, not in original spec)_

```python
class Flat(TimestampedModel):
    building    = ForeignKey(Building, CASCADE, related_name='flats')
    flat_number = CharField(max_length=20)
    floor       = IntegerField(null=True, blank=True)

    class Meta:
        unique_together = ('building', 'flat_number')
```

**Floor auto-population:** If flat_number follows a consistent numbering scheme, compute floor during creation (e.g., flat "304" → floor 3). This is optional/best-effort.

### 1.4 ResidentProfile

```python
USER_TYPE_CHOICES = [
    ('OWNER_RESIDING',     'Owner (Residing)'),
    ('OWNER_NON_RESIDING', 'Owner (Non-Residing)'),
    ('TENANT',             'Tenant'),
    ('FAMILY_DEPENDENT',   'Family / Dependent'),
]

STATUS_CHOICES = [
    ('PENDING',  'Pending'),
    ('APPROVED', 'Approved'),
    ('REJECTED', 'Rejected'),
]

class ResidentProfile(TimestampedModel):
    user      = OneToOneField(User, CASCADE, related_name='resident_profile')
    community = ForeignKey(Community, PROTECT, related_name='residents')
    flat      = ForeignKey(Flat, SET_NULL, null=True, blank=True, related_name='residents')
    user_type = CharField(choices=USER_TYPE_CHOICES, max_length=25)
    status    = CharField(choices=STATUS_CHOICES, default='PENDING', max_length=20)
    joined_at = DateTimeField(auto_now_add=True)
```

**Key constraints:**
- `user` is OneToOne → one ResidentProfile per User (one community membership)
- Multiple ResidentProfiles can reference the same Flat (family sharing)
- REJECTED profiles are **never deleted** — prevents re-queuing abuse

---

## 2. Approval Flow (MVP)

```
Resident uses community invite code
    → ResidentProfile created (status=PENDING)
    → JWT issued with community_id + resident role (limited access)
    → Community admin reviews pending list
    → Admin APPROVES → status=APPROVED → full platform access
    → Admin REJECTS → status=REJECTED → record kept, user notified
```

**Post-MVP (not in scope):** Owner-level vouching for family/tenant approval.

---

## 3. JWT Token Strategy

### Token claims shape (from split 01 `CustomTokenObtainPairSerializer`):
```json
{
  "phone": "+91XXXXXXXXXX",
  "community_id": 5,
  "roles": ["resident"]
}
```

### Re-issuance on join/register:
```python
# After updating user.active_community:
refresh = CustomTokenObtainPairSerializer.get_token(user)
return Response({
    "...": "...",
    "tokens": {
        "access": str(refresh.access_token),
        "refresh": str(refresh)
    }
})
```

`user.active_community` **must** be set before calling `get_token()` — the serializer reads it to scope roles.

### PENDING resident JWT:
- Issued immediately on join (same token shape, `roles: ['resident']`)
- Platform feature gating is done at the application layer by checking `ResidentProfile.status`, not via JWT claims

---

## 4. API Endpoints

### 4.1 Community Registration
```
POST /api/v1/communities/register/
Auth: IsAuthenticated
```
Payload:
```json
{
  "name": "Prestige Lakeside Habitat",
  "city": "Bengaluru",
  "pincode": "560103",
  "address": "Whitefield, Bengaluru",
  "buildings": ["Tower A", "Tower B", "Tower C"]
}
```
- Authenticated user becomes `admin_user`
- Auto-generates `slug` and `invite_code` (uppercase)
- Creates `Building` records in a single `transaction.atomic()` + `bulk_create()`
- Creates `UserRole(role='community_admin', community=community)` for the registering user
- Sets `user.active_community = community` and saves
- Re-issues JWT (new access + refresh)
- Community created with `is_active=True`, `is_reviewed=False`
- Returns community details + `invite_code` + new tokens

### 4.2 Get Community Details
```
GET /api/v1/communities/{slug}/
Auth: None (public)
Throttle: AnonRateThrottle
```
Returns: name, city, building list. **Does not** expose resident_count, commission_pct, invite_code.

### 4.3 List Buildings
```
GET /api/v1/communities/{slug}/buildings/
Auth: None (public)
```
Used by join flow for building selection.

### 4.4 Join Community
```
POST /api/v1/communities/join/
Auth: IsAuthenticated
```
Payload:
```json
{
  "invite_code": "ABC123",
  "building_id": 5,
  "flat_number": "304",
  "user_type": "TENANT"
}
```
- Lookup community by `invite_code` (exact, case-insensitive input → normalized to uppercase before lookup)
- Invalid code → 404 (`rest_framework.exceptions.NotFound`) — not 400, to avoid enumeration
- Check user doesn't already have a ResidentProfile → 400 if exists
- Get-or-create `Flat(building=building, flat_number=flat_number)` (with optional floor inference)
- Create `ResidentProfile(status=PENDING, ...)`
- Increment `community.resident_count` via `F()` expression
- Set `user.active_community = community`, save
- Re-issue JWT
- Returns: ResidentProfile data + new tokens
- **Note:** 404 is returned for invalid invite_code (not 400)

### 4.5 Resident Approval (Admin)
```
POST /api/v1/communities/{slug}/residents/{id}/approve/
POST /api/v1/communities/{slug}/residents/{id}/reject/
Auth: IsCommunityAdmin (+ community_id must match)
```
- Changes `ResidentProfile.status` to APPROVED or REJECTED
- REJECTED: record kept in DB

### 4.6 List Residents (Admin)
```
GET /api/v1/communities/{slug}/residents/
Auth: IsCommunityAdmin
```
Paginated (PAGE_SIZE=20). Supports `?status=PENDING` filter. Returns: flat, user_type, status, join date, name/phone.

### 4.7 Update Settings (Admin)
```
PATCH /api/v1/communities/{slug}/settings/
Auth: IsCommunityAdmin
```
Can update: `commission_pct`, add buildings, deactivate community.
**Cannot remove a building** if it has any ResidentProfile → 400.

### 4.8 Regenerate Invite Code
```
POST /api/v1/communities/{slug}/invite/regenerate/
Auth: IsCommunityAdmin
```
Generates new uppercase 6-char alphanumeric code, replaces old one.

---

## 5. Permission Classes (already in apps/core/permissions.py)

`IsCommunityAdmin`:
- `'community_admin' in request.auth.payload['roles']`
- View-level: verify `community.id == request.auth.payload['community_id']`

`IsResidentOfCommunity`:
- `'resident' in request.auth.payload['roles']`

---

## 6. Counter Denormalization

```python
# In JoinCommunityView.post() — atomic, no race condition
Community.objects.filter(pk=community.pk).update(
    resident_count=F('resident_count') + 1
)
community.refresh_from_db()
```

No signals. Inline `F()` in the view — direct, testable, single code path.

---

## 7. Django Admin

Custom admin for `Community`:
- **Display**: name, city, pincode, admin_user, resident_count, vendor_count, is_active, is_reviewed
- **Actions**: deactivate community, regenerate invite code, mark as reviewed
- **Inlines**: Buildings

Custom admin for `ResidentProfile`:
- **Display**: user (phone), community, flat, user_type, status, joined_at
- **Actions**: approve, reject
- **Filters**: status, community

---

## 8. Validation Rules Summary

| Rule | Enforcement |
|------|-------------|
| pincode = exactly 6 digits | Serializer validator |
| One ResidentProfile per User | OneToOneField(User) |
| One community per User | OneToOneField constraint on ResidentProfile |
| Multiple residents per flat | Allowed (no unique on flat) |
| invite_code stored uppercase | Model save / serializer |
| Invalid invite_code → 404 | NotFound exception (not 400) |
| Building removal blocked if residents exist | View-level check, return 400 |
| REJECTED profile kept in DB | Never deleted, status=REJECTED |

---

## 9. Invite Link Format

Deep link: `nammaNeighbor://join?code=ABC123`
Web fallback: `https://app.nammaNeighbor.in/join?code=ABC123`

---

## 10. Out of Scope for This Split

- Owner-level vouching for family/tenant approval (post-MVP)
- Flat type field (1BHK/2BHK) — deferred
- Push notifications for approval/rejection
- Celery tasks (all operations synchronous)
