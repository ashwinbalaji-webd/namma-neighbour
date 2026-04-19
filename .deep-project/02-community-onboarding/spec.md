# Spec: 02-community-onboarding

## Purpose
Enable gated communities to self-register on the platform and residents to join their community. Establishes the community scoping model that all other modules depend on.

## Dependencies
- **01-foundation** must be complete (User model, JWT auth, DRF permission base classes)

## Deliverables

### 1. Models

```python
# apps/communities/models.py

class Community(TimestampedModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)          # auto-generated from name
    city = models.CharField(max_length=100)
    pincode = models.CharField(max_length=6)
    address = models.TextField()
    admin_user = models.ForeignKey(User, on_delete=models.PROTECT,
                                   related_name='administered_communities')
    commission_pct = models.DecimalField(max_digits=5, decimal_places=2,
                                          default=Decimal('7.50'))
    # Invite system
    invite_code = models.CharField(max_length=10, unique=True)  # auto-generated
    is_active = models.BooleanField(default=True)
    # Stats (denormalized for performance)
    resident_count = models.PositiveIntegerField(default=0)
    vendor_count = models.PositiveIntegerField(default=0)

class Building(TimestampedModel):
    community = models.ForeignKey(Community, on_delete=models.CASCADE,
                                   related_name='buildings')
    name = models.CharField(max_length=50)        # "Tower A", "Block 1", "Main Building"

    class Meta:
        unique_together = ('community', 'name')

class ResidentProfile(TimestampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE,
                                 related_name='resident_profile')
    community = models.ForeignKey(Community, on_delete=models.PROTECT)
    building = models.ForeignKey(Building, on_delete=models.SET_NULL,
                                  null=True, blank=True)
    flat_number = models.CharField(max_length=20)
    is_verified = models.BooleanField(default=True)   # verified on join via OTP
    joined_at = models.DateTimeField(auto_now_add=True)
```

### 2. API Endpoints

#### Community Registration (Society Admin)
```
POST /api/v1/communities/register/
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
- Authenticated user becomes the community admin
- Auto-generates `slug` (kebab-case from name + city) and `invite_code` (6-char alphanumeric)
- Creates Building records for each entry in `buildings[]`
- Admin gets `community_admin` role injected into JWT (issue new token)
- Returns community details including `invite_code`

#### Get Community Details
```
GET /api/v1/communities/{slug}/
```
Public endpoint — no auth. Returns community name, city, building list (for join flow). Does not expose resident count or commission settings.

#### Join Community (Resident)
```
POST /api/v1/communities/join/
```
Payload:
```json
{
  "invite_code": "ABC123",
  "building_id": 5,
  "flat_number": "304"
}
```
- Creates ResidentProfile for authenticated user
- One user can be a resident of only one community (validated)
- Increments `community.resident_count`
- Issues updated JWT with `community_id` and `resident` role
- Returns resident profile

#### List Buildings in Community
```
GET /api/v1/communities/{slug}/buildings/
```
Used during join flow to let resident select their tower/block.

#### Community Admin: Update Settings
```
PATCH /api/v1/communities/{slug}/settings/
Permission: IsCommunityAdmin
```
Can update: `commission_pct`, add/remove buildings, deactivate community.

#### Generate New Invite Code
```
POST /api/v1/communities/{slug}/invite/regenerate/
Permission: IsCommunityAdmin
```
Invalidates old invite code, generates new one. Useful if code is shared publicly.

#### Community Admin: List Residents
```
GET /api/v1/communities/{slug}/residents/
Permission: IsCommunityAdmin
```
Paginated list with flat number, join date, name. For admin oversight.

### 3. Invite Link Format

Deep link: `nammaNeighbor://join?code=ABC123`
Web fallback: `https://app.nammaNeighbor.in/join?code=ABC123`

When opened on mobile, the app should pre-fill the invite code in the join form.

### 4. Permission Classes (implement in 01, used here)

`IsCommunityAdmin` — checks JWT `roles` contains `community_admin` AND `community_id` matches the requested community's ID.

`IsResidentOfCommunity` — checks JWT `roles` contains `resident` AND `community_id` matches.

### 5. JWT Token Update on Role Change

When a user joins a community or becomes a community admin, their JWT claims change. The API must return a new `access` token alongside the action response so the client can update its stored token without requiring a fresh login.

Pattern: include `tokens: { access: "...", refresh: "..." }` in the response body of `join/` and `register/` endpoints.

### 6. Django Admin

Custom admin for Community:
- Display: name, city, pincode, admin_user, resident_count, vendor_count, is_active
- Actions: deactivate community, regenerate invite code
- Inline: Buildings

### 7. Celery Tasks

None required for this split. All operations are synchronous.

### 8. Validation Rules

- A user can only be a resident of **one** community (enforce at model level with OneToOne ResidentProfile)
- A user can be community admin of **multiple** communities (for future multi-community admin use case)
- `flat_number` + `building` + `community` combination must be unique (one household per flat)
- `pincode` must be exactly 6 digits (India format)
- `invite_code` is case-insensitive on lookup

## Acceptance Criteria

1. Society admin registers community → receives invite code in response
2. `nammaNeighbor://join?code=ABC123` deep link works (tested in mobile app later, but URL format defined here)
3. Resident joins with valid invite code → ResidentProfile created, JWT updated with `resident` role and `community_id`
4. Resident cannot join two communities — second join attempt returns 400
5. Same flat in same building cannot have two residents (unique constraint enforced)
6. `GET /api/v1/communities/{slug}/` returns building list without exposing sensitive admin data
7. `IsCommunityAdmin` permission blocks residents from accessing admin-only endpoints (403)
8. Community admin can add a building to an existing community
9. `community.resident_count` increments correctly on each join
10. Invalid invite code returns 404 (not 400, to avoid code enumeration attacks)
