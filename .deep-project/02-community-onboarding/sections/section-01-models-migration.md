The codebase doesn't exist yet — this is a greenfield implementation. I have everything I need from the plan files. Now I'll generate the section content.

# Section 01: Models and Migration

## Overview

This is the foundational section for split 02 (Community Onboarding). All other sections in this split depend on it. You will replace the minimal `Community` stub left by split 01, add three new models (`Building`, `Flat`, `ResidentProfile`), implement model-level helpers (invite code generation, slug generation, floor inference), and write the Django migration that extends the existing schema without dropping the `communities_community` table.

**No other section needs to be complete before you start this one.**

---

## Dependencies on Split 01

Split 01 established the following — you must not modify these, only reference them:

- `apps/users/models.py` — `User` (phone-based auth, no username field), `UserRole` (`unique_together(user, role, community)`), `User.active_community` FK pointing at `communities.Community`
- `apps/users/serializers.py` — `CustomTokenObtainPairSerializer.get_token(user)` reads `user.active_community` at call time to embed `community_id` and `roles[]` in the JWT
- `apps/core/permissions.py` — `IsCommunityAdmin`, `IsResidentOfCommunity`, `IsVendorOfCommunity`, `IsPlatformAdmin`
- `apps/core/exceptions.py` — Custom DRF exception handler normalizing errors to `{"error": "...", "detail": "..."}`
- `apps/communities/models.py` — A minimal `Community` stub containing only `name` (CharField), `is_active` (BooleanField), and timestamps (`created_at`, `updated_at`)

The existing stub already has FK relationships pointing at it from `apps/users`. The migration **must not drop or recreate the `communities_community` table** — only add columns and create new tables.

---

## Files to Create / Modify

| Path | Action |
|------|--------|
| `apps/communities/models.py` | Replace stub content with full model definitions |
| `apps/communities/migrations/0002_community_full_schema.py` | New migration (or appropriately numbered) that adds fields to Community and creates Building, Flat, ResidentProfile |
| `apps/communities/tests/__init__.py` | Create empty |
| `apps/communities/tests/test_models.py` | Create with test stubs for all model-level behavior |

---

## Tests First

File: `apps/communities/tests/test_models.py`

Run with: `uv run pytest apps/communities/tests/test_models.py`

### Community model tests

```python
class TestCommunityInviteCode:
    def test_invite_code_auto_generated_on_save_when_blank(self):
        """A Community saved with no invite_code should have a non-blank
        uppercase alphanumeric code of exactly 6 characters afterwards."""

    def test_invite_code_is_uppercase(self):
        """The generated invite_code must contain only uppercase letters and digits."""

    def test_invite_code_collision_retries_without_raising_integrity_error(self):
        """If the first generated code collides with an existing one, the model
        retries until it finds a unique code rather than surfacing IntegrityError."""

    def test_invite_code_uniqueness_at_db_level(self):
        """Two communities cannot have the same invite_code (unique=True on field)."""


class TestCommunitySlug:
    def test_slug_derived_from_name_and_city(self):
        """slugify(name + '-' + city) should be stored in slug field."""

    def test_duplicate_slug_gets_numeric_suffix(self):
        """Second community with same name+city gets '-2' suffix; third gets '-3'."""

    def test_slug_not_updated_after_creation(self):
        """Changing name or city on an existing Community must not alter slug."""


class TestCommunityDefaults:
    def test_is_reviewed_defaults_to_false(self):
        """Newly created Community.is_reviewed must be False."""

    def test_resident_count_starts_at_zero(self):
        """Community.resident_count must be 0 on creation."""

    def test_f_expression_increment_is_atomic(self):
        """After F('resident_count') + 1 update, resident_count == 1."""
```

### Building model tests

```python
class TestBuildingModel:
    def test_building_belongs_to_community(self):
        """Building.community FK should resolve to the correct Community."""

    def test_unique_together_community_name(self):
        """Creating two Buildings with the same community+name raises IntegrityError."""

    def test_different_communities_can_share_building_names(self):
        """Same building name is allowed for two different communities."""
```

### Flat model tests

```python
class TestFlatModel:
    def test_unique_together_building_flat_number(self):
        """Duplicate (building, flat_number) raises IntegrityError."""

    def test_floor_inference_three_digit_number(self):
        """flat_number='304' should infer floor=3."""

    def test_floor_inference_four_digit_number(self):
        """flat_number='1205' should infer floor=12."""

    def test_floor_inference_non_numeric_returns_none(self):
        """flat_number='A4' or 'GF' should leave floor=None without raising."""

    def test_floor_inference_two_digit_number(self):
        """flat_number='12' should infer floor=1."""
```

