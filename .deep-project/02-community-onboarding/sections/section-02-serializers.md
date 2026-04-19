Now I have all the context I need. Let me generate the section content for `section-02-serializers`.

# Section 02: Serializers

## Overview

This section implements all DRF serializers for the communities app. Serializers live in `apps/communities/serializers.py` and serve as the validation and data-shaping layer between HTTP payloads and the model layer. Views in sections 03, 04, and 05 all import from this file.

**Dependency:** Section 01 (models-migration) must be complete before this section. The serializers import `Community`, `Building`, `Flat`, and `ResidentProfile` from `apps/communities/models`.

---

## File to Create

`/var/www/html/MadGirlfriend/namma-neighbour/apps/communities/serializers.py`

---

## Tests First

These test stubs are for `apps/communities/tests/test_serializers.py` (or can be included in `test_views.py` if preferred). The test command is `uv run pytest apps/communities/`.

### CommunityRegistrationSerializer Tests

```python
class TestCommunityRegistrationSerializer:
    def test_valid_payload_contains_community_fields_and_buildings(self):
        """Valid input → validated_data has name, city, pincode, address, buildings list."""

    def test_pincode_must_be_6_digits(self):
        """pincode='12345' (5 digits) or '12345A' (non-numeric) → ValidationError."""

    def test_empty_buildings_list_raises_validation_error(self):
        """buildings=[] → ValidationError."""

    def test_duplicate_building_names_in_list_raises_validation_error(self):
        """buildings=['Tower A', 'Tower A'] → ValidationError."""
```

### JoinCommunitySerializer Tests

```python
class TestJoinCommunitySerializer:
    def test_valid_invite_code_case_insensitive_resolves_community(self):
        """Input invite_code='abc123' resolves community whose invite_code='ABC123'."""

    def test_nonexistent_invite_code_raises_not_found(self):
        """Unknown invite_code → raises NotFound (HTTP 404, not 400)."""

    def test_building_id_not_in_resolved_community_raises_validation_error(self):
        """building_id belonging to a different community → ValidationError."""

    def test_user_already_has_resident_profile_raises_validation_error(self):
        """User with existing ResidentProfile → ValidationError (400)."""

    def test_inactive_community_invite_code_raises_validation_error(self):
        """community.is_active=False → ValidationError."""
```

### ResidentProfileSerializer Tests

```python
class TestResidentProfileSerializer:
    def test_output_includes_nested_flat_user_type_status_joined_at(self):
        """Serialized output has flat (nested), user_type, status, joined_at fields."""

    def test_output_does_not_expose_user_phone_or_pii(self):
        """phone, email, and other User PII are absent from serialized output."""
```

---

## Serializers to Implement

### 1. CommunityRegistrationSerializer

**Purpose:** Validates `POST /register/` input and creates Community + Building records atomically.

**Input fields:**
- `name` — CharField
- `city` — CharField
- `pincode` — CharField; must match `^[0-9]{6}$` (exactly 6 numeric digits)
- `address` — CharField
- `buildings` — `ListField(child=CharField(max_length=50), write_only=True)`; not a model field

**Validation rules (in `validate()` or individual `validate_<field>` methods):**
- `pincode` regex check — raise `serializers.ValidationError` on mismatch
- `buildings` must be non-empty — raise `ValidationError` if list is empty
- Building names within `buildings` must be unique in the list (use `len(set(buildings)) != len(buildings)`) — raise `ValidationError` on duplicates

**`create()` method:**
- Pop `buildings` from `validated_data` before calling `Community.objects.create()`
- `admin_user` is NOT in the payload — it is injected by the view via `self.context['request'].user` before or inside `create()`
- Wrap the entire body in `transaction.atomic()`: create the `Community`, then `Building.objects.bulk_create([Building(community=community, name=n) for n in buildings])`
- Return the created community

**Output:** Responds with full community detail including `invite_code`. The view uses this serializer's output data for the response.

Stub:
```python
class CommunityRegistrationSerializer(serializers.ModelSerializer):
    buildings = serializers.ListField(
        child=serializers.CharField(max_length=50),
        write_only=True
    )

    class Meta:
        model = Community
        fields = ['name', 'city', 'pincode', 'address', 'buildings',
                  'slug', 'invite_code', 'is_active']
        read_only_fields = ['slug', 'invite_code', 'is_active']

    def validate_pincode(self, value): ...
    def validate_buildings(self, value): ...
    def validate(self, attrs): ...
    def create(self, validated_data): ...
```

---

### 2. CommunityDetailSerializer

**Purpose:** Public read-only representation of a community. Used by `GET /{slug}/`.

**Fields to include:** `name`, `city`, `slug`, `is_active`

**Fields deliberately excluded:** `resident_count`, `vendor_count`, `commission_pct`, `invite_code`, `admin_user`

Stub:
```python
class CommunityDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Community
        fields = ['name', 'city', 'slug', 'is_active']
```

---

### 3. BuildingSerializer

**Purpose:** Returns building list for `GET /{slug}/buildings/`. Used during the join flow by the mobile client to populate a picker.

**Fields:** `id`, `name`

Stub:
```python
class BuildingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Building
        fields = ['id', 'name']
```

