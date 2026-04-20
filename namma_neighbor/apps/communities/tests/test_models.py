import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F

from apps.communities.models import Building, Community, Flat, ResidentProfile


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_community(**kwargs):
    defaults = {"name": "Sunrise Apartments", "city": "Bengaluru"}
    defaults.update(kwargs)
    return Community.objects.create(**defaults)


def make_building(community=None, name="Block A"):
    if community is None:
        community = make_community()
    return Building.objects.create(community=community, name=name)


def make_flat(building=None, flat_number="101"):
    if building is None:
        building = make_building()
    return Flat.objects.create(building=building, flat_number=flat_number)


# ─── Community: invite code ────────────────────────────────────────────────────

@pytest.mark.django_db
class TestCommunityInviteCode:
    def test_invite_code_auto_generated_on_save_when_blank(self):
        """A Community saved with no invite_code should have a non-blank 6-char code."""
        c = make_community()
        assert c.invite_code != ""
        assert len(c.invite_code) == 6

    def test_invite_code_is_uppercase(self):
        """The generated invite_code must contain only uppercase letters and digits."""
        c = make_community()
        assert c.invite_code == c.invite_code.upper()
        assert c.invite_code.isalnum()

    def test_invite_code_collision_retries_without_raising_integrity_error(self):
        """If the first generated code collides, the model retries silently."""
        from unittest.mock import patch
        existing = make_community(name="First")
        colliding_code = existing.invite_code
        call_count = 0

        def fake_generate():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return colliding_code
            return "UNIQUE"

        with patch("apps.communities.models._generate_invite_code", side_effect=fake_generate):
            second = make_community(name="Second", city="Chennai")
        assert second.invite_code == "UNIQUE"
        assert call_count == 2

    def test_invite_code_uniqueness_at_db_level(self):
        """Two communities cannot have the same invite_code (IntegrityError)."""
        c1 = make_community(name="First")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Community.objects.create(
                    name="Second",
                    city="Chennai",
                    invite_code=c1.invite_code,
                )


# ─── Community: slug ──────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestCommunitySlug:
    def test_slug_derived_from_name_and_city(self):
        """slugify(name + '-' + city) should be stored in the slug field."""
        from apps.communities.models import generate_unique_slug
        slug = generate_unique_slug("Sunrise Apartments", "Bengaluru")
        assert slug == "sunrise-apartments-bengaluru"

    def test_duplicate_slug_gets_numeric_suffix(self):
        """Second community with same name+city gets '-2' suffix."""
        from apps.communities.models import generate_unique_slug
        c1 = make_community(name="Green Park")
        c1.slug = generate_unique_slug("Green Park", "Bengaluru")
        c1.save()

        slug2 = generate_unique_slug("Green Park", "Bengaluru")
        assert slug2 == "green-park-bengaluru-2"

    def test_slug_not_updated_after_creation(self):
        """Changing name or city on an existing Community must not alter slug."""
        c = make_community(name="Oak Heights")
        c.slug = "oak-heights-bengaluru"
        c.save()
        original_slug = c.slug
        c.name = "Maple Heights"
        c.city = "Mumbai"
        c.save()
        c.refresh_from_db()
        assert c.slug == original_slug


# ─── Community: defaults ─────────────────────────────────────────────────────

@pytest.mark.django_db
class TestCommunityDefaults:
    def test_is_reviewed_defaults_to_false(self):
        """Newly created Community.is_reviewed must be False."""
        c = make_community()
        assert c.is_reviewed is False

    def test_resident_count_starts_at_zero(self):
        """Community.resident_count must be 0 on creation."""
        c = make_community()
        assert c.resident_count == 0

    def test_f_expression_increment_is_atomic(self):
        """After F('resident_count') + 1 update, resident_count == 1."""
        c = make_community()
        Community.objects.filter(pk=c.pk).update(resident_count=F("resident_count") + 1)
        c.refresh_from_db()
        assert c.resident_count == 1


