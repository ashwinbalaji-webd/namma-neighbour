import pytest
from unittest.mock import MagicMock

from apps.communities.models import Building, Community, ResidentProfile
from apps.communities.serializers import (
    CommunityRegistrationSerializer,
    JoinCommunitySerializer,
    ResidentProfileSerializer,
)


def make_community(**kwargs):
    defaults = {"name": "Sunrise Apartments", "city": "Bengaluru"}
    defaults.update(kwargs)
    return Community.objects.create(**defaults)


def make_user(phone="+919876543210"):
    from apps.users.models import User
    return User.objects.create_user(phone=phone, password="x")


def make_request(user):
    req = MagicMock()
    req.user = user
    return req


# ─── CommunityRegistrationSerializer ─────────────────────────────────────────

class TestCommunityRegistrationSerializer:
    def test_valid_payload_contains_community_fields_and_buildings(self):
        """Valid input → validated_data has name, city, pincode, address, buildings list."""
        data = {
            "name": "Sunrise Apartments",
            "city": "Bengaluru",
            "pincode": "560001",
            "address": "123 MG Road",
            "buildings": ["Tower A", "Tower B"],
        }
        serializer = CommunityRegistrationSerializer(data=data)
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["name"] == "Sunrise Apartments"
        assert serializer.validated_data["buildings"] == ["Tower A", "Tower B"]

    def test_pincode_must_be_6_digits(self):
        """pincode='12345' (5 digits) or '12345A' (non-numeric) → ValidationError."""
        for bad_pincode in ["12345", "12345A", "1234567", ""]:
            data = {
                "name": "Test", "city": "City", "pincode": bad_pincode,
                "address": "Addr", "buildings": ["A"],
            }
            serializer = CommunityRegistrationSerializer(data=data)
            assert not serializer.is_valid(), f"Expected invalid for pincode={bad_pincode!r}"
            assert "pincode" in serializer.errors

    def test_empty_buildings_list_raises_validation_error(self):
        """buildings=[] → ValidationError."""
        data = {
            "name": "Test", "city": "City", "pincode": "123456",
            "address": "Addr", "buildings": [],
        }
        serializer = CommunityRegistrationSerializer(data=data)
        assert not serializer.is_valid()
        assert "buildings" in serializer.errors

    def test_duplicate_building_names_in_list_raises_validation_error(self):
        """buildings=['Tower A', 'Tower A'] → ValidationError."""
        data = {
            "name": "Test", "city": "City", "pincode": "123456",
            "address": "Addr", "buildings": ["Tower A", "Tower A"],
        }
        serializer = CommunityRegistrationSerializer(data=data)
        assert not serializer.is_valid()
        assert "buildings" in serializer.errors


# ─── JoinCommunitySerializer ──────────────────────────────────────────────────

@pytest.mark.django_db
class TestJoinCommunitySerializer:
    def test_valid_invite_code_case_insensitive_resolves_community(self):
        """Input invite_code='abc123' resolves community whose invite_code='ABC123'."""
        community = make_community()
        building = Building.objects.create(community=community, name="Block A")
        user = make_user()
        data = {
            "invite_code": community.invite_code.lower(),
            "building_id": building.id,
            "flat_number": "101",
            "user_type": ResidentProfile.UserType.TENANT,
        }
        serializer = JoinCommunitySerializer(data=data, context={"request": make_request(user)})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["community"] == community

    def test_nonexistent_invite_code_raises_not_found(self):
        """Unknown invite_code → raises NotFound (HTTP 404, not 400)."""
        from rest_framework.exceptions import NotFound
        user = make_user()
        data = {
            "invite_code": "ZZZZZZ",
            "building_id": 9999,
            "flat_number": "101",
            "user_type": ResidentProfile.UserType.TENANT,
        }
        serializer = JoinCommunitySerializer(data=data, context={"request": make_request(user)})
        with pytest.raises(NotFound):
            serializer.is_valid(raise_exception=True)

    def test_building_id_not_in_resolved_community_raises_validation_error(self):
        """building_id belonging to a different community → ValidationError."""
        c1 = make_community(name="First")
        c2 = make_community(name="Second", city="Chennai")
        building_in_c2 = Building.objects.create(community=c2, name="Block B")
        user = make_user()
        data = {
            "invite_code": c1.invite_code,
            "building_id": building_in_c2.id,
            "flat_number": "101",
            "user_type": ResidentProfile.UserType.TENANT,
        }
        serializer = JoinCommunitySerializer(data=data, context={"request": make_request(user)})
        assert not serializer.is_valid()

    def test_user_already_has_resident_profile_raises_validation_error(self):
        """User with existing ResidentProfile → ValidationError (400)."""
        community = make_community()
        building = Building.objects.create(community=community, name="Block A")
        user = make_user()
        ResidentProfile.objects.create(
            user=user, community=community,
            user_type=ResidentProfile.UserType.TENANT,
        )
        data = {
            "invite_code": community.invite_code,
            "building_id": building.id,
            "flat_number": "101",
            "user_type": ResidentProfile.UserType.TENANT,
        }
        serializer = JoinCommunitySerializer(data=data, context={"request": make_request(user)})
        assert not serializer.is_valid()

    def test_inactive_community_invite_code_raises_validation_error(self):
        """community.is_active=False → ValidationError."""
        community = make_community(is_active=False)
        building = Building.objects.create(community=community, name="Block A")
        user = make_user()
        data = {
            "invite_code": community.invite_code,
            "building_id": building.id,
            "flat_number": "101",
            "user_type": ResidentProfile.UserType.TENANT,
        }
        serializer = JoinCommunitySerializer(data=data, context={"request": make_request(user)})
        assert not serializer.is_valid()


# ─── ResidentProfileSerializer ────────────────────────────────────────────────

@pytest.mark.django_db
class TestResidentProfileSerializer:
    def test_output_includes_nested_flat_user_type_status_joined_at(self):
        """Serialized output has flat (nested), user_type, status, joined_at fields."""
        user = make_user()
        community = make_community()
        profile = ResidentProfile.objects.create(
            user=user, community=community,
            user_type=ResidentProfile.UserType.TENANT,
        )
        data = ResidentProfileSerializer(profile).data
        assert "user_type" in data
        assert "status" in data
        assert "flat" in data
        assert "joined_at" in data

    def test_output_does_not_expose_user_phone_or_pii(self):
        """phone, email, and other User PII are absent from serialized output."""
        user = make_user()
        community = make_community()
        profile = ResidentProfile.objects.create(
            user=user, community=community,
            user_type=ResidentProfile.UserType.TENANT,
        )
        data = ResidentProfileSerializer(profile).data
        assert "phone" not in data
        assert "user" not in data
        assert "password" not in data