---

### 4. FlatSerializer

**Purpose:** Nested read-only representation of a flat. Embedded inside `ResidentProfileSerializer`.

**Fields:** `id`, `flat_number`, `floor`, `building_id`

Stub:
```python
class FlatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Flat
        fields = ['id', 'flat_number', 'floor', 'building_id']
```

---

### 5. JoinCommunitySerializer

**Purpose:** Validates `POST /join/` input. Resolves the community and building from the payload so the view does not need to re-query.

**Input fields:**
- `invite_code` — CharField
- `building_id` — IntegerField
- `flat_number` — CharField
- `user_type` — ChoiceField using `ResidentProfile.UserType.choices`

**Validation logic (all in `validate()`):**

1. Normalize invite code: `invite_code = attrs['invite_code'].upper()`
2. Look up community: `Community.objects.get(invite_code=invite_code)` — catch `Community.DoesNotExist` and raise `rest_framework.exceptions.NotFound` (not `ValidationError`). This returns a 404, not a 400 — this is intentional to prevent invite code enumeration.
3. Check `community.is_active` — raise `ValidationError` if `False`
4. Look up building: `Building.objects.get(id=attrs['building_id'], community=community)` — catch `Building.DoesNotExist` and raise `ValidationError`
5. Check for existing `ResidentProfile`: `ResidentProfile.objects.filter(user=request_user).exists()` — raise `ValidationError` if found. The requesting user is available via `self.context['request'].user`
6. Attach resolved objects: `attrs['community'] = community`, `attrs['building'] = building`
7. Return `attrs`

Note: The view retrieves `community` and `building` directly from `serializer.validated_data` after calling `is_valid()`.

Stub:
```python
class JoinCommunitySerializer(serializers.Serializer):
    invite_code = serializers.CharField()
    building_id = serializers.IntegerField()
    flat_number = serializers.CharField(max_length=20)
    user_type = serializers.ChoiceField(choices=ResidentProfile.UserType.choices)

    def validate(self, attrs): ...
```

---

### 6. ResidentProfileSerializer

**Purpose:** Output serializer for `ResidentProfile`. Used in join responses, resident list, and approve/reject responses.

**Fields:** `id`, `user_type`, `status`, `flat` (nested `FlatSerializer`), `joined_at`

Do not expose `user` FK, user phone, or any other PII. The profile is always scoped to a known community in its view context.

Stub:
```python
class ResidentProfileSerializer(serializers.ModelSerializer):
    flat = FlatSerializer(read_only=True)

    class Meta:
        model = ResidentProfile
        fields = ['id', 'user_type', 'status', 'flat', 'joined_at']
        read_only_fields = ['id', 'status', 'joined_at']
```

---

### 7. ResidentApprovalSerializer

**Purpose:** Minimal serializer for approve/reject endpoints. Input is empty (the action is implicit from the URL). Output is the updated `ResidentProfile`.

This can simply re-use `ResidentProfileSerializer` for output. The view handles the status update directly without needing input validation.

Stub:
```python
class ResidentApprovalSerializer(serializers.ModelSerializer):
    """No write fields — action is implicit. Re-use for output only."""
    flat = FlatSerializer(read_only=True)

    class Meta:
        model = ResidentProfile
        fields = ['id', 'user_type', 'status', 'flat', 'joined_at']
        read_only_fields = fields
```

---

## Key Design Notes

**`buildings` field is write-only.** It is a `ListField` with a `CharField` child, not a nested serializer. It must be popped from `validated_data` before passing to `Community.objects.create()` because `Community` has no `buildings` model field.

**`admin_user` injection.** `CommunityRegistrationSerializer.create()` reads `self.context['request'].user`. The view must pass `context={'request': request}` when instantiating the serializer (this is the standard DRF pattern when `request` is needed inside `create()`).

**`NotFound` vs `ValidationError` in `JoinCommunitySerializer`.** Raising `rest_framework.exceptions.NotFound` inside `validate()` short-circuits DRF's validation and returns a 404 response. This is the correct behavior for an unknown invite code — it prevents attackers from knowing whether an invite code exists.

**`transaction.atomic()` in `create()`.** The `CommunityRegistrationSerializer.create()` must wrap both the `Community.objects.create()` call and the subsequent `Building.objects.bulk_create()` in a single atomic block. If `bulk_create` fails, the Community row is rolled back.

**Invite code lookup is always `exact`.** The `JoinCommunitySerializer` normalizes input to uppercase before querying. The `Community.invite_code` field stores only uppercase values (enforced by the model's `save()` method in section 01). Lookups are therefore case-sensitive `exact` — no `iexact` filter needed.

**`slug` and `invite_code` are read-only in `CommunityRegistrationSerializer`.** They are generated in the view layer (slug + invite_code generation, collision handling) and set on the Community instance before the serializer's `create()` is called, or the view directly creates the Community and passes the instance. The exact handoff point between view and serializer for these generated fields is up to the implementer — a clean approach is to generate them in the view, pass them in `serializer.save(slug=slug, invite_code=code, admin_user=request.user)`.

---

## Import Checklist

```python
import re
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from apps.communities.models import Community, Building, Flat, ResidentProfile
```