# ─── Building ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestBuildingModel:
    def test_building_belongs_to_community(self):
        """Building.community FK should resolve to the correct Community."""
        c = make_community()
        b = make_building(community=c)
        assert b.community == c

    def test_unique_together_community_name(self):
        """Creating two Buildings with the same community+name raises IntegrityError."""
        c = make_community()
        make_building(community=c, name="Tower A")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Building.objects.create(community=c, name="Tower A")

    def test_different_communities_can_share_building_names(self):
        """Same building name is allowed for two different communities."""
        c1 = make_community(name="First")
        c2 = make_community(name="Second", city="Chennai")
        b1 = make_building(community=c1, name="Block A")
        b2 = make_building(community=c2, name="Block A")
        assert b1.pk != b2.pk


# ─── Flat ─────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestFlatModel:
    def test_unique_together_building_flat_number(self):
        """Duplicate (building, flat_number) raises IntegrityError."""
        b = make_building()
        make_flat(building=b, flat_number="101")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Flat.objects.create(building=b, flat_number="101")

    def test_floor_inference_three_digit_number(self):
        """flat_number='304' should infer floor=3."""
        from apps.communities.models import infer_floor
        assert infer_floor("304") == 3

    def test_floor_inference_four_digit_number(self):
        """flat_number='1205' should infer floor=12."""
        from apps.communities.models import infer_floor
        assert infer_floor("1205") == 12

    def test_floor_inference_non_numeric_returns_none(self):
        """flat_number='A4' or 'GF' should leave floor=None without raising."""
        from apps.communities.models import infer_floor
        assert infer_floor("A4") is None
        assert infer_floor("GF") is None

    def test_floor_inference_two_digit_number(self):
        """flat_number='12' should infer floor=1."""
        from apps.communities.models import infer_floor
        assert infer_floor("12") == 1


# ─── ResidentProfile ──────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestResidentProfileModel:
    def _make_user(self, phone="+919876543210"):
        from apps.users.models import User
        return User.objects.create_user(phone=phone, password="x")

    def _make_profile(self, user, community=None, flat=None):
        if community is None:
            community = make_community()
        return ResidentProfile.objects.create(
            user=user,
            community=community,
            flat=flat,
            user_type=ResidentProfile.UserType.TENANT,
        )

    def test_one_to_one_user_prevents_second_profile(self):
        """Creating a second ResidentProfile for the same User raises IntegrityError."""
        user = self._make_user()
        c1 = make_community(name="First")
        c2 = make_community(name="Second", city="Chennai")
        self._make_profile(user, community=c1)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ResidentProfile.objects.create(
                    user=user,
                    community=c2,
                    user_type=ResidentProfile.UserType.TENANT,
                )

    def test_two_profiles_can_share_same_flat(self):
        """Two different users with the same Flat FK both save without error."""
        u1 = self._make_user("+919876543210")
        u2 = self._make_user("+919876543211")
        flat = make_flat()
        c = flat.building.community
        p1 = self._make_profile(u1, community=c, flat=flat)
        p2 = self._make_profile(u2, community=c, flat=flat)
        assert p1.pk != p2.pk

    def test_status_defaults_to_pending(self):
        """ResidentProfile.status must be 'PENDING' on creation."""
        user = self._make_user()
        p = self._make_profile(user)
        assert p.status == ResidentProfile.Status.PENDING

    def test_user_type_rejects_invalid_choice(self):
        """Assigning an unknown user_type and calling full_clean() raises ValidationError."""
        user = self._make_user()
        community = make_community()
        profile = ResidentProfile(
            user=user,
            community=community,
            user_type="INVALID",
        )
        with pytest.raises(ValidationError):
            profile.full_clean()

    def test_rejected_record_persists(self):
        """Setting status='REJECTED' and saving does not delete the record."""
        user = self._make_user()
        p = self._make_profile(user)
        p.status = ResidentProfile.Status.REJECTED
        p.save()
        assert ResidentProfile.objects.filter(pk=p.pk).exists()