### ResidentProfile model tests

```python
class TestResidentProfileModel:
    def test_one_to_one_user_prevents_second_profile(self):
        """Creating a second ResidentProfile for the same User raises IntegrityError."""

    def test_two_profiles_can_share_same_flat(self):
        """Two different users with the same Flat FK both save without error."""

    def test_status_defaults_to_pending(self):
        """ResidentProfile.status must be 'PENDING' on creation."""

    def test_user_type_rejects_invalid_choice(self):
        """Assigning an unknown user_type and calling full_clean() raises ValidationError."""

    def test_rejected_record_persists(self):
        """Setting status='REJECTED' and saving does not delete the record."""
```

---

## Implementation Details

### `apps/communities/models.py`

Replace the entire file. Import these at the top: `import secrets`, `import string`, `from django.utils.text import slugify`, `from django.db.models import F`.

#### Community model

Keep the existing `name`, `is_active`, `created_at`, `updated_at` fields exactly as they were (same types, same defaults) so the migration only adds columns. Then add:

| Field | Type | Notes |
|-------|------|-------|
| `slug` | `SlugField(unique=True, max_length=120, blank=True)` | Populated by the registration view, not `save()` |
| `city` | `CharField(max_length=100, blank=True, default='')` | blank default required for migration compatibility |
| `pincode` | `CharField(max_length=6, blank=True, default='')` | |
| `address` | `TextField(blank=True, default='')` | |
| `admin_user` | `ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL, related_name='administered_communities')` | Nullable initially; set at registration time |
| `commission_pct` | `DecimalField(max_digits=5, decimal_places=2, default=Decimal('7.50'))` | |
| `invite_code` | `CharField(max_length=6, unique=True, blank=True, db_index=True)` | |
| `resident_count` | `PositiveIntegerField(default=0)` | Never updated via save() |
| `vendor_count` | `PositiveIntegerField(default=0)` | Never updated via save() |
| `is_reviewed` | `BooleanField(default=False)` | |

**`save()` override** — only auto-generate `invite_code` when the field is blank. Do not auto-generate slug here; slug is created by the registration view.

Invite code generation logic (implement as a module-level helper `_generate_invite_code()`):

```python
def _generate_invite_code() -> str:
    """Return a random 6-character uppercase alphanumeric string."""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(random.choices(alphabet, k=6))
```

In `Community.save()`, if `invite_code` is blank, call `_generate_invite_code()` in a loop, checking `Community.objects.filter(invite_code=candidate).exists()` until a non-colliding code is found. Assign before calling `super().save()`.

**Slug generation** is done in the registration view (not in `save()`), but the logic needs to be importable. Implement as a module-level helper:

```python
def generate_unique_slug(name: str, city: str) -> str:
    """Return a slug derived from name+city, with numeric suffix on collision."""
```

The helper should try `slugify(f"{name}-{city}")` first, then `slugify(f"{name}-{city}-2")`, `-3`, etc., checking `Community.objects.filter(slug=candidate).exists()` on each attempt.

**Counter updates** — document in the model docstring that `resident_count` and `vendor_count` must only be updated with:
```python
Community.objects.filter(pk=self.pk).update(resident_count=F('resident_count') + 1)
```
Never use `community.resident_count += 1; community.save()`.

#### Building model

```python
class Building(models.Model):
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='buildings')
    name = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('community', 'name')

    def __str__(self): ...
```

#### Flat model

```python
class Flat(models.Model):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='flats')
    flat_number = models.CharField(max_length=20)
    floor = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = ('building', 'flat_number')

    def __str__(self): ...
```

**Floor inference** — implement as a module-level function `infer_floor(flat_number: str) -> int | None`. The rule: if `flat_number` starts with a run of digits of length >= 2, the floor is all digits before the last two. Examples:
- `"304"` → digits = `"304"`, floor prefix = `"3"` → `floor = 3`
- `"1205"` → digits = `"12"`, floor prefix = `"12"` → `floor = 12`
- `"12"` → two digits, floor prefix = `"1"` → `floor = 1`
- `"A4"` → does not start with digit → `None`
- `"GF"` → not numeric → `None`
- `"5"` → only one digit → `None` (ambiguous)

