import pytest
from django.db import IntegrityError

from apps.users.models import User, UserRole, PhoneOTP
from apps.users.tests.factories import UserFactory, UserRoleFactory, PhoneOTPFactory
from apps.communities.tests.factories import CommunityFactory


@pytest.mark.django_db
class TestUserModel:
    def test_create_user_with_phone(self):
        user = UserFactory(phone="+919876543210")
        assert user.phone == "+919876543210"
        assert user.id is not None

    def test_user_has_no_username_field(self):
        user = UserFactory()
        assert not hasattr(user, "username")

    def test_username_field_is_phone(self):
        assert User.USERNAME_FIELD == "phone"

    def test_required_fields_is_empty(self):
        assert User.REQUIRED_FIELDS == []

    def test_active_community_is_nullable(self):
        user = UserFactory()
        assert user.active_community is None

    def test_deleting_community_sets_active_community_to_null(self):
        community = CommunityFactory()
        user = UserFactory(active_community=community)
        assert user.active_community == community
        community.delete()
        user.refresh_from_db()
        assert user.active_community is None

    def test_create_superuser(self):
        superuser = User.objects.create_superuser(phone="+919999999999", password="testpass")
        assert superuser.is_staff is True
        assert superuser.is_superuser is True

    def test_superuser_has_password(self):
        superuser = User.objects.create_superuser(phone="+919999999999", password="testpass")
        assert superuser.has_usable_password() is True

    def test_phone_is_unique(self):
        phone = "+919876543210"
        UserFactory(phone=phone)
        with pytest.raises(IntegrityError):
            UserFactory(phone=phone)

    def test_phone_max_length(self):
        user = UserFactory(phone="+91XXXXXXXXXX")
        assert len(user.phone) == 13


@pytest.mark.django_db
class TestUserRoleModel:
    def test_platform_admin_role_allows_null_community(self):
        user = UserFactory()
        role = UserRoleFactory(user=user, role="platform_admin", community=None)
        assert role.community is None

    def test_unique_together_prevents_duplicates(self):
        user = UserFactory()
        community = CommunityFactory()
        UserRoleFactory(user=user, role="resident", community=community)
        with pytest.raises(IntegrityError):
            UserRoleFactory(user=user, role="resident", community=community)

    def test_index_on_user_and_community_exists(self):
        indexes = UserRole._meta.indexes
        assert len(indexes) > 0
        index_fields = [idx.fields for idx in indexes]
        assert ["user", "community"] in index_fields

    def test_user_can_have_multiple_roles_in_same_community(self):
        user = UserFactory()
        community = CommunityFactory()
        resident_role = UserRoleFactory(user=user, role="resident", community=community)
        vendor_role = UserRoleFactory(user=user, role="vendor", community=community)
        assert resident_role.id != vendor_role.id

    def test_role_choices_are_valid(self):
        user = UserFactory()
        community = CommunityFactory()
        for role_choice, _ in UserRole.ROLE_CHOICES:
            role = UserRoleFactory(user=user, role=role_choice, community=community if role_choice != "platform_admin" else None)
            assert role.role == role_choice


@pytest.mark.django_db
class TestPhoneOTPModel:
    def test_phoneotp_has_required_fields(self):
        otp = PhoneOTPFactory()
        assert otp.phone is not None
        assert otp.otp_hash is not None
        assert otp.created_at is not None
        assert otp.is_used is not None
        assert otp.attempt_count is not None

    def test_is_used_defaults_to_false(self):
        otp = PhoneOTPFactory()
        assert otp.is_used is False

    def test_attempt_count_defaults_to_zero(self):
        otp = PhoneOTPFactory()
        assert otp.attempt_count == 0

    def test_index_on_phone_and_created_at_exists(self):
        indexes = PhoneOTP._meta.indexes
        assert len(indexes) > 0
        index_fields = [idx.fields for idx in indexes]
        assert ["phone", "created_at"] in index_fields

    def test_phoneotp_has_no_updated_at(self):
        otp = PhoneOTPFactory()
        assert not hasattr(otp, "updated_at")