The function must never raise — wrap in try/except and return `None` on any failure. The `Flat` model does not call this automatically; the join view calls it before `get_or_create`.

#### ResidentProfile model

```python
class ResidentProfile(models.Model):
    class UserType(models.TextChoices):
        OWNER_RESIDING = 'OWNER_RESIDING', 'Owner (Residing)'
        OWNER_NON_RESIDING = 'OWNER_NON_RESIDING', 'Owner (Non-Residing)'
        TENANT = 'TENANT', 'Tenant'
        FAMILY_DEPENDENT = 'FAMILY_DEPENDENT', 'Family Dependent'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='resident_profile',
    )
    community = models.ForeignKey(
        Community,
        on_delete=models.CASCADE,
        related_name='residents',
    )
    flat = models.ForeignKey(
        Flat,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='residents',
    )
    user_type = models.CharField(max_length=20, choices=UserType.choices)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self): ...
```

Note: There is no `is_verified` field. The `status` field replaces the original spec's `is_verified=True` on creation pattern.

Note: There is no `unique_together` on `(community, flat)` — multiple residents sharing one flat is intentional.

---

## Migration Strategy

The migration must handle the transition from the split 01 stub without data loss.

**File:** `apps/communities/migrations/0002_community_full_schema.py` (or the next available number — check `apps/communities/migrations/` for existing files first).

The migration should consist of:

1. `AddField` operations for every new `Community` field with database-safe defaults:
   - `slug`: `default=''`, then `AlterField` to make it unique after backfilling (or supply a callable default that generates empty string, then handle uniqueness separately if there is existing data)
   - `city`, `pincode`, `address`: `default=''`
   - `admin_user`: `null=True` (already nullable by design)
   - `commission_pct`: `default=Decimal('7.50')`
   - `invite_code`: `default=''`, then add uniqueness — if migrating from real data with multiple blank codes, a data migration step is needed before adding the unique constraint
   - `resident_count`, `vendor_count`: `default=0`
   - `is_reviewed`: `default=False`

2. `CreateModel` for `Building` with `unique_together`

3. `CreateModel` for `Flat` with `unique_together`

4. `CreateModel` for `ResidentProfile`

**Important:** If split 01 test fixtures created `Community` rows with blank `invite_code`, those rows will collide when you add `unique=True`. For the migration to succeed on a database with existing test data, either:
- Add a data migration step between `AddField(invite_code, default='')` and `AlterField(invite_code, unique=True)` that generates unique codes for existing rows, or
- Accept that test databases are cleared between splits (document this assumption clearly in the migration).

For a clean installation (no prior data), a single migration file is sufficient.

---

## Key Design Constraints (Do Not Violate)

1. `invite_code` lookups always use `exact` match (not `iexact`) because codes are stored and validated as uppercase. The `save()` method normalizes to uppercase before storing.

2. `resident_count` and `vendor_count` are **never** updated via `model_instance.save()`. The only valid update pattern is `Community.objects.filter(pk=pk).update(resident_count=F('resident_count') + 1)`.

3. `slug` is never auto-updated after creation. The registration view generates it once; subsequent name or city changes to the community do not change the slug.

4. REJECTED `ResidentProfile` records are never deleted. This is enforced at the view layer, not the model layer — there is no `on_delete` hook preventing it. The test verifies that a REJECTED record still exists in the database after status update.

5. The `OneToOneField` on `ResidentProfile.user` means a user can belong to exactly one community. A second join attempt by the same user must be caught in the serializer validation layer (section 02), but the database constraint backs it up.

---

## Acceptance Checklist

Before marking this section done, verify:

- [ ] `uv run python manage.py migrate` completes without errors from a fresh database
- [ ] `uv run python manage.py migrate` is idempotent (running twice is safe)
- [ ] All existing split 01 migrations still pass (`uv run python manage.py showmigrations`)
- [ ] `uv run pytest apps/communities/tests/test_models.py` — all test stubs collected (even if some are `pass`/skipped, none should error at import time)
- [ ] `infer_floor("304") == 3` in a Python shell
- [ ] `infer_floor("A4") is None` in a Python shell
- [ ] `Community()` with no invite_code, after `.save()`, has a 6-char uppercase `invite_code`
- [ ] Two `Community` objects cannot share the same `invite_code` (IntegrityError at DB level)
- [ ] Two `ResidentProfile` objects with the same `flat` but different `user` — both save without error